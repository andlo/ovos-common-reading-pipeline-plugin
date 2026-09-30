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


import difflib
import inspect
import json
import math
import os
import random
import re
import threading
import time
import unicodedata
from os.path import dirname
from typing import Dict, List, Optional, Union
from xml.sax.saxutils import escape as xml_escape

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.session import Session, SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils.fakebus import FakeBus
from ovos_workshop.app import OVOSAbstractApplication
from ovos_workshop.skills import ovos as _workshop_skill
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
# Vocabulary: what a provider can read, in words people use. A provider
# emits COMMON_READING_VOCABULARY once per language it serves when it loads,
# and again whenever the pipeline asks with COMMON_READING_VOCABULARY_GET
# ({"langs": [...]}, sent when the pipeline loads). Payload:
#   {"skill_id": ..., "lang": "en-us",
#    "content_types": {"horoscope": ["horoscope", "horoscopes"]},  # canonical -> words
#    "collections": ["grimm", "brothers grimm"],                      # names of the collection
#    "titles": ["The Little Mermaid", ...]}                           # optional
# {"skill_id": ..., "remove": true} forgets a provider. See README.md.
COMMON_READING_VOCABULARY = "ovos.common_reading.vocabulary"
COMMON_READING_VOCABULARY_GET = "ovos.common_reading.vocabulary.get"

SEARCH_TIMEOUT = 2.0  # seconds to wait for provider skills to answer a search
FETCH_TIMEOUT = 10.0  # seconds to wait for the winning provider to deliver text
PING_TIMEOUT = 0.3  # seconds - short, since a pong is cheap (no index lookup)
CONFIDENCE_THRESHOLD = 0.8  # provider search-response confidence needed to skip "is it that one?"
MATCH_CONFIDENCE_THRESHOLD = 0.5  # padacioso utterance-match confidence needed to engage at all
# match_low: how close a bare title ("tell me the little mermaid") must be to
# a title a provider announced. Short titles must match exactly.
TITLE_MATCH_THRESHOLD = 0.88
TITLE_FUZZY_MIN_LENGTH = 8
# locale/<lang>/reading.json - the words that take a request apart
# (scripts/build_reading_words.py)
READING_WORDS = "reading.json"

