"""
skill OVOS Common Reading
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

This skill orchestrates 'read me something' across *provider* skills
(fairy tale collections, but also potentially books, articles, poems, and
any other text-based content), the same way OCP (ovos-common-play)
orchestrates 'play X' across media skills:

- Provider skills own no intents and do no narration - they just answer
  search/fetch bus requests with content metadata and text.
- This skill owns all the user-facing conversation: intents, the "is it
  that one?" disambiguation, narration pacing, and - importantly -
  bookmark/'continue' state, which is tracked in ONE place regardless of
  which provider last supplied the content.

See README.md for the full ovos.common_reading.* bus protocol.
"""

from ovos_bus_client.message import Message
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import time


class ContentFetchError(Exception):
    """Raised when a provider skill doesn't answer a fetch_content
    request in time, or answers with no usable text."""


# ovos.common_reading.* bus protocol - shared by convention (no package
# dependency) with provider skills, the same way OCP's ovos.common_play.*
# messages work.
COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"  # + ".{provider_skill_id}"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"

SEARCH_TIMEOUT = 2.0  # seconds to wait for provider skills to answer a search
FETCH_TIMEOUT = 10.0  # seconds to wait for the winning provider to deliver text
CONFIDENCE_THRESHOLD = 0.8


def pick_best_candidate(candidates):
    """Pure helper (kept separate from the bus mechanics so it's easy to
    unit test): given a list of search.response payloads from provider
    skills, return the one with the highest confidence, or None if the
    list is empty."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.get("confidence", 0))


class CommonReading(OVOSSkill):

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
        # progress is keyed by "{provider_skill_id}::{content_id}" so
        # content from different providers never collides, mirroring the
        # per-title progress tracking ovos-skill-fairytales already did,
        # just now spanning multiple provider skills instead of just one
        self.settings.setdefault('progress', {})
        self.settings.setdefault('last_content', None)  # candidate dict, see pick_best_candidate

    @intent_handler('ReadContent.intent')
    def handle_read_content(self, message: Message):
        if message.data.get("title", "") is None:
            response = self.get_response('ReadContent', num_retries=1)
            if not response:
                return
        else:
            response = message.data.get("title")
        self._search_and_read(response)

    @intent_handler('ReadContentByCollection.intent')
    def handle_read_by_collection(self, message: Message):
        """Handles phrasings that name a specific collection/author/
        publication, e.g. 'read me a story from Grimm' or 'find
        Cinderella by Andersen'. {title} is optional here - 'a story
        from Grimm' with no specific title named is a valid 'surprise
        me' request to that collection."""
        collection_hint = message.data.get("collection")
        title = message.data.get("title")
        self._search_and_read(title, collection_hint=collection_hint)

    @intent_handler('continue.intent')
    def handle_continue(self, message: Message):
        last = self.settings.get('last_content')
        if not last:
            self.speak_dialog('nothing_to_continue')
            return
        self.speak_dialog('continue', data={"title": last["title"]}, wait=True)
        key = self._progress_key(last)
        bookmark = self.settings.get('progress', {}).get(key, 0)
        self._read_content(last, bookmark)

    def stop(self):
        if self.is_reading is True:
            self.speak_dialog('stop_reading')
            self.is_reading = False
            return True
        return False

    def _search_and_read(self, phrase, collection_hint=None, content_type=None):
        candidates = self._search_providers(phrase, collection_hint=collection_hint, content_type=content_type)
        if not candidates:
            if collection_hint:
                self.speak_dialog('no_such_collection', data={"collection": collection_hint})
            else:
                self.speak_dialog('no_content_providers')
            return

        best = pick_best_candidate(candidates)
        if best["confidence"] < CONFIDENCE_THRESHOLD:
            self.speak_dialog('that_would_be', data={"title": best["title"]})
            confirm = self.ask_yesno('is_it_that')
            if not confirm or confirm == 'no':
                self.speak_dialog('no_content')
                return

        self._announce_and_read(best, bookmark=0)

    @staticmethod
    def _progress_key(candidate):
        return f"{candidate['skill_id']}::{candidate['content_id']}"

    @staticmethod
    def _describe(candidate):
        """Build a spoken description from whatever metadata the winning
        provider supplied - gracefully skipping any fields it left out
        (not every provider necessarily has a 'collection', for instance).
        If the provider flagged 'machine_translated', that's disclosed
        here too, since this runs right before reading starts."""
        parts = [candidate["title"]]
        if candidate.get("author"):
            parts.append(f"by {candidate['author']}")
        if candidate.get("collection"):
            parts.append(f"from {candidate['collection']}")
        if candidate.get("source"):
            parts.append(f"sourced from {candidate['source']}")
        if candidate.get("machine_translated"):
            parts.append("machine translated")
        return ", ".join(parts)

    def _search_providers(self, phrase, collection_hint=None, content_type=None, timeout=SEARCH_TIMEOUT):
        """Broadcast a search to every provider skill and collect all
        responses for a short window (unlike _fetch_content, several
        providers are expected to answer here, not just one).

        collection_hint (optional) is a raw, unvalidated string like
        'grimm' or 'h c andersen' - providers match it fuzzily against
        their own known friendly names and should only respond if it's a
        match, or if collection_hint is None (in which case everyone
        competes as usual).

        content_type (optional) is a raw hint like 'story', 'book',
        'article' or 'poem' - providers that only offer one kind of
        content may use it to decide whether to respond at all, but
        should not require it (a provider offering only fairy tales can
        just ignore this field and always respond)."""
        responses = []

        def collect(message):
            responses.append(message.data)

        self.bus.on(COMMON_READING_SEARCH_RESPONSE, collect)
        try:
            self.bus.emit(Message(COMMON_READING_SEARCH, {
                "phrase": phrase,
                "collection_hint": collection_hint,
                "content_type": content_type,
                "requester": self.skill_id,
            }))
            time.sleep(timeout)
        finally:
            self.bus.remove(COMMON_READING_SEARCH_RESPONSE, collect)
        return responses

    def _fetch_content(self, candidate, timeout=FETCH_TIMEOUT):
        skill_id = candidate["skill_id"]
        request = Message(f"{COMMON_READING_FETCH_CONTENT}.{skill_id}",
                           {"content_id": candidate["content_id"], "requester": self.skill_id})
        response = self.bus.wait_for_response(
            request, reply_type=COMMON_READING_FETCH_CONTENT_RESPONSE, timeout=timeout)
        if response is None:
            raise ContentFetchError(f"provider {skill_id} did not respond in time")
        paragraphs = response.data.get("paragraphs")
        if not paragraphs:
            raise ContentFetchError(f"provider {skill_id} returned no text for {candidate['content_id']}")
        return paragraphs

    def _announce_and_read(self, candidate, bookmark):
        self.speak_dialog('i_know_that', data={"description": self._describe(candidate)}, wait=True)
        self.settings['last_content'] = candidate
        self._read_content(candidate, bookmark)

    def _read_content(self, candidate, bookmark):
        self.is_reading = True
        try:
            paragraphs = self._fetch_content(candidate)
        except ContentFetchError as e:
            self.log.error(f"Could not fetch content: {e}")
            self.is_reading = False
            self.speak_dialog('content_unavailable')
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
            self.settings['last_content'] = None
            self.speak_dialog('finished_reading', data={"source": candidate.get("source") or "the source"})
