"""Shared pytest fixtures for the common-reading skill test suite."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("common_reading_skill", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CommonReading = _module.CommonReading
ContentFetchError = _module.ContentFetchError
pick_best_candidate = _module.pick_best_candidate
COMMON_READING_SEARCH = _module.COMMON_READING_SEARCH
COMMON_READING_SEARCH_RESPONSE = _module.COMMON_READING_SEARCH_RESPONSE
COMMON_READING_FETCH_CONTENT = _module.COMMON_READING_FETCH_CONTENT
COMMON_READING_FETCH_CONTENT_RESPONSE = _module.COMMON_READING_FETCH_CONTENT_RESPONSE


@pytest.fixture
def skill(monkeypatch):
    s = CommonReading.__new__(CommonReading)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-common-reading.test"
    s.status = MagicMock()
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(CommonReading, "lang", "en-us", raising=False)
    s.is_reading = False
    s.settings.setdefault('progress', {})
    s.settings.setdefault('last_content', None)
    return s
