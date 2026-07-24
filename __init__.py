"""
OVOS Common Reading - pipeline plugin
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

An OVOS pipeline plugin that orchestrates "read me something" across
*provider* skills - broadcasting a search, picking the best answer, and
reading it aloud with bookmark/"continue" support, all from one
dedicated stage in ovos-core's intent pipeline.

Provider skills implement the ovos.common_reading.* bus protocol - see
README.md for the full spec.

Utterance matching uses padacioso (pure Python, no native dependencies),
trained at runtime from the *.intent files bundled per language in
locale/<lang>/.
"""


import os
from os.path import dirname
from typing import Dict, List, Optional, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.pipeline import PipelinePlugin, IntentHandlerMatch
from ovos_utils.fakebus import FakeBus
from ovos_workshop.app import OVOSAbstractApplication
from padacioso import IntentContainer

import time


class ContentFetchError(Exception):
    """Raised when a provider skill doesn't answer a fetch_content
    request in time, or answers with no usable text."""


# ovos.common_reading.* bus protocol - shared by convention (no package
# dependency) with provider skills, the same way OCP's ovos.common_play.*
# messages work. Unchanged from the skill-based version.
COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"  # + ".{provider_skill_id}"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"
# ping/pong: a lightweight 'is anyone there?' check, only broadcast on
# the rare 0-candidates path (see #2) - never on every search. Lets the
# pipeline distinguish 'no reading skills installed at all' from
# 'skills are installed but nothing matched', without the pipeline ever
# needing to know or guess about languages: a provider that refused to
# load for an unsupported device language (the SUPPORTED_LANGUAGES gate
# in andersen-tales/grimm-tales/andrew-lang-tales/bechstein-tales/
# cosquin-tales) never registers a pong handler either, so it correctly
# stays silent here too.
COMMON_READING_PING = "ovos.common_reading.ping"
COMMON_READING_PONG = "ovos.common_reading.pong"

SEARCH_TIMEOUT = 2.0  # seconds to wait for provider skills to answer a search
FETCH_TIMEOUT = 10.0  # seconds to wait for the winning provider to deliver text
PING_TIMEOUT = 0.3  # seconds - short, since a pong is cheap (no index lookup)
CONFIDENCE_THRESHOLD = 0.8  # provider search-response confidence needed to skip "is it that one?"
MATCH_CONFIDENCE_THRESHOLD = 0.5  # padacioso utterance-match confidence needed to engage at all

# maps our internal intent names -> the *.intent file each is trained from
INTENT_FILES = {
    "read_content": "ReadContent.intent",
    "read_by_collection": "ReadContentByCollection.intent",
    "read_by_type": "ReadContentByType.intent",
    "continue": "continue.intent",
    "pause": "pause.intent",
}


