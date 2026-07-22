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
    COMMON_READING_PING,
    COMMON_READING_PONG,
)


class FakeMessage:
    def __init__(self, data):
        self.data = data


def test_search_providers_collects_all_responses(plugin, monkeypatch):
    captured = {}

    def fake_on(event, handler):
        captured['event'] = event
        captured['handler'] = handler

    plugin.bus.on.side_effect = fake_on

    def fake_sleep(_seconds):
        captured['handler'](FakeMessage({"skill_id": "a", "title": "X", "confidence": 0.9}))
        captured['handler'](FakeMessage({"skill_id": "b", "title": "Y", "confidence": 0.5}))

    monkeypatch.setattr(real_time, "sleep", fake_sleep)

    results = plugin._search_providers("cinderella", timeout=0.01)

    assert len(results) == 2
    assert {r["skill_id"] for r in results} == {"a", "b"}
    assert captured['event'] == COMMON_READING_SEARCH_RESPONSE

    emitted = plugin.bus.emit.call_args[0][0]
    assert emitted.msg_type == COMMON_READING_SEARCH
    assert emitted.data["phrase"] == "cinderella"
    assert emitted.data["content_type"] is None

    plugin.bus.remove.assert_called_once_with(COMMON_READING_SEARCH_RESPONSE, captured['handler'])


def test_search_providers_passes_content_type_and_collection_hint(plugin, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    plugin._search_providers("cinderella", collection_hint="grimm", content_type="story")
    emitted = plugin.bus.emit.call_args[0][0]
    assert emitted.data["collection_hint"] == "grimm"
    assert emitted.data["content_type"] == "story"


def test_search_providers_no_responses_returns_empty_list(plugin, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    assert plugin._search_providers("nothing will answer") == []


def test_fetch_content_success(plugin):
    plugin.bus.wait_for_response.return_value = FakeMessage(
        {"paragraphs": ["Once upon a time.", "The end."]}
    )
    candidate = {"skill_id": "ovos-skill-grimm-tales.andlo", "content_id": "Cinderella"}

    paragraphs = plugin._fetch_content(candidate)

    assert paragraphs == ["Once upon a time.", "The end."]
    sent = plugin.bus.wait_for_response.call_args[0][0]
    assert sent.msg_type == f"{COMMON_READING_FETCH_CONTENT}.ovos-skill-grimm-tales.andlo"
    assert sent.data["content_id"] == "Cinderella"
    assert plugin.bus.wait_for_response.call_args[1]["reply_type"] == COMMON_READING_FETCH_CONTENT_RESPONSE


def test_fetch_content_timeout_raises(plugin):
    plugin.bus.wait_for_response.return_value = None
    with pytest.raises(ContentFetchError):
        plugin._fetch_content({"skill_id": "x", "content_id": "y"})


def test_fetch_content_empty_paragraphs_raises(plugin):
    plugin.bus.wait_for_response.return_value = FakeMessage({"paragraphs": []})
    with pytest.raises(ContentFetchError):
        plugin._fetch_content({"skill_id": "x", "content_id": "y"})


def test_ping_providers_collects_all_pongs(plugin, monkeypatch):
    captured = {}

    def fake_on(event, handler):
        captured['event'] = event
        captured['handler'] = handler

    plugin.bus.on.side_effect = fake_on

    def fake_sleep(_seconds):
        captured['handler'](FakeMessage({"skill_id": "a", "collection": "Grimm's Fairy Tales"}))
        captured['handler'](FakeMessage({"skill_id": "b", "collection": "365tomorrows"}))

    monkeypatch.setattr(real_time, "sleep", fake_sleep)

    results = plugin._ping_providers(timeout=0.01)

    assert len(results) == 2
    assert {r["skill_id"] for r in results} == {"a", "b"}
    assert captured['event'] == COMMON_READING_PONG

    emitted = plugin.bus.emit.call_args[0][0]
    assert emitted.msg_type == COMMON_READING_PING

    plugin.bus.remove.assert_called_once_with(COMMON_READING_PONG, captured['handler'])


def test_ping_providers_no_pongs_returns_empty_list(plugin, monkeypatch):
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    assert plugin._ping_providers() == []
