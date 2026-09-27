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
    return p