def pick_best_candidate(candidates):
    """Pure helper (kept separate from the bus mechanics so it's easy to
    unit test): given a list of search.response payloads from provider
    skills, return the one with the highest confidence, or None if the
    list is empty."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.get("confidence", 0))


class CommonReadingPipeline(PipelinePlugin, OVOSAbstractApplication):

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        OVOSAbstractApplication.__init__(
            self, bus=bus, skill_id="ovos-common-reading-pipeline-plugin.andlo",
            resources_dir=dirname(__file__))
        PipelinePlugin.__init__(self, bus, config)
        self.is_reading = False
        self.settings.setdefault('progress', {})
        self.settings.setdefault('last_content', None)
        self._intent_containers = {}  # lang -> trained padacioso IntentContainer

    def _locale_dir_for(self, lang):
        base = os.path.join(dirname(__file__), "locale")
        candidate = os.path.join(base, lang.lower())
        if os.path.isdir(candidate):
            return candidate
        return os.path.join(base, "en-us")  # every provider/skill in this family falls back to English

    def _get_intent_container(self, lang):
        if lang in self._intent_containers:
            return self._intent_containers[lang]
        container = IntentContainer()
        lang_dir = self._locale_dir_for(lang)
        for intent_name, filename in INTENT_FILES.items():
            path = os.path.join(lang_dir, filename)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                samples = [line.strip() for line in f if line.strip()]
            if samples:
                container.add_intent(intent_name, samples)
        self._intent_containers[lang] = container
        return container

    def match(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        container = self._get_intent_container(lang)
        for utterance in utterances:
            result = container.calc_intent(utterance)
            name = result.get("name")
            if not name or result.get("conf", 0) < MATCH_CONFIDENCE_THRESHOLD:
                continue
            entities = result.get("entities", {})

            if name == "continue":
                if not self.settings.get('last_content'):
                    # nothing in progress here - decline rather than claim
                    # the utterance, so a later pipeline stage gets a
                    # chance instead
                    continue
                self._handle_continue()
            elif name == "pause":
                if not self.is_reading:
                    # nothing being read right now - same decline-rather-
                    # than-claim reasoning as "continue" above
                    continue
                self._handle_pause()
            elif name == "read_content":
                self._search_and_read(entities.get("title"))
            elif name == "read_by_collection":
                self._search_and_read(entities.get("title"), collection_hint=entities.get("collection"))
            elif name == "read_by_type":
                # "read me my horoscope" / "tell me today's horoscope" -
                # no {title}, just a content_type ("horoscope", "story",
                # etc) forwarded as a hint on the search broadcast (see
                # COMMON_READING_SEARCH's "content_type" field) so
                # provider skills can filter/respond appropriately.
                # Distinct phrasing ("my"/"today's") deliberately avoids
                # overlapping with read_content's "the story {title}"
                # patterns - see ReadContentByType.intent's own comment.
                self._search_and_read(None, content_type=entities.get("content_type"))
            else:
                continue

            return IntentHandlerMatch(match_type=f"{self.skill_id}:{name}",
                                       skill_id=self.skill_id, utterance=utterance)
        return None

    def stop(self):
        if self.is_reading is True:
            # wait=True is not optional here: without it, speak_dialog()
            # only enqueues the TTS request and returns immediately.
            # 'stop' is very likely to also trigger OVOS core's own
            # global audio-stop handling in the same moment, which
            # flushes the TTS queue - a just-enqueued, not-yet-started
            # confirmation gets silently wiped out by that flush. wait=True
            # blocks until the dialog has actually finished being spoken,
            # so nothing can race it away. Same reasoning applies to
            # _handle_pause() below. See the real bug report that led to
            # this: pause/stop were completely silent in practice despite
            # calling speak_dialog(), while _handle_continue() (which
            # already had wait=True) worked fine.
            self.speak_dialog('stop_reading', wait=True)
            self.is_reading = False
            return True
        return False

    def _handle_pause(self):
        """A dedicated 'pause' intent, matched by this pipeline's own
        padacioso parser rather than relying on OVOS's global stop
        vocabulary (self.stop(), above) - 'pause' isn't guaranteed to
        be a recognized synonym for 'stop' at the core level, so
        without this, saying 'pause' while reading could silently do
        nothing. Functionally identical to stop() (is_reading=False
        breaks the reading loop at the next sentence boundary, and
        progress is already bookmarked), just with a dialog that
        explicitly invites resuming rather than sounding final.

        wait=True for the same reason as stop() - see the comment
        there."""
        self.is_reading = False
        self.speak_dialog('paused', wait=True)

    def _handle_continue(self):
        last = self.settings.get('last_content')
        self.speak_dialog('continue', data={"title": last["title"]}, wait=True)
        key = self._progress_key(last)
        bookmark = self.settings.get('progress', {}).get(key, 0)
        self._read_content(last, bookmark)

    def _search_and_read(self, phrase, collection_hint=None, content_type=None):
        candidates = self._search_providers(phrase, collection_hint=collection_hint, content_type=content_type)
        if not candidates:
            self._handle_no_candidates(collection_hint)
            return

        best = pick_best_candidate(candidates)
        if best["confidence"] < CONFIDENCE_THRESHOLD:
            # wait=True is not optional here - same reasoning as
            # stop()/_handle_pause() above, and the exact same bug
            # shape: without it, speak_dialog() only enqueues the TTS
            # request and returns immediately, so ask_yesno() right
            # below opens its listening window before 'that_would_be'
            # has actually finished being spoken (and possibly before
            # 'is_it_that' has even started). Real bug report that led
            # to this: saying "yes" right after hearing "is it that
            # one?" was landing in fallback_unknown instead of being
            # caught here - the listening window had already opened
            # (and could time out) while audio was still queued/
            # playing, not synced to when the user could actually
            # have heard the question and started answering.
            self.speak_dialog('that_would_be', data={"title": best["title"]}, wait=True)
            confirm = self.ask_yesno('is_it_that')
            if not confirm or confirm == 'no':
                self.speak_dialog('no_content')
                return

        self._announce_and_read(best, bookmark=0)

    def _handle_no_candidates(self, collection_hint):
        """No search candidates - distinguish 'nothing is installed' from
        'something is installed but found nothing' via a lightweight
        ping/pong (see #2), rather than guessing at a fallback
        language or just saying the same generic thing either way."""
        if self._ping_providers():
            if collection_hint:
                self.speak_dialog('no_such_collection', data={"collection": collection_hint})
            else:
                self.speak_dialog('no_matching_content')
        else:
            self.speak_dialog('no_content_providers')

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
        providers are expected to answer here, not just one)."""
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

    def _ping_providers(self, timeout=PING_TIMEOUT):
        """Broadcast a lightweight 'is anyone there?' and collect pongs.
        Only called from _handle_no_candidates, on the rare 0-candidates
        path - never on every search, since a pong round trip would add
        latency to the common case for no benefit."""
        responses = []

        def collect(message):
            responses.append(message.data)

        self.bus.on(COMMON_READING_PONG, collect)
        try:
            self.bus.emit(Message(COMMON_READING_PING, {"requester": self.skill_id}))
            time.sleep(timeout)
        finally:
            self.bus.remove(COMMON_READING_PONG, collect)
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

        # Flattened to a single sentence list up front, so the bookmark
        # can track exactly where reading paused - at SENTENCE
        # granularity, not paragraph granularity. The bug this fixes:
        # tracking only "which paragraph" meant progress[key] got set
        # to i+1 the moment paragraph i STARTED, before its sentences
        # had actually been spoken - so pausing partway through a large
        # paragraph (e.g. a whole story with no \n\n breaks, coming
        # back from the provider as a single "paragraph") lost
        # everything remaining in it on resume: paragraphs[bookmark:]
        # skipped straight past the one paragraph entirely, the loop
        # ran zero times, and _read_content immediately spoke the
        # 'finished_reading' dialog as if the (unheard) rest had been
        # read.
        sentences = [s for para in paragraphs for s in para.split('. ')]

        key = self._progress_key(candidate)
        for i, sentence in enumerate(sentences[bookmark:], start=bookmark):
            if self.is_reading is False:
                break
            self.speak_dialog(sentence, wait=True)
            # only marked done AFTER actually speaking it - if pause
            # flips is_reading while this sentence is mid-speech,
            # speak_dialog(wait=True) still finishes it before
            # returning, so the bookmark correctly reflects that this
            # sentence WAS heard, while the next loop iteration's
            # is_reading check (above) correctly stops before the one
            # after it.
            self.settings['progress'][key] = i + 1

        if self.is_reading is True:
            self.is_reading = False
            self.settings['progress'].pop(key, None)
            self.settings['last_content'] = None
            self.speak_dialog('finished_reading', data={"source": candidate.get("source") or "the source"})
