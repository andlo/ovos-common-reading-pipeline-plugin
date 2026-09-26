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

How a request is handled, and why it is split the way it is:

- match() only classifies the utterance and decides whether to claim it.
  ovos-core (3.7+) gives every plugin's match() 10 seconds on a small
  worker pool and skips a session whose previous call is still running;
  anything slow in there makes the utterance fall through to later
  stages while this plugin carries on regardless.
- ovos-core then dispatches "<skill_id>:<intent>" to the handler
  registered for it in __init__. The handler does the quick part: the
  provider search, the "is it that one?" question when the best match is
  unsure, and the announcement. It returns as soon as the story starts,
  which is what ends the turn (mycroft.skill.handler.complete ->
  ovos.utterance.handled), so "stop" and "pause" reach this plugin while
  the story is being read.
- The story itself is read on a daemon thread, one sentence at a time.

Everything a story needs is kept per session (the session id in the
message context), because on a HiveMind hub one instance of this plugin
serves every connected user: one user's "stop" or "continue" must not
touch another user's story.
"""


import inspect
import os
import random
import re
import threading
import time
import unicodedata
from os.path import dirname
from typing import Dict, List, Optional, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.session import Session, SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_plugin_manager.templates.pipeline import PipelinePlugin, IntentHandlerMatch
from ovos_utils.fakebus import FakeBus
from ovos_workshop.app import OVOSAbstractApplication
from padacioso import IntentContainer


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
    "read_any_story": "ReadAnyStory.intent",
    "continue": "continue.intent",
    "pause": "pause.intent",
}
# A request for the news ("read the news", "read me the latest news about
# France", "read me today's news") belongs to news skills. They come later in
# the pipeline than this plugin, so whatever it claims never reaches them, and
# no provider in this family serves the news. The intents list no word for the
# news as a kind of text (see scripts/build_padacioso_intents.py), but their
# open slots can still capture one: English "read the {title}" and "read me
# my/today's {content_type}", Danish "læs dagens {content_type}". match()
# declines a title or content type holding a phrase from this file
# (locale/<lang>/news.voc); a language without one declines nothing.
NEWS_VOC = "news.voc"
# ...and each intent name -> the method that handles its dispatch. ovos-core
# dispatches a claimed utterance on "<skill_id>:<intent name>" (the
# match_type match() returns) and ends the turn when that handler reports
# mycroft.skill.handler.complete; with no handler registered for it, the turn
# only ended when the dispatcher's 5 minute timeout fired.
INTENT_HANDLERS = {
    "read_content": "handle_read_content",
    "read_by_collection": "handle_read_by_collection",
    "read_by_type": "handle_read_by_type",
    "read_any_story": "handle_read_any_story",
    "continue": "handle_continue",
    "pause": "handle_pause",
}
# The done-signal topic ovos-workshop's event wrapper emits around a handler
# (".start", then ".complete" or ".error"). ovos-core's dispatcher resolves
# an in-flight dispatch from it, keyed on the session, context["skill_id"]
# and data["intent_name"].
HANDLER_INFO = "mycroft.skill.handler"

# "Tell me a story" names no title and no content type of its own. The search
# goes out with phrase=None and this hint, whatever language the words were
# in, so a provider that only offers horoscopes or blog posts can stay
# silent, and a story provider answers with one story of its own choosing.
ANY_STORY_CONTENT_TYPE = "story"

# Session everything falls back to when a message names none: a local,
# single-user device, and where bookmarks written before sessions were
# tracked are carried over to.
DEFAULT_SESSION_ID = "default"
# A hub meets many sessions over its life. Bookmarks are kept for this many
# (the most recently used, plus the default session and any session that is
# reading right now), so the settings file cannot grow without bound.
MAX_REMEMBERED_SESSIONS = 50

# Longest chunk handed to TTS in one speak(wait=True) call. That wait
# gives up after 15s (ovos_bus_client's wait_while_speaking), and at 12-15
# spoken characters a second a 160-character chunk stays well inside it. A
# sentence longer than this is cut at a clause boundary instead (#35).
MAX_SPOKEN_CHARS = 160
# ...but not into shards: a cut never leaves a piece shorter than this.
MIN_CLAUSE_CHARS = 40
# Bumped whenever sentence splitting changes what a bookmark index points at,
# so bookmarks written by an older splitter can be carried over (see
# migrate_bookmark) instead of resuming a few sentences off.
SPLITTER_VERSION = 2

# A '.' after one of these is not the end of a sentence ("Mr. Fox", "z.B.").
# Lower case, without the final dot. Deliberately no bare "no": "No." is a
# whole sentence of dialogue far more often than an abbreviation of "number".
_ABBREVIATIONS = {
    # en
    "mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "rev", "gen", "capt", "lt",
    "col", "mt", "vs", "etc", "e.g", "i.e", "vol", "ch", "fig", "approx",
    # da
    "hr", "fru", "frk", "bl.a", "f.eks", "osv", "dvs", "nr", "ca", "jf", "pga", "evt", "kl",
    # de
    "fr", "frl", "bzw", "z.b", "u.a", "usw", "vgl", "ggf", "bspw",
    # fr
    "m", "mm", "mme", "mlle", "ste", "p.ex", "cf",
    # es / pt
    "sra", "srta", "dra", "d", "vd", "ud", "uds", "p.ej", "v.ex",
    # it
    "sig", "sigg", "dott", "ecc",
    # nl
    "dhr", "mevr", "mw", "bijv", "enz", "o.a", "blz",
}
# What closes a quotation after its terminator. Danish and German close with
# “ and « as often as English does with ” and » (»Hej!« sagde han, „Hilfe!“).
_CLOSERS = "\"'”’»«“‘)]"
# A terminator, any closing quotes or brackets after it, then the space
# before the next sentence. French sets its closing quote off with a space
# (« Bonjour ! » dit-il); a spaced » or ” counts as closing only when a space
# follows it too, since an opening quote is always followed by its word
# (Danish opens with »: Han gik. »Hej!« sagde hun.).
_SENTENCE_END = re.compile(
    r"(?:\.{3}|[.!?…])+[" + re.escape(_CLOSERS) + r"]*(?:\s[»”’](?=\s))?(?=\s)"
)
_DOTTED_INITIALS = re.compile(r"(?:[^\W\d_]\.)+[^\W\d_]")
_CLAUSE_BREAK = re.compile(r"[,;:](?=\s)|\s(?:--|—|–)(?=\s)")


def _ends_sentence(text: str, match) -> bool:
    """Whether the terminator in `match` really ends a sentence."""
    rest = text[match.end():].lstrip()
    if not rest:
        return True
    # Dialogue attribution carries on the same sentence: '"Oh!" said she.'
    if rest[0].islower():
        return False
    terminator = match.group(0).rstrip(_CLOSERS + " ")
    if terminator != ".":
        return True
    word = text[:match.start()].split()[-1:] or [""]
    word = word[0].lstrip("\"'“‘«„([").lower()
    if word in _ABBREVIATIONS:
        return False
    # An initial ("H. C. Andersen") or an ordinal ("den 1. januar", "am 3. Mai");
    # a year ("In 1805. Then...") still ends its sentence.
    if len(word) == 1 and word.isalpha():
        return False
    # Dotted initials written without spaces ("H.C. Andersen", "J.R.R. Tolkien",
    # "U.S."): the word before the final dot is letter-dot-letter.
    if _DOTTED_INITIALS.fullmatch(word):
        return False
    if word.isdigit() and len(word) <= 2:
        return False
    return True


def _cap_length(sentence: str, limit: int) -> List[str]:
    """Cut a sentence longer than `limit` at clause boundaries (#35).

    The cut goes at the last comma, semicolon, colon or dash that keeps the
    piece within `limit` and at least MIN_CLAUSE_CHARS long; failing that, at
    the last space. Every word is kept, in order.
    """
    pieces = []
    while len(sentence) > limit:
        cut = None
        for match in _CLAUSE_BREAK.finditer(sentence, 0, limit + 1):
            if match.end() >= MIN_CLAUSE_CHARS:
                cut = match.end()
        if cut is None:
            cut = sentence.rfind(" ", MIN_CLAUSE_CHARS, limit + 1)
        if cut <= 0:
            break
        pieces.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    if sentence:
        pieces.append(sentence)
    return pieces


def split_sentences(text: str, limit: int = MAX_SPOKEN_CHARS) -> List[str]:
    """Split a paragraph into chunks to speak one at a time.

    Sentences end at '.', '!', '?', '…' or '...' (closing quotes stay with
    their sentence), but not after an abbreviation, an initial or an ordinal,
    and not when the next word goes on in lower case. Each keeps its own
    punctuation, which is what gives a question its rising tone. A sentence
    longer than `limit` is cut further at clause boundaries.
    """
    text = " ".join(str(text).split())
    sentences, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        if _ends_sentence(text, match):
            sentences.append(text[start:match.end()].strip())
            start = match.end()
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return [piece for sentence in sentences for piece in _cap_length(sentence, limit)]


def migrate_bookmark(paragraphs: List[str], legacy_index: int) -> int:
    """Carry a bookmark written by the old '. ' splitter over to this one.

    The index counted chunks of the old split; the same number now points
    somewhere else. Words are what both splits share, so the bookmark moves
    to the chunk holding the first word not yet heard: at worst a sentence
    is heard twice, never skipped.
    """
    old = [s for para in paragraphs for s in para.split('. ')]
    heard = sum(len(chunk.split()) for chunk in old[:legacy_index])
    index, counted = 0, 0
    for para in paragraphs:
        for chunk in split_sentences(para):
            words = len(chunk.split())
            if counted + words > heard:
                return index
            counted += words
            index += 1
    return index


def _fold(text: str) -> str:
    """Lower case, accents off, spaces collapsed: "Latest  NEWS" and
    "latest news" compare equal, whichever way padacioso handed it over."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def pick_best_candidate(candidates):
    """Pure helper (kept separate from the bus mechanics so it's easy to
    unit test): given a list of search.response payloads from provider
    skills, return the one with the highest confidence, or None if the
    list is empty.

    Candidates that tie for the highest confidence are picked from at
    random. "Tell me a story" gets one random story from every story
    provider, all at the same confidence; without this the provider that
    happened to answer first would win every time."""
    if not candidates:
        return None
    best = max(c.get("confidence", 0) for c in candidates)
    return random.choice([c for c in candidates if c.get("confidence", 0) == best])


def _session_id(message: Optional[Message]) -> str:
    """The id of the session `message` belongs to, the same way
    ovos-workshop works it out before calling stop_session()."""
    if message is None:
        return DEFAULT_SESSION_ID
    try:
        return SessionManager.get(message).session_id or DEFAULT_SESSION_ID
    except Exception:  # a malformed session carrier; nothing better to key on
        return DEFAULT_SESSION_ID


class _Reading:
    """One session's story in progress.

    `message` is the dispatch Message the story was asked for with. Every
    sentence is forwarded from it, so each one carries that session and its
    routing context back to the client that asked (a HiveMind hub routes on
    it, and speak(wait=True) waits for that session's audio_output_end).
    `lang` is the language the story was found in, which the fetch asks for.
    `stopped` is what stop/pause set; the reader checks it before every
    sentence."""

    def __init__(self, session_id: str, candidate: dict, message: Optional[Message],
                 lang: Optional[str] = None):
        self.session_id = session_id
        self.candidate = candidate
        self.message = message
        self.lang = lang
        self.stopped = threading.Event()
        self.thread: Optional[threading.Thread] = None


class CommonReadingPipeline(PipelinePlugin, OVOSAbstractApplication):

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        OVOSAbstractApplication.__init__(
            self, bus=bus, skill_id="ovos-common-reading-pipeline-plugin.andlo",
            resources_dir=dirname(__file__))
        PipelinePlugin.__init__(self, bus, config)
        self._init_state()
        self._migrate_flat_settings()
        self._register_intent_handlers()
        self._warm_up_intent_containers()

    def _init_state(self):
        """In-memory state, kept apart from __init__ so the tests can set up
        an instance without a bus or a settings file."""
        self._readings: Dict[str, _Reading] = {}  # session id -> story being read
        # guards _readings and the per-session settings; re-entrant because
        # the helpers that take it call each other
        self._state_lock = threading.RLock()
        self._intent_containers = {}  # locale folder name -> trained padacioso IntentContainer
        self._containers_lock = threading.Lock()
        self._news_words = {}  # locale folder name -> the phrases of its news.voc

    def _register_intent_handlers(self):
        """Register a handler for every match type match() can return.

        ovos-core dispatches a claimed utterance on "<skill_id>:<intent>"
        and ends the turn (ovos.utterance.handled) when the handler's
        mycroft.skill.handler.complete comes back. handler_info makes
        ovos-workshop's event wrapper emit that done-signal around the
        handler, and intent_name rides in its payload so the dispatcher can
        tell which in-flight dispatch it closes (a "pause" dispatched while a
        "read" handler is still asking "is it that one?" in the same session
        is two dispatches for one skill_id). Errors are logged, not spoken:
        this plugin ships no skill.error dialog, so the wrapper would say the
        dialog's file name out loud.

        ovos-workshop before 9 has no intent_name argument; its done-signal
        then names the skill only, which the dispatcher also accepts."""
        takes_intent_name = "intent_name" in inspect.signature(self.add_event).parameters
        for name, method in INTENT_HANDLERS.items():
            extra = {"intent_name": name} if takes_intent_name else {}
            self.add_event(f"{self.skill_id}:{name}", getattr(self, method),
                           handler_info=HANDLER_INFO, is_intent=True,
                           speak_errors=False, **extra)

    def _warm_up_intent_containers(self):
        """Train the padacioso containers for the configured languages in
        the background. Training English takes 1.5 to 3 s; done lazily, the
        first utterance after a restart would pay for it inside match()."""
        try:
            langs = [self.core_lang] + list(self.secondary_langs)
        except Exception as e:
            self.log.debug(f"not warming up intent containers: {e}")
            return

        def train():
            for lang in langs:
                try:
                    self._get_intent_container(lang)
                except Exception as e:
                    self.log.warning(f"could not train intents for {lang}: {e}")

        threading.Thread(target=train, name="common-reading-intents", daemon=True).start()

    # --- per-session state ---------------------------------------------------

    def _is_reading(self, session_id: str) -> bool:
        with self._state_lock:
            return session_id in self._readings

    def _session_entry(self, session_id: str, create: bool = False) -> Optional[dict]:
        """This session's slice of the settings:

            settings["sessions"][session_id] = {
                "last_content": <search response being read, or None>,
                "last_lang": <language it was found in, e.g. "fr-FR">,
                "progress": {"<skill_id>::<content_id>": <sentences heard>},
                "progress_splitter": {"<skill_id>::<content_id>": SPLITTER_VERSION},
                "touched": <unix time of the last write>,
            }

        With create=True a missing entry is made, the entry is stamped as
        just used, and the oldest sessions beyond MAX_REMEMBERED_SESSIONS are
        forgotten. Callers hold _state_lock."""
        sessions = self.settings.get("sessions")
        if not isinstance(sessions, dict):
            if not create:
                return None
            sessions = self.settings["sessions"] = {}
        entry = sessions.get(session_id)
        if not isinstance(entry, dict):
            if not create:
                return None
            entry = sessions[session_id] = {}
        entry.setdefault("last_content", None)
        entry.setdefault("progress", {})
        entry.setdefault("progress_splitter", {})
        if create:
            entry["touched"] = time.time()
            self._forget_old_sessions(sessions)
        return entry

    def _forget_old_sessions(self, sessions: dict):
        if len(sessions) <= MAX_REMEMBERED_SESSIONS:
            return
        protected = [sid for sid in sessions if sid == DEFAULT_SESSION_ID or sid in self._readings]
        others = sorted((sid for sid in sessions if sid not in protected),
                        key=lambda sid: sessions[sid].get("touched", 0), reverse=True)
        room = max(0, MAX_REMEMBERED_SESSIONS - len(protected))
        for sid in others[room:]:
            sessions.pop(sid, None)

    def _forget_session_if_empty(self, session_id: str):
        """Drop an entry that no longer holds anything to resume."""
        sessions = self.settings.get("sessions")
        entry = (sessions or {}).get(session_id)
        if isinstance(entry, dict) and not entry.get("last_content") and not entry.get("progress") \
                and session_id not in self._readings:
            sessions.pop(session_id, None)
            if not sessions:
                self.settings.pop("sessions", None)

    def _last_content(self, session_id: str) -> Optional[dict]:
        with self._state_lock:
            entry = self._session_entry(session_id)
            return entry.get("last_content") if entry else None

    def _migrate_flat_settings(self):
        """Carry settings written before sessions were tracked over to the
        default session.

        Older versions kept one "last_content", "progress" and
        "progress_splitter" at the top of the settings for everybody. A
        local device only ever had the default session, so that is where
        they belong now; a paused story there still continues where it was
        left. Anything the default session already holds wins."""
        with self._state_lock:
            flat = {key: self.settings.pop(key) for key in ("last_content", "progress", "progress_splitter")
                    if key in self.settings}
            if not flat:
                return
            entry = self._session_entry(DEFAULT_SESSION_ID, create=True)
            if flat.get("last_content") and not entry.get("last_content"):
                entry["last_content"] = flat["last_content"]
            for key in ("progress", "progress_splitter"):
                if isinstance(flat.get(key), dict):
                    for content_key, value in flat[key].items():
                        entry[key].setdefault(content_key, value)
            self._forget_session_if_empty(DEFAULT_SESSION_ID)
        self._store_settings()

    def _store_settings(self):
        """Write the settings file now. ovos-workshop only stores settings
        after a handler, and only when a shallow comparison sees a change,
        which misses the nested per-session dicts entirely."""
        store = getattr(self.settings, "store", None)
        if not callable(store):
            return
        try:
            with self._state_lock:
                store()
        except Exception as e:
            self.log.warning(f"could not store settings: {e}")

    # --- activation ------------------------------------------------------------

    def _activate(self, message: Optional[Message] = None, duration_minutes=5):
        """Mark this plugin as the currently active thing, so OVOS's
        global stop mechanism actually knows to call our stop() when
        the user says 'stop'.

        REAL BUG this fixes, confirmed via a live screenshot: saying
        'stop' mid-story did nothing - the story kept reading through
        several more paragraphs, eventually forcing a full ovos-core
        restart to interrupt it. The reading loop itself
        (_read_content, below) was never the problem - it correctly
        checks its stop flag between every sentence and breaks
        cleanly. The actual issue: OVOS's stop pipeline determines
        which skill(s) to call .stop() on by consulting the session's
        active_skills list, and this plugin was never being added to
        it, since this plugin (PipelinePlugin + OVOSAbstractApplication,
        not a full skill loaded via the skill manager) doesn't inherit
        from ovos_workshop.skills.converse.ConversationalSkill, which
        is normally what provides activate()/deactivate() - confirmed
        directly that OVOSAbstractApplication has no such method at
        all. So the global stop handler had no way to know this plugin
        was the thing currently speaking, and its stop() was simply
        never being invoked through the normal path.

        Since inheriting ConversationalSkill isn't an option here (no
        skill manager loads pipeline plugins the way it loads skills),
        this replicates exactly what ConversationalSkill.activate()
        itself does under the hood - emit 'intent.service.skills.
        activate' with our own skill_id - rather than the method
        itself, which isn't available on our base classes.

        The activation is forwarded from `message`, the request of the
        session it is for, so it lands on that session and nobody else's.
        Without one, the message in flight is used, as before."""
        msg = message or dig_for_message() or Message("")
        out = msg.forward("intent.service.skills.activate",
                          {"skill_id": self.skill_id, "timeout": duration_minutes})
        # Stamped unconditionally, not only when the key is absent: the message
        # in flight almost always already carries some OTHER skill's identity in
        # its context (whoever emitted the utterance that led here). Only
        # overwriting when the key was missing left payload and context
        # disagreeing on who this request is from - ovos-core's _activate_allowed
        # compares the two and silently refuses the activation whenever they
        # differ, which is whenever cross_activation is off. See #37. Stamped on
        # the forwarded copy, so the caller's message is left as it was.
        out.context["skill_id"] = self.skill_id
        self.bus.emit(out)

    def _deactivate(self, message: Optional[Message] = None):
        """Companion to _activate() above - same reasoning, replicates
        ConversationalSkill.deactivate()'s own bus message directly, for
        the session `message` belongs to."""
        msg = message or dig_for_message() or Message("")
        out = msg.forward("intent.service.skills.deactivate", {"skill_id": self.skill_id})
        # Same reasoning as _activate() above - stamp unconditionally so payload
        # and context agree regardless of whose message is in flight. See #37.
        out.context["skill_id"] = self.skill_id
        self.bus.emit(out)

    # --- utterance matching ------------------------------------------------------

    def _locale_dir_for(self, lang):
        """locale/<lang>, else another region of the same language
        (fr-ca -> fr-fr, de-at -> de-de), else English - every
        provider/skill in this family falls back to English."""
        base = os.path.join(dirname(__file__), "locale")
        lang = str(lang or "en-us").lower().replace("_", "-")
        candidate = os.path.join(base, lang)
        if os.path.isdir(candidate):
            return candidate
        primary = lang.split("-")[0]
        for name in sorted(os.listdir(base)):
            if name.split("-")[0] == primary and os.path.isdir(os.path.join(base, name)):
                return os.path.join(base, name)
        return os.path.join(base, "en-us")

    def _get_intent_container(self, lang):
        lang_dir = self._locale_dir_for(lang)
        key = os.path.basename(lang_dir)
        # Held while training, so match() calls arriving together for a
        # language that is not trained yet train it once, not once each.
        with self._containers_lock:
            if key in self._intent_containers:
                return self._intent_containers[key]
            container = IntentContainer()
            for intent_name, filename in INTENT_FILES.items():
                path = os.path.join(lang_dir, filename)
                if not os.path.isfile(path):
                    continue
                with open(path, encoding="utf-8") as f:
                    samples = [line.strip() for line in f if line.strip()]
                if samples:
                    container.add_intent(intent_name, samples)
            self._intent_containers[key] = container
            return container

    def _news_phrases(self, lang) -> List[str]:
        """The phrases in locale/<lang>/news.voc, folded with _fold()."""
        lang_dir = self._locale_dir_for(lang)
        key = os.path.basename(lang_dir)
        if key not in self._news_words:
            path = os.path.join(lang_dir, NEWS_VOC)
            phrases = []
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    phrases = [_fold(line) for line in f
                               if line.strip() and not line.lstrip().startswith("#")]
            self._news_words[key] = phrases
        return self._news_words[key]

    def _asks_for_news(self, entities: dict, lang) -> bool:
        """Whether the title or content type match() captured names the
        news ("news", "latest news about france", "dagens nyheder")."""
        phrases = self._news_phrases(lang)
        for slot in ("title", "content_type"):
            text = _fold(entities.get(slot) or "")
            if text and any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text) for p in phrases):
                return True
        return False

    def match(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Classify the utterance and decide whether to claim it. Nothing
        else: no search, no speech, no waiting.

        This used to run the whole request in here - the provider search
        (a 2 s window), the "is it that one?" question and the entire
        story, sentence by sentence. ovos-core 3.7 bounds every match()
        call to 10 s on a pool of 4 workers and skips a session whose
        previous call is still running, so after 10 s the utterance fell
        through to the later pipeline stages (an LLM answered it too) while
        the story kept reading on an abandoned worker, and "pause" or
        "continue" could not reach this plugin while its own story ran. The
        work now happens in the handler ovos-core dispatches to (see
        handle_read_content and friends), and match() answers in
        milliseconds once the language's intents are trained.

        "continue" and "pause" are declined rather than claimed when they
        make no sense for THIS session - nothing to resume, nothing being
        read - so a later pipeline stage gets its chance instead. Another
        user's story on the same hub does not count. A request for the news
        is declined the same way (see NEWS_VOC)."""
        container = self._get_intent_container(lang)
        session_id = _session_id(message)
        for utterance in utterances:
            result = container.calc_intent(utterance)
            name = result.get("name")
            if not name or result.get("conf", 0) < MATCH_CONFIDENCE_THRESHOLD:
                continue
            if name not in INTENT_HANDLERS:
                continue
            if name == "continue" and not (self._is_reading(session_id) or self._last_content(session_id)):
                # nothing in progress in this session - decline rather than
                # claim the utterance, so a later pipeline stage gets a
                # chance instead
                continue
            if name == "pause" and not self._is_reading(session_id):
                # nothing being read in this session right now - same
                # decline-rather-than-claim reasoning as "continue" above
                continue
            entities = result.get("entities") or {}
            if self._asks_for_news(entities, lang):
                continue

            # match_data=entities (not the default None) is not
            # optional: a real crash found via live testing.
            # IntentHandlerMatch.match_data defaults to None when not
            # given explicitly, and ovos-core's own handle_utterance
            # does `data.update(match.match_data)` on it unconditionally
            # - None isn't iterable, so that line raised TypeError and
            # the match was silently discarded, falling through to
            # common-query/fallback instead. Passing the already-
            # extracted entities dict here fixes the crash, and it is
            # also how the entities reach the handler: ovos-core merges
            # match_data into the dispatch message's data.
            return IntentHandlerMatch(match_type=f"{self.skill_id}:{name}",
                                       match_data=dict(entities),
                                       skill_id=self.skill_id, utterance=utterance)
        return None

    # --- intent handlers (ovos-core dispatches "<skill_id>:<intent>" here) ---------
    #
    # Each receives the dispatch Message: the utterance's data plus the
    # entities match() captured ("title", "collection", "content_type"),
    # "utterance" and "lang", with the requesting session in its context.

    def handle_read_content(self, message: Message):
        self._search_and_read(message, message.data.get("title"))

    def handle_read_by_collection(self, message: Message):
        self._search_and_read(message, message.data.get("title"),
                              collection_hint=message.data.get("collection"))

    def handle_read_by_type(self, message: Message):
        # "read me my horoscope" / "tell me today's horoscope" - no {title},
        # just a content_type ("horoscope", "story", etc) forwarded as a hint
        # on the search broadcast (see COMMON_READING_SEARCH's "content_type"
        # field) so provider skills can filter/respond appropriately.
        # Distinct phrasing ("my"/"today's") deliberately avoids overlapping
        # with read_content's "the story {title}" patterns - see
        # ReadContentByType.intent's own comment.
        self._search_and_read(message, None, content_type=message.data.get("content_type"))

    def handle_read_any_story(self, message: Message):
        # "tell me a story" / "raconte-moi une histoire" / "erzähl mir ein
        # Märchen" - no title at all. The providers answer a search with no
        # phrase with one story of their own choosing (see the README).
        self._search_and_read(message, None, content_type=ANY_STORY_CONTENT_TYPE)

    def handle_continue(self, message: Message):
        self._handle_continue(message)

    def handle_pause(self, message: Message):
        self._handle_pause(message)

    # --- stop / pause / continue ---------------------------------------------------

    def can_stop(self, message):
        """Required override, not optional: OVOSSkill.can_stop() (which
        this plugin inherits via OVOSAbstractApplication -> OVOSSkill)
        raises NotImplementedError by default for any class that
        implements its own stop() method, specifically to force this
        override rather than let it silently default to "can't stop".

        Real crash confirmed via a live screenshot: once _activate()
        (above) started correctly registering this plugin as active
        while reading, OVOS's stop pipeline began actually querying it
        via _handle_stop_ack() -> can_stop() as part of the normal
        stop-ack flow every active skill goes through - and since this
        override didn't exist yet, that raised NotImplementedError
        every single time, logged as a real (if apparently non-fatal
        to the overall stop still working) error on every stop/pause.

        True exactly when the session asking has a story to interrupt;
        a story read to somebody else does not make this session's
        "stop" ours."""
        return self._is_reading(_session_id(message))

    def stop_session(self, session: Session) -> bool:
        """Stop the story of the session that said "stop", and only that one.

        ovos-workshop calls this first for a targeted stop
        ("<skill_id>.stop") and for a global one ("mycroft.stop"), with the
        session the stop came from; stop() only runs when this returns False.

        The stop flag is set BEFORE the confirmation is spoken - a real,
        confirmed race condition, found via live testing: the reading loop
        (on its own thread, blocked inside speak(sentence, wait=True) for
        whatever sentence is currently playing) and this method (called from
        a separate bus-event thread) both want to enqueue TTS around the same
        moment. With the flag set AFTER 'stop_reading' was spoken, there's a
        window where the reading loop's thread wakes up (its own current
        sentence finishes), sees it may go on, and queues ONE MORE sentence
        before this method gets a chance to set the flag - which is exactly
        the "still reads one sentence after 'stop'" behavior reported.

        wait=True on the dialog itself is still not optional: without it,
        speak_dialog() only enqueues the TTS request and returns
        immediately. 'stop' is very likely to also trigger OVOS core's own
        audio-stop handling in the same moment, which flushes the TTS queue -
        a just-enqueued, not-yet-started confirmation gets silently wiped out
        by that flush. wait=True blocks until the dialog has actually
        finished being spoken, so nothing can race it away.

        The confirmation and the deactivation go to the stop message in
        flight, i.e. to the session that asked."""
        if self._stop_reading(session.session_id) is None:
            return False
        self._deactivate()
        self.speak_dialog('stop_reading', wait=True)
        self._store_settings()
        return True

    def stop(self):
        """The fallback stop: every story, for every session.

        ovos-workshop also calls this after stop_session() has found nothing
        to stop for the session that asked - which on a hub is every other
        user's "stop" while one story plays. A stop that names a session
        must never end another session's story, so this only goes ahead when
        no session is named at all: the plugin shutting down (ovos-core calls
        stop() on every pipeline plugin then), or a bare "mycroft.stop" with
        no session in its context. Returns True if anything was stopped."""
        message = dig_for_message()
        if message is not None and message.context.get("session") is not None:
            return False
        with self._state_lock:
            readings = list(self._readings.values())
            self._readings.clear()
        # all flags first, then the confirmations - see stop_session()
        for reading in readings:
            reading.stopped.set()
        for reading in readings:
            self._confirm_stop(reading.message)
        self._store_settings()
        return bool(readings)

    def _confirm_stop(self, message: Optional[Message]):
        """Deactivate and say 'stop_reading' to the session `message` came
        from (a local named `message` is how speak() finds its context)."""
        self._deactivate(message)
        self.speak_dialog('stop_reading', wait=True)

    def _stop_reading(self, session_id: str) -> Optional[_Reading]:
        """Flag this session's story to stop before its next sentence. The
        bookmark stays; returns the story, or None if none was being read."""
        with self._state_lock:
            reading = self._readings.pop(session_id, None)
        if reading is not None:
            reading.stopped.set()
        return reading

    def _handle_pause(self, message: Message):
        """A dedicated 'pause' intent, matched by this pipeline's own
        padacioso parser rather than relying on OVOS's global stop
        vocabulary (stop_session(), above) - 'pause' isn't guaranteed to
        be a recognized synonym for 'stop' at the core level, so
        without this, saying 'pause' while reading could silently do
        nothing. Functionally identical to a stop (the stop flag breaks the
        reading loop at the next sentence boundary, and progress is
        already bookmarked), just with a dialog that explicitly invites
        resuming rather than sounding final. Only the session that said
        it is paused.

        wait=True for the same reason as stop_session() - see the comment
        there."""
        if self._stop_reading(_session_id(message)) is not None:
            self._deactivate(message)
        self.speak_dialog('paused', wait=True)
        self._store_settings()

    def _handle_continue(self, message: Message):
        session_id = _session_id(message)
        if self._is_reading(session_id):
            return  # already reading - a second reader would read over the first
        last = self._last_content(session_id)
        if not last:
            # match() saw something to continue, but it finished since
            self.speak_dialog('nothing_to_continue')
            return
        with self._state_lock:
            entry = self._session_entry(session_id, create=True)
            bookmark = entry["progress"].get(self._progress_key(last), 0)
            # fetched in the language it was found in, whatever language
            # "continue" was said in: a one-language provider answers nothing else
            lang = entry.get("last_lang")
        reading = self._begin_reading(message, last, lang)  # before speaking: see _announce_and_read
        self.speak_dialog('continue', data={"title": last["title"]}, wait=True)
        self._read_in_background(message, reading, bookmark)

    # --- search and read -------------------------------------------------------------

    def _search_and_read(self, message: Message, phrase, collection_hint=None, content_type=None):
        """The part of a request that happens before the story starts, run
        by the intent handler: search, the confirmation when the best match
        is unsure, the announcement. The story itself is read on its own
        thread (_start_reading), so the handler returns and the turn ends."""
        # Asking for something new while a story plays: that story stops
        # (its bookmark stays) instead of being read over.
        self._stop_reading(_session_id(message))
        candidates = self._search_providers(message, phrase, collection_hint=collection_hint,
                                            content_type=content_type)
        if not candidates:
            self._handle_no_candidates(message, collection_hint)
            return

        best = pick_best_candidate(candidates)
        if best.get("confidence", 0) < CONFIDENCE_THRESHOLD:
            # wait=True is not optional here - same reasoning as
            # stop_session()/_handle_pause() above, and the exact same bug
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
            self.speak_dialog('that_would_be', data={"description": self._describe_short(best)}, wait=True)
            confirm = self.ask_yesno('is_it_that')
            if not confirm or confirm == 'no':
                self.speak_dialog('no_content')
                return

        self._announce_and_read(message, best, bookmark=0)

    def _handle_no_candidates(self, message: Message, collection_hint):
        """No search candidates - distinguish 'nothing is installed' from
        'something is installed but found nothing' via a lightweight
        ping/pong (see #2), rather than guessing at a fallback
        language or just saying the same generic thing either way."""
        if self._ping_providers(message):
            if collection_hint:
                self.speak_dialog('no_such_collection', data={"collection": collection_hint})
            else:
                self.speak_dialog('no_matching_content')
        else:
            self.speak_dialog('no_content_providers')

    @staticmethod
    def _progress_key(candidate):
        return f"{candidate['skill_id']}::{candidate['content_id']}"

    def _describe(self, candidate):
        """Build a spoken description from whatever metadata the winning
        provider supplied - gracefully skipping any fields it left out
        (not every provider necessarily has a 'collection', for instance).
        If the provider flagged 'machine_translated', that's disclosed
        here too, since this runs right before reading starts.

        The words around each field ("by", "from", ...) come from the
        locale's by_author/from_collection/sourced_from/machine_translated
        dialogs, so a French story is announced in French all the way
        through."""
        parts = [candidate["title"]]
        if candidate.get("author"):
            parts.append(self._render('by_author', author=candidate["author"]))
        if candidate.get("collection"):
            parts.append(self._render('from_collection', collection=candidate["collection"]))
        if candidate.get("source"):
            parts.append(self._render('sourced_from', source=candidate["source"]))
        if candidate.get("machine_translated"):
            parts.append(self._render('machine_translated'))
        return ", ".join(parts)

    def _describe_short(self, candidate):
        """A shorter version of _describe() - title and author only,
        no collection/source/translation notes - for the low-confidence
        confirmation dialog ('is this the one you meant?'), which needs
        just enough to help the person recognize/distinguish the match,
        not the full announcement _describe() builds for right before
        actually reading starts. Real request that led to this: 'Yes,
        it could be "how to boil an egg in 100 ways" by Andreas' reads
        naturally; the full _describe() output (also tacking on
        collection/source/translation-flag) would be a mouthful for a
        quick yes/no check."""
        parts = [candidate["title"]]
        if candidate.get("author"):
            parts.append(self._render('by_author', author=candidate["author"]))
        return ", ".join(parts)

    def _render(self, dialog, **data):
        """One line of a dialog file, in the language of the request in
        flight (the renderer follows the session, like speak_dialog)."""
        return self.dialog_renderer.render(dialog, data)

    def _request(self, message: Optional[Message], msg_type: str, data: dict,
                 lang: Optional[str] = None) -> Message:
        """A request to the providers, forwarded from the user's request so
        it keeps its context: which session asked and where the answer goes.

        "lang" is always in the payload, and it is the language the request
        was matched in (ovos-core puts it in the dispatch's data), not the
        session's: for the default session a provider's SessionManager.get()
        gives back the device's own language whatever the message carried,
        and a bare Message would be stamped with the default session too."""
        data = dict(data)
        data["requester"] = self.skill_id
        data["lang"] = lang or self._request_lang(message)
        request = message.forward(msg_type, data) if message is not None else Message(msg_type, data)
        request.context["skill_id"] = self.skill_id
        return request

    def _request_lang(self, message: Optional[Message]) -> Optional[str]:
        try:
            lang = get_message_lang(message) if message is not None else None
        except Exception:
            lang = None
        return lang or self.lang

    def _collect_replies(self, request: Message, reply_type: str, timeout: float,
                         first_only: bool = False) -> List[Message]:
        """Emit `request` and collect the `reply_type` answers to it.

        Only answers for the session that asked are taken. Two people on a
        hub can search or fetch at the same moment, and every provider
        answers on the same topics; a provider replies with message.reply(),
        which carries the requester's session back. An answer that names no
        session at all cannot be told apart and is taken.

        first_only returns as soon as one answer is in (a fetch has exactly
        one addressee); otherwise answers are collected for the whole window
        (a search goes to every provider)."""
        session_id = _session_id(request)
        replies = []
        answered = threading.Event()

        def collect(reply):
            carrier = (getattr(reply, "context", None) or {}).get("session")
            if carrier is not None and _session_id(reply) != session_id:
                return
            replies.append(reply)
            answered.set()

        self.bus.on(reply_type, collect)
        try:
            self.bus.emit(request)
            if first_only:
                answered.wait(timeout)
            else:
                time.sleep(timeout)
        finally:
            self.bus.remove(reply_type, collect)
        return replies

    def _search_providers(self, message: Optional[Message], phrase, collection_hint=None, content_type=None,
                          timeout=SEARCH_TIMEOUT):
        """Broadcast a search to every provider skill and collect all
        responses for a short window (unlike _fetch_content, several
        providers are expected to answer here, not just one)."""
        request = self._request(message, COMMON_READING_SEARCH, {
            "phrase": phrase,
            "collection_hint": collection_hint,
            "content_type": content_type,
        })
        return [reply.data for reply in
                self._collect_replies(request, COMMON_READING_SEARCH_RESPONSE, timeout)]

    def _ping_providers(self, message: Optional[Message], timeout=PING_TIMEOUT):
        """Broadcast a lightweight 'is anyone there?' and collect pongs.
        Only called from _handle_no_candidates, on the rare 0-candidates
        path - never on every search, since a pong round trip would add
        latency to the common case for no benefit."""
        request = self._request(message, COMMON_READING_PING, {})
        return [reply.data for reply in self._collect_replies(request, COMMON_READING_PONG, timeout)]

    def _fetch_content(self, message: Optional[Message], candidate, timeout=FETCH_TIMEOUT, lang=None):
        """Ask the provider that won the search for the text. content_id is
        the provider's own key (it may differ from the spoken title)."""
        skill_id = candidate["skill_id"]
        request = self._request(message, f"{COMMON_READING_FETCH_CONTENT}.{skill_id}",
                                {"content_id": candidate["content_id"]}, lang=lang)
        replies = self._collect_replies(request, COMMON_READING_FETCH_CONTENT_RESPONSE, timeout,
                                        first_only=True)
        if not replies:
            raise ContentFetchError(f"provider {skill_id} did not respond in time")
        paragraphs = replies[0].data.get("paragraphs")
        if not paragraphs:
            raise ContentFetchError(f"provider {skill_id} returned no text for {candidate['content_id']}")
        return paragraphs

    def _announce_and_read(self, message: Message, candidate, bookmark):
        # The story counts as being read from here, before the announcement:
        # a "stop" said over "Here it is: ..." then stops it (can_stop says
        # yes, and the story never starts) instead of finding nothing to stop.
        reading = self._begin_reading(message, candidate)
        self.speak_dialog('i_know_that', data={"description": self._describe(candidate)}, wait=True)
        self._read_in_background(message, reading, bookmark)

    def _begin_reading(self, message: Optional[Message], candidate, lang: Optional[str] = None) -> _Reading:
        """Make `candidate` this session's story: registered as being read
        (a story the session was already reading is flagged to stop) and
        remembered, with its language, as the one "continue" resumes."""
        session_id = _session_id(message)
        lang = lang or self._request_lang(message)
        reading = _Reading(session_id, candidate, message, lang)
        with self._state_lock:
            previous = self._readings.get(session_id)
            self._readings[session_id] = reading
            entry = self._session_entry(session_id, create=True)
            entry["last_content"] = candidate
            entry["last_lang"] = lang
        if previous is not None:
            previous.stopped.set()
        self._store_settings()
        return reading

    def _start_reading(self, message: Message, candidate, bookmark, lang: Optional[str] = None) -> _Reading:
        """_begin_reading() and _read_in_background() in one go."""
        return self._read_in_background(message, self._begin_reading(message, candidate, lang), bookmark)

    def _read_in_background(self, message: Message, reading: _Reading, bookmark) -> _Reading:
        """Read `reading` on a daemon thread and return at once, so the intent
        handler returns and ovos-core ends the turn while the story plays.
        Nothing is started if it was stopped in the meantime."""
        if reading.stopped.is_set():
            return reading
        # See _activate()'s own docstring for the real bug this fixes -
        # without this, OVOS's global stop pipeline has no way to know
        # this plugin is the thing currently speaking, so saying "stop"
        # mid-story would do nothing at all. Done here, while the turn is
        # still open, so it lands on the session the turn belongs to.
        self._activate(message)
        reading.thread = threading.Thread(target=self._read_content, args=(message, reading, bookmark),
                                          name=f"common-reading-{reading.session_id}", daemon=True)
        reading.thread.start()
        return reading

    def _finish_reading(self, message: Optional[Message], reading: _Reading):
        """The story is over (read to the end, or could not be fetched):
        forget it, unless something else has become this session's story
        in the meantime."""
        with self._state_lock:
            current = self._readings.get(reading.session_id) is reading
            if current:
                self._readings.pop(reading.session_id)
        if current:
            self._deactivate(message)
        return current

    def _read_content(self, message: Optional[Message], reading: _Reading, bookmark):
        """Read the story aloud, one sentence at a time, on the reader thread.

        `message` is a parameter on purpose: speak() finds the context to
        send each sentence with by walking the stack for a Message argument
        (dig_for_message). With the dispatch message here, every sentence
        carries the session and routing of the request that started the
        story - on a HiveMind hub that is what gets it to the right client -
        and speak(wait=True) waits for that session's audio_output_end, so
        a client that reports its playback paces the story."""
        try:
            self._read_sentences(message, reading, bookmark)
        except Exception as e:
            self.log.exception(f"reading {reading.candidate.get('title')!r} failed: {e}")
            self._finish_reading(message, reading)
        finally:
            self._store_settings()

    def _read_sentences(self, message: Optional[Message], reading: _Reading, bookmark):
        candidate = reading.candidate
        try:
            paragraphs = self._fetch_content(message, candidate, lang=reading.lang)
        except ContentFetchError as e:
            self.log.error(f"Could not fetch content: {e}")
            if self._finish_reading(message, reading):
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
        sentences = [s for para in paragraphs for s in split_sentences(para)]

        key = self._progress_key(candidate)
        # A bookmark saved before SPLITTER_VERSION counted chunks of the old
        # split; carry it over by the words already heard.
        with self._state_lock:
            versions = self._session_entry(reading.session_id, create=True)["progress_splitter"]
            if bookmark and versions.get(key) != SPLITTER_VERSION:
                bookmark = migrate_bookmark(paragraphs, bookmark)
        for i, sentence in enumerate(sentences[bookmark:], start=bookmark):
            if reading.stopped.is_set():
                break
            # speak(), not speak_dialog(): the dialog renderer treats its
            # argument as a template name and, finding none, speaks the name
            # with every '.' replaced by a space - the full stop that ends
            # the sentence, "Mr. Fox", "3.5" - and a sentence that happens to
            # equal a dialog name would be swapped for that dialog.
            self.speak(sentence, wait=True)
            # only marked done AFTER actually speaking it - if pause
            # sets the stop flag while this sentence is mid-speech,
            # speak(wait=True) still finishes it before returning, so
            # the bookmark correctly reflects that this sentence WAS
            # heard, while the next loop iteration's stop check (above)
            # correctly stops before the one after it.
            with self._state_lock:
                entry = self._session_entry(reading.session_id, create=True)
                entry["progress"][key] = i + 1
                entry["progress_splitter"][key] = SPLITTER_VERSION

        if reading.stopped.is_set():
            return  # stopped or paused: the bookmark stays for "continue"

        with self._state_lock:
            entry = self._session_entry(reading.session_id, create=True)
            entry["progress"].pop(key, None)
            entry["progress_splitter"].pop(key, None)
            if entry.get("last_content") == candidate:
                entry["last_content"] = None
                entry.pop("last_lang", None)
            current = self._readings.get(reading.session_id) is reading
            if current:
                self._readings.pop(reading.session_id)
            self._forget_session_if_empty(reading.session_id)
        if not current:
            return  # a newer story took over this session; it has its own ending
        self._deactivate(message)
        if candidate.get("source"):
            self.speak_dialog('finished_reading', data={"source": candidate["source"]})
        else:
            self.speak_dialog('finished_reading_unsourced')
