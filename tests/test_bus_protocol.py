"""Tests for the bus mechanics: _search_providers (broadcast, collect all
responses) and _fetch_content (targeted request/response via
wait_for_response)."""
import time as real_time

import pytest
from conftest import (
    ContentFetchError,
    COMMON_READING_SEARCH,
    COMMON_READING_SEARCH_RESPONSE,
    COMMON_READING_FETCH_CONTENT,
    COMMON_READING_FETCH_CONTENT_RESPONSE,
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
        captured['handler'](FakeMessage({"skill_id": "a", "title": "X", "confidence": 0.9}))
        captured['handler'](FakeMessage({"skill_id": "b", "title": "Y", "confidence": 0.5}))

    monkeypatch.setattr(real_time, "sleep", fake_sleep)

    results = skill._search_providers("cinderella", timeout=0.01)

    assert len(results) == 2
    assert {r["skill_id"] for r in results} == {"a", "b"}
    assert captured['event'] == COMMON_READING_SEARCH_RESPONSE

    emitted = skill.bus.emit.call_args[0][0]
    assert emitted.msg_type == COMMON_READING_SEARCH
    assert emitted.data["phrase"] == "cinderella"
    assert emitted.data["content_type"] is None

    skill.bus.remove.assert_called_once_with(COMMON_READING_SEARCH_RESPONSE, captured['handler'])


def test_search_providers_passes_content_type_and_collection_hint(skill, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    skill._search_providers("cinderella", collection_hint="grimm", content_type="story")
    emitted = skill.bus.emit.call_args[0][0]
    assert emitted.data["collection_hint"] == "grimm"
    assert emitted.data["content_type"] == "story"


def test_search_providers_no_responses_returns_empty_list(skill, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    assert skill._search_providers("nothing will answer") == []


def test_fetch_content_success(skill):
    skill.bus.wait_for_response.return_value = FakeMessage(
        {"paragraphs": ["Once upon a time.", "The end."]}
    )
    candidate = {"skill_id": "ovos-skill-grimm-tales.andlo", "content_id": "Cinderella"}

    paragraphs = skill._fetch_content(candidate)

    assert paragraphs == ["Once upon a time.", "The end."]
    sent = skill.bus.wait_for_response.call_args[0][0]
    assert sent.msg_type == f"{COMMON_READING_FETCH_CONTENT}.ovos-skill-grimm-tales.andlo"
    assert sent.data["content_id"] == "Cinderella"
    assert skill.bus.wait_for_response.call_args[1]["reply_type"] == COMMON_READING_FETCH_CONTENT_RESPONSE


def test_fetch_content_timeout_raises(skill):
    skill.bus.wait_for_response.return_value = None
    with pytest.raises(ContentFetchError):
        skill._fetch_content({"skill_id": "x", "content_id": "y"})


def test_fetch_content_empty_paragraphs_raises(skill):
    skill.bus.wait_for_response.return_value = FakeMessage({"paragraphs": []})
    with pytest.raises(ContentFetchError):
        skill._fetch_content({"skill_id": "x", "content_id": "y"})
