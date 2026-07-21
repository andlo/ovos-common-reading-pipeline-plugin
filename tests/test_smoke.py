"""Smoke tests: the skill module must import cleanly."""
from conftest import CommonReading, ContentFetchError


def test_imports_cleanly():
    assert CommonReading is not None
    assert issubclass(ContentFetchError, Exception)


def test_common_reading_is_an_ovos_skill():
    from ovos_workshop.skills import OVOSSkill
    assert issubclass(CommonReading, OVOSSkill)
