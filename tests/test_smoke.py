"""Smoke tests: the skill module must import cleanly."""
from conftest import CommonTales, StoryFetchError


def test_imports_cleanly():
    assert CommonTales is not None
    assert issubclass(StoryFetchError, Exception)


def test_common_tales_is_an_ovos_skill():
    from ovos_workshop.skills import OVOSSkill
    assert issubclass(CommonTales, OVOSSkill)
