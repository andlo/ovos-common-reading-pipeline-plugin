"""
skill OVOS Common Tales
Copyright (C) 2026  Andreas Lorensen

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

---

This skill orchestrates 'tell me a story' across *provider* skills
(ovos-skill-andersen-tales, ovos-skill-grimm-tales,
ovos-skill-andrew-lang-tales, and any future ones), the same way OCP
(ovos-common-play) orchestrates 'play X' across media skills:

- Provider skills own no intents and do no narration - they just answer
  search/fetch bus requests with story metadata and text.
- This skill owns all the user-facing conversation: intents, the "is it
  that one?" disambiguation, narration pacing, and - importantly -
  bookmark/'continue' state, which is now tracked in ONE place regardless
  of which provider last told a story.

See README.md for the full ovos.common_tales.* bus protocol.
"""

from ovos_bus_client.message import Message
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import time


class StoryFetchError(Exception):
    """Raised when a provider skill doesn't answer a fetch_story request
    in time, or answers with no usable story text."""


# ovos.common_tales.* bus protocol - shared by convention (no package
# dependency) with provider skills, the same way OCP's ovos.common_play.*
# messages work.
COMMON_TALES_SEARCH = "ovos.common_tales.search"
COMMON_TALES_SEARCH_RESPONSE = "ovos.common_tales.search.response"
COMMON_TALES_FETCH_STORY = "ovos.common_tales.fetch_story"  # + ".{provider_skill_id}"
COMMON_TALES_FETCH_STORY_RESPONSE = "ovos.common_tales.fetch_story.response"

SEARCH_TIMEOUT = 2.0  # seconds to wait for provider skills to answer a search
FETCH_TIMEOUT = 10.0  # seconds to wait for the winning provider to deliver story text
CONFIDENCE_THRESHOLD = 0.8


