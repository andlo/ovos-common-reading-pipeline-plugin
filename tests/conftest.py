"""Shared pytest fixtures for the common-tales skill test suite.

Same approach as the other tales skills: build a bare instance via
CommonTales.__new__() rather than going through OVOSSkill's normal
__init__ (which needs a live messagebus connection), and attach just the
attributes the methods under test actually use.
"""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("common_tales_skill", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CommonTales = _module.CommonTales
StoryFetchError = _module.StoryFetchError
pick_best_candidate = _module.pick_best_candidate
COMMON_TALES_SEARCH = _module.COMMON_TALES_SEARCH
COMMON_TALES_SEARCH_RESPONSE = _module.COMMON_TALES_SEARCH_RESPONSE
COMMON_TALES_FETCH_STORY = _module.COMMON_TALES_FETCH_STORY
COMMON_TALES_FETCH_STORY_RESPONSE = _module.COMMON_TALES_FETCH_STORY_RESPONSE


@pytest.fixture
def skill(monkeypatch):
    s = CommonTales.__new__(CommonTales)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-common-tales.test"
    s.status = MagicMock()
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(CommonTales, "lang", "en-us", raising=False)
    s.is_reading = False
    s.settings.setdefault('progress', {})
    s.settings.setdefault('last_story', None)
    return s
