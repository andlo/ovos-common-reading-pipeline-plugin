"""Shared pytest fixtures for the common-reading pipeline plugin test suite."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("common_reading_pipeline", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CommonReadingPipeline = _module.CommonReadingPipeline
ContentFetchError = _module.ContentFetchError
pick_best_candidate = _module.pick_best_candidate
COMMON_READING_SEARCH = _module.COMMON_READING_SEARCH
COMMON_READING_SEARCH_RESPONSE = _module.COMMON_READING_SEARCH_RESPONSE
COMMON_READING_FETCH_CONTENT = _module.COMMON_READING_FETCH_CONTENT
COMMON_READING_FETCH_CONTENT_RESPONSE = _module.COMMON_READING_FETCH_CONTENT_RESPONSE
COMMON_READING_PING = _module.COMMON_READING_PING
COMMON_READING_PONG = _module.COMMON_READING_PONG


@pytest.fixture
def plugin(monkeypatch):
    p = CommonReadingPipeline.__new__(CommonReadingPipeline)
    p.log = MagicMock()
    p.skill_id = "ovos-common-reading-pipeline-plugin.test"
    p.status = MagicMock()
    p._bus = MagicMock()
    p._settings = {}
    monkeypatch.setattr(CommonReadingPipeline, "lang", "en-us", raising=False)
    p.is_reading = False
    p.settings.setdefault('progress', {})
    p.settings.setdefault('last_content', None)
    p._intent_containers = {}
    return p