def pick_best_candidate(candidates):
    """Pure helper (kept separate from the bus mechanics so it's easy to
    unit test): given a list of search.response payloads from provider
    skills, return the one with the highest confidence, or None if the
    list is empty."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.get("confidence", 0))


class CommonTales(OVOSSkill):

    @classproperty
    def runtime_requirements(self):
        # this skill does no network I/O itself - it only talks to
        # provider skills over the local messagebus, and delegates any
        # internet access to them
        return RuntimeRequirements(
            internet_before_load=False,
            network_before_load=False,
            requires_internet=False,
            requires_network=False,
            no_internet_fallback=True,
            no_network_fallback=True,
        )

    def initialize(self):
        self.is_reading = False
        # progress is keyed by "{provider_skill_id}::{story_id}" so stories
        # from different providers never collide, mirroring the per-title
        # progress tracking ovos-skill-fairytales already does, just now
        # spanning multiple provider skills instead of just one
        self.settings.setdefault('progress', {})
        self.settings.setdefault('last_story', None)  # candidate dict, see pick_best_candidate

    @intent_handler('Tales.intent')
    def handle_Tales(self, message: Message):
        if message.data.get("tale", "") is None:
            response = self.get_response('Tales', num_retries=1)
            if not response:
                return
        else:
            response = message.data.get("tale")
        self._search_and_tell(response)

    @intent_handler('TalesByCollection.intent')
    def handle_tales_by_collection(self, message: Message):
        """Handles phrasings that name a specific collection/author, e.g.
        'tell me a story from Grimm' or 'find Cinderella by Andersen'.
        {tale} is optional here - 'a story from Grimm' with no specific
        tale named is a valid 'surprise me' request to that collection."""
        collection_hint = message.data.get("collection")
        tale = message.data.get("tale")
        self._search_and_tell(tale, collection_hint=collection_hint)

    def _search_and_tell(self, phrase, collection_hint=None):
        candidates = self._search_providers(phrase, collection_hint=collection_hint)
        if not candidates:
            if collection_hint:
                self.speak_dialog('no_such_collection', data={"collection": collection_hint})
            else:
                self.speak_dialog('no_story_providers')
            return

        best = pick_best_candidate(candidates)
        if best["confidence"] < CONFIDENCE_THRESHOLD:
            self.speak_dialog('that_would_be', data={"story": best["title"]})
            confirm = self.ask_yesno('is_it_that')
            if not confirm or confirm == 'no':
                self.speak_dialog('no_story')
                return

        self._announce_and_tell(best, bookmark=0)

    @intent_handler('continue.intent')
    def handle_continue(self, message: Message):
        last = self.settings.get('last_story')
        if not last:
            self.speak_dialog('no_story_to_continue')
            return
        self.speak_dialog('continue', data={"story": last["title"]}, wait=True)
        key = self._progress_key(last)
        bookmark = self.settings.get('progress', {}).get(key, 0)
        self._tell_story(last, bookmark)

    def stop(self):
        if self.is_reading is True:
            self.speak_dialog('stop_telling_tales')
            self.is_reading = False
            return True
        return False

    @staticmethod
    def _progress_key(candidate):
        return f"{candidate['skill_id']}::{candidate['story_id']}"

    @staticmethod
    def _describe(candidate):
        """Build a spoken description from whatever metadata the winning
        provider supplied - gracefully skipping any fields it left out
        (not every provider necessarily has a 'collection', for instance)."""
        parts = [candidate["title"]]
        if candidate.get("author"):
            parts.append(f"by {candidate['author']}")
        if candidate.get("collection"):
            parts.append(f"from {candidate['collection']}")
        if candidate.get("source"):
            parts.append(f"sourced from {candidate['source']}")
        return ", ".join(parts)

    def _search_providers(self, phrase, collection_hint=None, timeout=SEARCH_TIMEOUT):
        """Broadcast a search to every provider skill and collect all
        responses for a short window (unlike _fetch_story, several
        providers are expected to answer here, not just one).

        collection_hint (optional) is a raw, unvalidated string like
        'grimm' or 'h c andersen' extracted from phrasings such as 'tell
        me a story from Grimm' - providers match it fuzzily against their
        own known friendly names and should only respond if it's a match
        (or if collection_hint is None, in which case everyone competes
        as usual)."""
        responses = []

        def collect(message):
            responses.append(message.data)

        self.bus.on(COMMON_TALES_SEARCH_RESPONSE, collect)
        try:
            self.bus.emit(Message(COMMON_TALES_SEARCH, {
                "phrase": phrase,
                "collection_hint": collection_hint,
                "requester": self.skill_id,
            }))
            time.sleep(timeout)
        finally:
            self.bus.remove(COMMON_TALES_SEARCH_RESPONSE, collect)
        return responses

    def _fetch_story(self, candidate, timeout=FETCH_TIMEOUT):
        skill_id = candidate["skill_id"]
        request = Message(f"{COMMON_TALES_FETCH_STORY}.{skill_id}",
                           {"story_id": candidate["story_id"], "requester": self.skill_id})
        response = self.bus.wait_for_response(
            request, reply_type=COMMON_TALES_FETCH_STORY_RESPONSE, timeout=timeout)
        if response is None:
            raise StoryFetchError(f"provider {skill_id} did not respond in time")
        paragraphs = response.data.get("paragraphs")
        if not paragraphs:
            raise StoryFetchError(f"provider {skill_id} returned no story text for {candidate['story_id']}")
        return paragraphs

    def _announce_and_tell(self, candidate, bookmark):
        self.speak_dialog('i_know_that', data={"description": self._describe(candidate)}, wait=True)
        self.settings['last_story'] = candidate
        self._tell_story(candidate, bookmark)

    def _tell_story(self, candidate, bookmark):
        self.is_reading = True
        try:
            paragraphs = self._fetch_story(candidate)
        except StoryFetchError as e:
            self.log.error(f"Could not fetch story: {e}")
            self.is_reading = False
            self.speak_dialog('story_unavailable')
            return

        key = self._progress_key(candidate)
        for i, para in enumerate(paragraphs[bookmark:], start=bookmark):
            self.settings['progress'][key] = i + 1
            if self.is_reading is False:
                break
            for sentence in para.split('. '):
                if self.is_reading is False:
                    break
                self.speak_dialog(sentence, wait=True)

        if self.is_reading is True:
            self.is_reading = False
            self.settings['progress'].pop(key, None)
            self.settings['last_story'] = None
            self.speak_dialog('from_Tales', data={"source": candidate.get("source") or "the storyteller"})
