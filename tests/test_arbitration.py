"""Tests for the pure candidate-selection and description helpers."""
from conftest import pick_best_candidate, CommonReading


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


def test_pick_best_candidate_missing_confidence_defaults_to_zero():
    candidates = [
        {"skill_id": "a", "title": "X"},
        {"skill_id": "b", "title": "Y", "confidence": 0.1},
    ]
    best = pick_best_candidate(candidates)
    assert best["skill_id"] == "b"


def test_describe_includes_all_present_fields():
    candidate = {
        "title": "Cinderella",
        "author": "Brothers Grimm",
        "collection": "Household Tales",
        "source": "grimmstories.com",
    }
    assert CommonReading._describe(candidate) == (
        "Cinderella, by Brothers Grimm, from Household Tales, sourced from grimmstories.com"
    )


def test_describe_gracefully_skips_missing_fields():
    candidate = {"title": "Cinderella", "author": "", "source": "grimmstories.com"}
    assert CommonReading._describe(candidate) == "Cinderella, sourced from grimmstories.com"


def test_describe_title_only():
    candidate = {"title": "Cinderella"}
    assert CommonReading._describe(candidate) == "Cinderella"


def test_describe_discloses_machine_translation():
    candidate = {"title": "Kedelige installationer", "source": "blog.openvoiceos.org", "machine_translated": True}
    assert CommonReading._describe(candidate) == (
        "Kedelige installationer, sourced from blog.openvoiceos.org, machine translated"
    )


def test_describe_omits_disclosure_when_not_translated():
    candidate = {"title": "Boring installs", "source": "blog.openvoiceos.org", "machine_translated": False}
    assert "machine translated" not in CommonReading._describe(candidate)


def test_progress_key_combines_skill_and_content_id():
    candidate = {"skill_id": "ovos-skill-grimm-tales.andlo", "content_id": "Cinderella"}
    assert CommonReading._progress_key(candidate) == "ovos-skill-grimm-tales.andlo::Cinderella"
