"""Shared pytest fixtures for the common-reading pipeline plugin test suite."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ovos_bus_client.message import Message

REPO_ROOT = Path(__file__).resolve().parents[1]
_INIT_PATH = REPO_ROOT / "__init__.py"
_spec = importlib.util.spec_from_file_location("common_reading_pipeline", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
# registered so a real CommonReadingPipeline(bus=...) can be built: OVOSSkill
# looks its own module up in sys.modules to find its root directory
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

module = _module  # exposed so tests can monkeypatch module-level names (e.g. dig_for_message)
CommonReadingPipeline = _module.CommonReadingPipeline
ContentFetchError = _module.ContentFetchError
pick_best_candidate = _module.pick_best_candidate
COMMON_READING_SEARCH = _module.COMMON_READING_SEARCH
COMMON_READING_SEARCH_RESPONSE = _module.COMMON_READING_SEARCH_RESPONSE
COMMON_READING_FETCH_CONTENT = _module.COMMON_READING_FETCH_CONTENT
COMMON_READING_FETCH_CONTENT_RESPONSE = _module.COMMON_READING_FETCH_CONTENT_RESPONSE
COMMON_READING_PING = _module.COMMON_READING_PING
COMMON_READING_PONG = _module.COMMON_READING_PONG


def session_message(session_id="default", msg_type="test", data=None, lang="en-US", **context):
    """A Message the way ovos-core hands it over: with a session carrier
    naming `session_id` (and routing context, when given)."""
    context.setdefault("session", {"session_id": session_id, "lang": lang})
    return Message(msg_type, dict(data or {}), context)


def report_end(plugin, session_id="default"):
    """What a client that reports its playback sends when a sentence is said:
    recognizer_loop:audio_output_end on the story's session, to whichever
    reader is listening (the bus is a MagicMock; its on() calls hold them)."""
    for call in plugin.bus.on.call_args_list:
        if call.args and call.args[0] == "recognizer_loop:audio_output_end":
            call.args[1](session_message(session_id, "recognizer_loop:audio_output_end"))


def dispatch_message(session_id="default", intent="read_content", data=None, lang="en-US",
                     skill_id="ovos-common-reading-pipeline-plugin.test"):
    """The dispatch ovos-core sends a handler: "<skill_id>:<intent>", the
    utterance's data plus the captured entities, "lang", and the requesting
    session and route in its context."""
    payload = {"utterances": ["..."], "lang": lang, "utterance": "..."}
    payload.update(data or {})
    return session_message(session_id, f"{skill_id}:{intent}", payload, lang=lang,
                           source="hive.client", destination="skills", skill_id=skill_id)


def entry(plugin, session_id="default"):
    """A session's slice of the plugin settings."""
    return plugin.settings["sessions"][session_id]


def use_real_dialogs(plugin, monkeypatch, lang="en-us"):
    """Let speak_dialog()/_describe() render the bundled locale files for
    `lang` instead of a mock."""
    monkeypatch.setattr(CommonReadingPipeline, "lang", lang, raising=False)
    monkeypatch.setattr(CommonReadingPipeline, "_auto_register_entity_files",
                        lambda *a, **kw: None, raising=False)
    plugin.res_dir = str(REPO_ROOT)
    plugin._lang_resources = {}
    return plugin


class VirtualClock:
    """time.monotonic for _ReadAhead, moved on by its pauses instead of waiting."""

    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def plugin(monkeypatch):
    p = CommonReadingPipeline.__new__(CommonReadingPipeline)
    p.log = MagicMock()
    p.skill_id = "ovos-common-reading-pipeline-plugin.test"
    p.status = MagicMock()
    p._bus = MagicMock()
    p._settings = {}
    p._OVOSSkill__responses = {}  # ovos-workshop's get_response bookkeeping, touched by a stop
    monkeypatch.setattr(CommonReadingPipeline, "lang", "en-us", raising=False)
    p._init_state()
    # Story time is virtual: a sentence nobody reports on is over when its
    # spoken_wait says so, and the test does not sit through it.
    clock = VirtualClock()
    p._read_ahead_timing = {"clock": clock.now, "pause": clock.advance}
    p.clock = clock
    return p


def announce(plugin, skill_id, lang="en-us", content_types=None, collections=None, titles=None):
    """What a provider sends when it loads: ovos.common_reading.vocabulary."""
    plugin._handle_vocabulary(Message(_module.COMMON_READING_VOCABULARY, {
        "skill_id": skill_id, "lang": lang, "content_types": content_types or {},
        "collections": collections or [], "titles": titles or []}))


ALL_LANGS = ["en-us", "da-dk", "de-de", "es-es", "fr-fr", "it-it", "nl-nl", "pt-pt"]


def announce_typical_providers(plugin):
    """A realistic set: story collections with a few titles, a horoscope,
    an almanac, a blog and an archive of articles."""
    for lang in ALL_LANGS:
        announce(plugin, "grimm.test", lang, collections=["grimm", "brothers grimm", "brødrene grimm"],
                 titles=["Rapunzel", "Cinderella"] if lang == "en-us" else [])
        announce(plugin, "andersen.test", lang, collections=["andersen", "hans christian andersen", "h c andersen"])
    announce(plugin, "andersen.test", "en-us", collections=["andersen", "hans christian andersen"],
             titles=["The Little Mermaid", "The Ugly Duckling", "The Snow Queen", "The Tinderbox"])
    announce(plugin, "andersen.test", "da-dk", collections=["andersen", "h c andersen"],
             titles=["Den lille havfrue", "Den grimme ælling"])
    # French literary short story ("une nouvelle"); never "les nouvelles" (the news)
    announce(plugin, "cosquin.test", "fr-fr", collections=["cosquin"],
             content_types={"story": ["nouvelle"]})
    announce(plugin, "horoscope.test", "en-us", content_types={"horoscope": ["horoscope", "horoscopes"]})
    announce(plugin, "horoscope.test", "da-dk", content_types={"horoscope": ["horoskop", "horoskopet"]})
    announce(plugin, "almanac.test", "en-us", content_types={"almanac": ["almanac"]})
    announce(plugin, "blog.test", "en-us", content_types={"post": ["post", "posts", "blog post"],
                                                         "article": ["article", "articles"]},
             collections=["ovosblog", "ovos blog"])
    announce(plugin, "archive.test", "en-us", collections=["archive"])