# maps our internal intent names -> the *.intent file each is trained from
# Only "continue" and "pause" are fixed sentences; a reading request is
# taken apart by _analyze() against the providers' vocabulary instead.
INTENT_FILES = {
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

# Longest chunk handed to TTS in one speak() call. The wait after it gives up
# after 15s at most (MAX_SPOKEN_WAIT), and at 12-15 spoken characters a
# second a 160-character chunk stays well inside it. A sentence longer than
# this is cut at a clause boundary instead (#35).
MAX_SPOKEN_CHARS = 160
# ...but not into shards: a cut never leaves a piece shorter than this.
MIN_CLAUSE_CHARS = 40
# How long the reader waits for a line to be heard (#41). speak(wait=...)
# waits for the session's recognizer_loop:audio_output_end, or for its
# timeout. A client that reports its playback ends the wait when the line
# ends; one that doesn't (a HiveMind client that plays speech itself and says
# nothing, a web preview) used to cost the full 15 s of wait=True after every
# sentence, most of it silence. The timeout is sized to the line instead: its
# length at a slow speaking rate plus a margin for synthesis, never more than
# those 15 s. Piper was measured at 19-20 characters a second from speak to
# audio_output_end, synthesis included, so 14 leaves room for slower voices.
# Both can be set in the plugin's config or settings (see _option):
# "chars_per_second" and "wait_margin".
SPOKEN_CHARS_PER_SECOND = 14
SPOKEN_WAIT_MARGIN = 3  # seconds
MAX_SPOKEN_WAIT = 15  # seconds, what speak(wait=True) waits
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


def spoken_wait(text: str, chars_per_second: float = SPOKEN_CHARS_PER_SECOND,
                margin: float = SPOKEN_WAIT_MARGIN) -> int:
    """Seconds to wait for `text` to be heard when nothing reports that it
    was: len(text) / chars_per_second + margin, rounded up, at most
    MAX_SPOKEN_WAIT.

    Whole seconds because ovos-workshop 0.1.0 to 0.1.2 read the wait as
    `wait if isinstance(wait, int) else 15`, so a fraction there would still
    wait 15 s. From 0.1.3 on (checked through 9.8.6a2) it is
    `15 if isinstance(wait, bool) else wait`, which takes either."""
    seconds = len(text) / chars_per_second + margin
    return max(1, min(MAX_SPOKEN_WAIT, math.ceil(seconds)))


# --- narration (#40) ------------------------------------------------------
#
# Off unless the plugin's config or settings say {"narration": "ssml"}. Each
# sentence then carries an SSML version of itself in data["utterance_ssml"],
# beside the plain data["utterance"], which stays exactly as it was. Never
# inline: a client that doesn't render SSML shows or says a tag it finds in
# "utterance", while one that doesn't know "utterance_ssml" just ignores it.
# Every sentence is still its own speak and its own <speak> document, so the
# bookmark and the wait work as before.
#
# The rules are few, because a pause in the wrong place is worse than none,
# and they only act on what the text itself marks:
#
# - a pause before the first sentence read (after "Here it is: ..." or
#   "Continuing ...") and a shorter one before the first sentence of every
#   other paragraph;
# - a dash right after the end of a sentence, which is how Cosquin's
#   Gutenberg text marks the next speaker ("maltraité?—Si tu te plains"),
#   becomes a pause longer than the voice's own between two sentences;
# - any other dash between words (an aside, an interruption: "I think—I know
#   I think—it might be little Kay") becomes a brief pause. Phoonnx voices
#   read straight through a dash, and through a comma too: their phonemizer
#   drops both;
# - "…" becomes "...": Phoonnx ends a sentence at "..." (80-130 ms of
#   silence measured) and reads straight through the single character. An
#   ellipsis with more of the sentence after it also gets a short pause.
#
# Quoted dialogue, "!" and "?" are left to the voice.
NARRATION_SSML = "ssml"
STORY_START_BREAK_MS = 750
PARAGRAPH_BREAK_MS = 500
SPEAKER_CHANGE_BREAK_MS = 300
ELLIPSIS_BREAK_MS = 250
DASH_BREAK_MS = 200
# Every topic speak() has emitted on: "speak" up to ovos-workshop 8, then
# SpecMessage.SPEAK ("ovos.utterance.speak"; the bus adds the legacy "speak"
# twin unless OVOS_BUS_EMIT_LEGACY is off). Taken from the name speak() itself
# looks up, so the narrated sentences go out on the same topic as plain ones.
SPEAK_TOPIC = getattr(getattr(_workshop_skill, "SpecMessage", None), "SPEAK", "speak")

_OPENERS = "\"'“‘«„»("
# a dash after a sentence's end (and any closing quote): the next speaker
_SPEAKER_DASH = re.compile(r"(?<=[.!?…])([" + re.escape(_CLOSERS) + r"]*)\s*(?:—|--|–)\s*(?=\S)")
# an em dash or a double hyphen anywhere, an en dash only with a space on
# either side (unspaced, it is a range: 1805–1812), and the closing quotes
# right after it
_ASIDE_DASH = re.compile(r"(?:\s*(?:—|--)\s*|\s+–\s+)([" + re.escape(_CLOSERS) + r"]*)\s*")
_ELLIPSIS = re.compile(r"\.{3,}|…")
# ...with more of the sentence after it, not a closing quote or the end
_ELLIPSIS_MID = re.compile(r"\.\.\.\s+(?=[\w" + re.escape(_OPENERS) + r"])")
# what XML 1.0 cannot carry at all, even escaped
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _break(ms: int) -> str:
    return f'<break time="{ms}ms"/>'


def _aside(match) -> str:
    """A dash between words becomes a brief pause, after any closing quote
    that follows it. One at either end of the sentence, or between two
    numbers, is left as it is."""
    text, start, end = match.string, match.start(), match.end()
    if start == 0 or end == len(text) or (text[start - 1].isdigit() and text[end].isdigit()):
        return match.group(0)
    return f"{match.group(1)} {_break(DASH_BREAK_MS)} "


def narrate(sentence: str, pause_before_ms: int = 0) -> str:
    """One sentence as an SSML document (see the rules above). The words are
    the sentence's own, XML-escaped; only dashes and ellipses change."""
    text = xml_escape(_NOT_XML.sub("", sentence))
    text = _SPEAKER_DASH.sub(lambda m: f"{m.group(1)} {_break(SPEAKER_CHANGE_BREAK_MS)} ", text)
    text = _ASIDE_DASH.sub(_aside, text)
    text = _ELLIPSIS.sub("...", text)
    text = _ELLIPSIS_MID.sub(f"... {_break(ELLIPSIS_BREAK_MS)} ", text)
    lead = _break(pause_before_ms) if pause_before_ms > 0 else ""
    return f"<speak>{lead}{text}</speak>"


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


def _norm(text: str) -> str:
    """_fold(), with hyphens and apostrophes as spaces and other
    punctuation dropped: "Raconte-moi l'histoire!" -> "raconte moi l
    histoire". Utterances and every word list go through this."""
    text = _fold(text)
    text = re.sub(r"[-'’`]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _lang_key(lang) -> str:
    """"en-US"/"en_us" -> "en-us"; the key vocabulary is stored under."""
    return str(lang or "en-us").lower().replace("_", "-")


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
    it, and speak(wait=...) waits for that session's audio_output_end).
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


class CommonReadingPipeline(ConfidenceMatcherPipeline, OVOSAbstractApplication):

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        OVOSAbstractApplication.__init__(
            self, bus=bus, skill_id="ovos-common-reading-pipeline-plugin.andlo",
            resources_dir=dirname(__file__))
        ConfidenceMatcherPipeline.__init__(self, bus, config)
        self._init_state()
        self._migrate_flat_settings()
        self._register_intent_handlers()
        self.add_event(COMMON_READING_VOCABULARY, self._handle_vocabulary)
        self._warm_up_intent_containers()
        self._request_vocabulary()

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
        # provider vocabulary: skill_id -> lang key -> {"content_types",
        # "collections", "titles"}, as announced (see COMMON_READING_VOCABULARY)
        self._vocab: Dict[str, Dict[str, dict]] = {}
        self._vocab_lock = threading.Lock()
        self._indexes = {}  # lang key -> _index() result, dropped when vocabulary changes
        self._reading_words_cache = {}  # locale folder name -> reading.json, normalised
        self._rejected_options = set()  # (key, value) already warned about

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

    # --- vocabulary (what providers can read) ---------------------------------

    def _request_vocabulary(self):
        """Ask the providers that are already loaded for their vocabulary.
        Providers that load later announce it themselves."""
        try:
            langs = [self.core_lang] + list(self.secondary_langs)
        except Exception:
            langs = []
        try:
            self.bus.emit(Message(COMMON_READING_VOCABULARY_GET, {"langs": langs}))
        except Exception as e:
            self.log.debug(f"could not request vocabulary: {e}")

    def _handle_vocabulary(self, message: Message):
        """A provider says what it can read in one language (or that it
        is gone). Stored as announced; _index() normalises it."""
        data = message.data or {}
        skill_id = data.get("skill_id")
        if not skill_id:
            return
        with self._vocab_lock:
            if data.get("remove"):
                self._vocab.pop(skill_id, None)
            else:
                entry = {
                    "content_types": {str(k): [str(w) for w in (v or [])]
                                      for k, v in (data.get("content_types") or {}).items()},
                    "collections": [str(c) for c in (data.get("collections") or [])],
                    "titles": [str(t) for t in (data.get("titles") or [])],
                }
                self._vocab.setdefault(skill_id, {})[_lang_key(data.get("lang"))] = entry
            self._indexes.clear()

    def _reading_words(self, lang) -> dict:
        """locale/<lang>/reading.json, every word normalised and every
        list sorted longest first (so "tell me" wins over "tell")."""
        lang_dir = self._locale_dir_for(lang)
        key = os.path.basename(lang_dir)
        if key not in self._reading_words_cache:
            path = os.path.join(lang_dir, READING_WORDS)
            raw = {}
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)

            def words(name):
                return sorted({_norm(w) for w in raw.get(name, []) if _norm(w)}, key=len, reverse=True)

            self._reading_words_cache[key] = {
                "verbs": words("verbs"),
                "suffixes": words("suffixes"),
                "edges": sorted({*words("about"), *words("from"), *words("filler"), *words("latest")},
                                key=len, reverse=True),
                "content_types": {canon: [_norm(w) for w in forms if _norm(w)]
                                  for canon, forms in (raw.get("content_types") or {}).items()},
            }
        return self._reading_words_cache[key]

    def _strip_edges(self, text: str, lang) -> str:
        """Drop articles, connectors and the like from both ends of a
        title: "the little mermaid" -> "little mermaid", "about the moon
        from" -> "moon"."""
        edges = self._reading_words(lang)["edges"]
        changed = True
        while text and changed:
            changed = False
            for w in edges:
                if text == w:
                    return ""
                if text.startswith(w + " "):
                    text, changed = text[len(w) + 1:], True
                    break
                if text.endswith(" " + w):
                    text, changed = text[:-len(w) - 1], True
                    break
        return text.strip()

    def _index(self, lang) -> dict:
        """What can be read in this language, from the pipeline's own story
        words and every provider's announcement for the same language."""
        key = _lang_key(lang)
        with self._vocab_lock:
            if key in self._indexes:
                return self._indexes[key]
            primary = key.split("-")[0]
            content = {}   # normalised word -> canonical content type
            for canon, forms in self._reading_words(lang)["content_types"].items():
                for form in forms:
                    content.setdefault(form, canon)
            collections = {}  # normalised name -> name as announced
            titles = {}  # title without articles -> title as announced
            for per_lang in self._vocab.values():
                for vlang, entry in per_lang.items():
                    if vlang.split("-")[0] != primary:
                        continue
                    for canon, forms in entry["content_types"].items():
                        for form in [canon] + forms:
                            if _norm(form):
                                content.setdefault(_norm(form), canon)
                    for name in entry["collections"]:
                        if _norm(name):
                            collections.setdefault(_norm(name), name)
                    for title in entry["titles"]:
                        stripped = self._strip_edges(_norm(title), lang)
                        if stripped:
                            titles.setdefault(stripped, title)
            index = {"content": sorted(content.items(), key=lambda kv: len(kv[0]), reverse=True),
                     "collections": sorted(collections.items(), key=lambda kv: len(kv[0]), reverse=True),
                     "titles": titles}
            self._indexes[key] = index
            return index

    @staticmethod
    def _find_first(text: str, items, suffix=""):
        """The leftmost of `items` ((word, value) pairs) in `text` as a whole
        word, longest first on a tie: (start, end, word, value) or None.
        Leftmost, so a kind of text named before the title wins over one
        that is part of it ("a story about a fairy tale princess")."""
        best = None
        for word, value in items:
            m = re.search(rf"(?<!\w){re.escape(word)}{suffix}(?!\w)", text)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.end(), word, value)
        return best

    def _analyze(self, utterance: str, lang) -> Optional[dict]:
        """Take a reading request apart: {"content_type", "collection",
        "title"} (each None when not said), or None when the sentence does
        not open with a reading verb. Nothing here decides whether to claim
        it - see match_high() and match_low()."""
        words = self._reading_words(lang)
        text = _norm(utterance)
        verb = next((v for v in words["verbs"] if text == v or text.startswith(v + " ")), None)
        if verb is None:
            return None
        rest = text[len(verb):].strip()
        changed = True
        while rest and changed:
            changed = False
            for suffix in words["suffixes"]:
                if rest == suffix or rest.endswith(" " + suffix):
                    rest, changed = rest[:len(rest) - len(suffix)].strip(), True
                    break
        index = self._index(lang)
        content_type = None
        hit = self._find_first(rest, index["content"])
        if hit:
            content_type = hit[3]
            rest = f"{rest[:hit[0]]} {rest[hit[1]:]}".strip()
        collection = None
        # "grimm", "grimm's", Danish "grimms"
        hit = self._find_first(rest, index["collections"], suffix=r"(?: ?s)?")
        if hit:
            collection = hit[3]
            rest = f"{rest[:hit[0]]} {rest[hit[1]:]}".strip()
        title = self._strip_edges(" ".join(rest.split()), lang) or None
        return {"content_type": content_type, "collection": collection, "title": title}

    def _known_title(self, title: Optional[str], lang) -> Optional[str]:
        """The announced title `title` names, or None. Exact after dropping
        articles; close (TITLE_MATCH_THRESHOLD) only for longer titles, so
        "the time" never passes for a tale called "The Tinderbox"."""
        if not title:
            return None
        titles = self._index(lang)["titles"]
        if title in titles:
            return titles[title]
        if len(title) < TITLE_FUZZY_MIN_LENGTH:
            return None
        close = difflib.get_close_matches(title, titles.keys(), n=1, cutoff=TITLE_MATCH_THRESHOLD)
        return titles[close[0]] if close else None

    def _claim(self, name: str, entities: dict, utterance: str) -> IntentHandlerMatch:
        # match_data=entities (not the default None) is not optional:
        # ovos-core's handle_utterance does data.update(match.match_data)
        # unconditionally (a real crash found via live testing), and it is
        # how the entities reach the handler.
        return IntentHandlerMatch(match_type=f"{self.skill_id}:{name}",
                                  match_data={k: v for k, v in entities.items() if v},
                                  skill_id=self.skill_id, utterance=utterance)

    # --- matching (ovos-core calls these; see README "Pipeline stages") -------

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """A request that names something a provider can read: a kind of
        text ("a story", "my horoscope", "an article about ...") or a
        collection ("a story from grimm"). Also "continue"/"pause".

        Only classifies - no search, no speech, no waiting: ovos-core
        bounds every match() call (10 s on a small pool) and the work
        happens in the handler it dispatches to (handle_read_content and
        friends).

        "tell me the weather" / "tell me the time" name neither, so they
        are left to the skills they belong to (issue #50). A bare title is
        match_low()'s, after the skills' own intents have had their turn."""
        session_id = _session_id(message)
        container = self._get_intent_container(lang)
        for utterance in utterances:
            result = container.calc_intent(utterance)
            name = result.get("name")
            if name in ("continue", "pause") and result.get("conf", 0) >= MATCH_CONFIDENCE_THRESHOLD:
                if name == "continue" and not (self._is_reading(session_id) or self._last_content(session_id)):
                    # nothing in progress in this session - decline, so a
                    # later pipeline stage gets its chance
                    continue
                if name == "pause" and not self._is_reading(session_id):
                    continue
                return self._claim(name, {}, utterance)

            parts = self._analyze(utterance, lang)
            if not parts or not (parts["content_type"] or parts["collection"]):
                continue
            if self._asks_for_news(parts, lang):
                continue
            # a title a provider announced goes out the way it was announced
            parts["title"] = self._known_title(parts["title"], lang) or parts["title"]
            if parts["collection"]:
                name = "read_by_collection"
            elif parts["title"]:
                name = "read_content"
            elif parts["content_type"] == ANY_STORY_CONTENT_TYPE:
                name = "read_any_story"
            else:
                name = "read_by_type"
            return self._claim(name, parts, utterance)
        return None

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        return None

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """A bare title ("tell me the little mermaid", "læs den grimme
        ælling"), claimed only when a provider announced that title. Meant
        to sit after padatious/adapt in the pipeline, so a skill whose own
        intent matches the sentence gets it first."""
        for utterance in utterances:
            parts = self._analyze(utterance, lang)
            if not parts or parts["content_type"] or parts["collection"]:
                continue
            title = self._known_title(parts["title"], lang)
            if title and not self._asks_for_news({"title": title}, lang):
                return self._claim("read_content", {"title": title}, utterance)
        return None

    # --- intent handlers (ovos-core dispatches "<skill_id>:<intent>" here) ---------
    #
    # Each receives the dispatch Message: the utterance's data plus the
    # entities match() captured ("title", "collection", "content_type"),
    # "utterance" and "lang", with the requesting session in its context.

    def handle_read_content(self, message: Message):
        self._search_and_read(message, message.data.get("title"),
                              content_type=message.data.get("content_type"))

    def handle_read_by_collection(self, message: Message):
        self._search_and_read(message, message.data.get("title"),
                              collection_hint=message.data.get("collection"),
                              content_type=message.data.get("content_type"))

    def handle_read_by_type(self, message: Message):
        # "read me my horoscope" / "tell me today's horoscope" - no title,
        # just the kind of text, forwarded as the canonical name a provider
        # announced ("horoscope"), so provider skills can filter on it.
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
        (on its own thread, blocked inside speak(sentence, wait=...) for
        whatever sentence is currently playing) and this method (called from
        a separate bus-event thread) both want to enqueue TTS around the same
        moment. With the flag set AFTER 'stop_reading' was spoken, there's a
        window where the reading loop's thread wakes up (its own current
        sentence finishes), sees it may go on, and queues ONE MORE sentence
        before this method gets a chance to set the flag - which is exactly
        the "still reads one sentence after 'stop'" behavior reported.

        Waiting on the dialog itself is still not optional: without it,
        speak_dialog() only enqueues the TTS request and returns
        immediately. 'stop' is very likely to also trigger OVOS core's own
        audio-stop handling in the same moment, which flushes the TTS queue -
        a just-enqueued, not-yet-started confirmation gets silently wiped out
        by that flush. The wait blocks until the dialog has actually
        finished being spoken (or for as long as it takes to say, see
        _speak_dialog_and_wait), so nothing can race it away.

        The confirmation and the deactivation go to the stop message in
        flight, i.e. to the session that asked."""
        if self._stop_reading(session.session_id) is None:
            return False
        self._deactivate()
        self._speak_dialog_and_wait('stop_reading')
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
        self._speak_dialog_and_wait('stop_reading')

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

        It waits for the dialog for the same reason as stop_session() - see
        the comment there."""
        if self._stop_reading(_session_id(message)) is not None:
            self._deactivate(message)
        self._speak_dialog_and_wait('paused')
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
        self._speak_dialog_and_wait('continue', data={"title": last["title"]})
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
            # Waiting is not optional here - same reasoning as
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
            self._speak_dialog_and_wait('that_would_be', data={"description": self._describe_short(best)})
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

        The source is not in it: it is said once, when the story is over
        ('finished_reading'). It used to be said here too, so every story
        named it twice; unlike the translation note, a credit doesn't have
        to come before the story.

        The words around each field ("by", "from", ...) come from the
        locale's by_author/from_collection/machine_translated dialogs, so
        a French story is announced in French all the way through."""
        parts = [candidate["title"]]
        if candidate.get("author"):
            parts.append(self._render('by_author', author=candidate["author"]))
        if candidate.get("collection"):
            parts.append(self._render('from_collection', collection=candidate["collection"]))
        if candidate.get("machine_translated"):
            parts.append(self._render('machine_translated'))
        return ", ".join(parts)

    def _describe_short(self, candidate):
        """A shorter version of _describe() - title and author only,
        no collection/translation notes - for the low-confidence
        confirmation dialog ('is this the one you meant?'), which needs
        just enough to help the person recognize/distinguish the match,
        not the full announcement _describe() builds for right before
        actually reading starts. Real request that led to this: 'Yes,
        it could be "how to boil an egg in 100 ways" by Andreas' reads
        naturally; the full _describe() output (also tacking on
        collection/translation-flag) would be a mouthful for a
        quick yes/no check."""
        parts = [candidate["title"]]
        if candidate.get("author"):
            parts.append(self._render('by_author', author=candidate["author"]))
        return ", ".join(parts)

    def _render(self, dialog, **data):
        """One line of a dialog file, in the language of the request in
        flight (the renderer follows the session, like speak_dialog)."""
        return self.dialog_renderer.render(dialog, data)

    def _option(self, key: str, default):
        """A setting from the plugin's section of mycroft.conf, which
        ovos-core hands the plugin as its config
        (intents["ovos-common-reading-pipeline-plugin"]), else from the
        plugin's settings file, else `default`."""
        for source in (getattr(self, "config", None), self.settings):
            if isinstance(source, dict) and source.get(key) is not None:
                return source[key]
        return default

    def _positive_option(self, key: str, default: float, allow_zero: bool = False) -> float:
        """_option() as a number above zero (or zero, with allow_zero). A
        value that isn't one is warned about once and `default` used."""
        raw = self._option(key, default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = -1.0
        if value > 0 or (value == 0 and allow_zero):
            return value
        if (key, repr(raw)) not in self._rejected_options:
            self._rejected_options.add((key, repr(raw)))
            self.log.warning(f"ignoring {key}={raw!r}, using {default}")
        return default

    def _spoken_wait(self, text: str) -> int:
        """spoken_wait() with the configured speaking rate and margin."""
        return spoken_wait(text,
                           self._positive_option("chars_per_second", SPOKEN_CHARS_PER_SECOND),
                           self._positive_option("wait_margin", SPOKEN_WAIT_MARGIN, allow_zero=True))

    def _narrating(self) -> bool:
        """Whether stories are read with SSML beside the text (#40): the
        "narration" option set to "ssml" (see _option). Off by default."""
        return str(self._option("narration", "") or "").strip().lower() == NARRATION_SSML

    def _speak_ssml(self, utterance: str, ssml: str, wait: Union[bool, int] = False):
        """speak(utterance, wait=wait), with data["utterance_ssml"] = ssml.

        ovos-workshop's speak() builds its message itself and takes no extra
        data, so this is its code with that one field added: the same topic
        (SPEAK_TOPIC), data and meta, forwarded from the same message
        (dig_for_message() finds the reader's `message` a frame or two up,
        as it does for speak()), the plugin's skill_id in the context, and
        the same wait. tests/test_narration.py checks the message against
        speak()'s on the installed ovos-workshop."""
        meta = {"skill": self.skill_id}
        data = {"utterance": utterance, "expect_response": False, "meta": meta, "lang": self.lang,
                "utterance_ssml": ssml}
        message = dig_for_message()
        m = message.forward(SPEAK_TOPIC, data) if message else Message(SPEAK_TOPIC, data)
        m.context["skill_id"] = self.skill_id
        self.bus.emit(m)
        if wait:
            timeout = 15 if isinstance(wait, bool) else wait
            session = SessionManager.get(m)
            session.is_speaking = True
            SessionManager.wait_while_speaking(timeout, session)

    def _speak_dialog_and_wait(self, key: str, data: Optional[dict] = None):
        """speak_dialog(key, data, wait=True), with the wait sized to the
        line (#41) instead of a flat 15 s.

        speak_dialog() takes its wait before it has picked the line, so this
        does what it does in the order the size needs: render the line with
        the same renderer, then hand it to speak() with the same meta."""
        data = data or {}
        if not self.dialog_renderer:
            self.speak_dialog(key, data, wait=True)
            return
        utterance = self.dialog_renderer.render(key, data)
        self.speak(utterance, wait=self._spoken_wait(utterance), meta={"dialog": key, "data": data})

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
        self._speak_dialog_and_wait('i_know_that', data={"description": self._describe(candidate)})
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
        and speak(wait=...) waits for that session's audio_output_end, so
        a client that reports its playback paces the story. One that doesn't
        is waited on for as long as each sentence takes to say (#41)."""
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
        sentences, paragraph_starts = [], set()
        for para in paragraphs:
            chunks = split_sentences(para)
            if chunks:
                paragraph_starts.add(len(sentences))
            sentences.extend(chunks)
        narrating = self._narrating()

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
            if narrating:
                pause = STORY_START_BREAK_MS if i == bookmark else \
                    PARAGRAPH_BREAK_MS if i in paragraph_starts else 0
                self._speak_ssml(sentence, narrate(sentence, pause), wait=self._spoken_wait(sentence))
            else:
                self.speak(sentence, wait=self._spoken_wait(sentence))
            # only marked done AFTER actually speaking it - if pause
            # sets the stop flag while this sentence is mid-speech,
            # speak(wait=...) still finishes it before returning, so
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
        # The only place the source is named (see _describe): after the last
        # sentence, and never for a story that was stopped or paused (the
        # return above), which the listener hasn't finished.
        if candidate.get("source"):
            self.speak_dialog('finished_reading', data={"source": candidate["source"]})
        else:
            self.speak_dialog('finished_reading_unsourced')
