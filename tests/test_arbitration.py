"""Tests for the pure candidate-selection and description helpers."""
import pytest

from conftest import pick_best_candidate, CommonReadingPipeline, use_real_dialogs


@pytest.fixture
def en(plugin, monkeypatch):
    """The plugin, rendering the bundled en-us dialogs."""
    return use_real_dialogs(plugin, monkeypatch, "en-us")


def test_pick_best_candidate_picks_highest_confidence():
    candidates = [
        {"skill_id": "a", "title": "Cinderella", "confidence": 0.6},
        {"skill_id": "b", "title": "Cinderella, Or The Little Glass Slipper", "confidence": 0.95},
        {"skill_id": "c", "title": "Ash Girl", "confidence": 0.4},
    ]
    best = pick_best_candidate(candidates)
    assert best["skill_id"] == "b"


def test_pick_best_candidate_empty_list_returns_none():
    assert pick_best_candidate([]) is None


def test_pick_best_candidate_breaks_ties_at_random():
    """"Tell me a story" gets one random story from each story provider,
    all at the same confidence: the first to answer must not win every time."""
    candidates = [
        {"skill_id": "a", "title": "Rapunzel", "confidence": 0.9},
        {"skill_id": "b", "title": "La Biche blanche", "confidence": 0.9},
        {"skill_id": "c", "title": "Aschenputtel", "confidence": 0.5},
    ]
    picked = {pick_best_candidate(candidates)["skill_id"] for _ in range(200)}
    assert picked == {"a", "b"}


def test_describe_short_is_title_and_author(en):
    candidate = {"title": "Cinderella", "author": "Brothers Grimm", "collection": "Household Tales",
                 "source": "grimmstories.com"}
    assert en._describe_short(candidate) == "Cinderella, by Brothers Grimm"


def test_pick_best_candidate_missing_confidence_defaults_to_zero():
    candidates = [
        {"skill_id": "a", "title": "X"},
        {"skill_id": "b", "title": "Y", "confidence": 0.1},
    ]
    best = pick_best_candidate(candidates)
    assert best["skill_id"] == "b"


def test_describe_includes_all_present_fields(en):
    candidate = {
        "title": "Cinderella",
        "author": "Brothers Grimm",
        "collection": "Household Tales",
        "source": "grimmstories.com",
    }
    assert en._describe(candidate) == (
        "Cinderella, by Brothers Grimm, from Household Tales, sourced from grimmstories.com"
    )


def test_describe_gracefully_skips_missing_fields(en):
    candidate = {"title": "Cinderella", "author": "", "source": "grimmstories.com"}
    assert en._describe(candidate) == "Cinderella, sourced from grimmstories.com"


def test_describe_title_only(en):
    candidate = {"title": "Cinderella"}
    assert en._describe(candidate) == "Cinderella"


def test_describe_discloses_machine_translation(en):
    candidate = {"title": "Kedelige installationer", "source": "blog.openvoiceos.org", "machine_translated": True}
    assert en._describe(candidate) == (
        "Kedelige installationer, sourced from blog.openvoiceos.org, machine translated"
    )


def test_describe_omits_disclosure_when_not_translated(en):
    candidate = {"title": "Boring installs", "source": "blog.openvoiceos.org", "machine_translated": False}
    assert "machine translated" not in en._describe(candidate)


def test_progress_key_combines_skill_and_content_id():
    candidate = {"skill_id": "ovos-skill-grimm-tales.andlo", "content_id": "Cinderella"}
    assert CommonReadingPipeline._progress_key(candidate) == "ovos-skill-grimm-tales.andlo::Cinderella"
