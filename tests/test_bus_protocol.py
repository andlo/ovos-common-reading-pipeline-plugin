"""Tests for the bus mechanics: _search_providers (broadcast, collect all
responses) and _fetch_story (targeted request/response via
wait_for_response). Bus calls are mocked; time.sleep is monkeypatched so
tests run instantly instead of waiting out real timeouts."""
import time as real_time

import pytest
from conftest import (
    StoryFetchError,
    COMMON_TALES_SEARCH,
    COMMON_TALES_SEARCH_RESPONSE,
    COMMON_TALES_FETCH_STORY,
    COMMON_TALES_FETCH_STORY_RESPONSE,
)


class FakeMessage:
    def __init__(self, data):
        self.data = data


def test_search_providers_collects_all_responses(skill, monkeypatch):
    captured = {}

    def fake_on(event, handler):
        captured['event'] = event
        captured['handler'] = handler

    skill.bus.on.side_effect = fake_on

    def fake_sleep(_seconds):
        # simulate two providers answering while we're "waiting"
        captured['handler'](FakeMessage({"skill_id": "a", "title": "X", "confidence": 0.9}))
        captured['handler'](FakeMessage({"skill_id": "b", "title": "Y", "confidence": 0.5}))

    monkeypatch.setattr(real_time, "sleep", fake_sleep)

    results = skill._search_providers("cinderella", timeout=0.01)

    assert len(results) == 2
    assert {r["skill_id"] for r in results} == {"a", "b"}
    assert captured['event'] == COMMON_TALES_SEARCH_RESPONSE

    emitted = skill.bus.emit.call_args[0][0]
    assert emitted.msg_type == COMMON_TALES_SEARCH
    assert emitted.data["phrase"] == "cinderella"

    skill.bus.remove.assert_called_once_with(COMMON_TALES_SEARCH_RESPONSE, captured['handler'])


def test_search_providers_no_responses_returns_empty_list(skill, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    assert skill._search_providers("nothing will answer") == []


def test_search_providers_passes_collection_hint(skill, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    skill._search_providers("cinderella", collection_hint="grimm")
    emitted = skill.bus.emit.call_args[0][0]
    assert emitted.data["collection_hint"] == "grimm"


def test_search_providers_defaults_collection_hint_to_none(skill, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    skill._search_providers("cinderella")
    emitted = skill.bus.emit.call_args[0][0]
    assert emitted.data["collection_hint"] is None


def test_fetch_story_success(skill):
    skill.bus.wait_for_response.return_value = FakeMessage(
        {"paragraphs": ["Once upon a time.", "The end."]}
    )
    candidate = {"skill_id": "ovos-skill-grimm-tales.andlo", "story_id": "Cinderella"}

    paragraphs = skill._fetch_story(candidate)

    assert paragraphs == ["Once upon a time.", "The end."]
    sent = skill.bus.wait_for_response.call_args[0][0]
    assert sent.msg_type == f"{COMMON_TALES_FETCH_STORY}.ovos-skill-grimm-tales.andlo"
    assert sent.data["story_id"] == "Cinderella"
    assert skill.bus.wait_for_response.call_args[1]["reply_type"] == COMMON_TALES_FETCH_STORY_RESPONSE


def test_fetch_story_timeout_raises(skill):
    skill.bus.wait_for_response.return_value = None
    with pytest.raises(StoryFetchError):
        skill._fetch_story({"skill_id": "x", "story_id": "y"})


def test_fetch_story_empty_paragraphs_raises(skill):
    skill.bus.wait_for_response.return_value = FakeMessage({"paragraphs": []})
    with pytest.raises(StoryFetchError):
        skill._fetch_story({"skill_id": "x", "story_id": "y"})
