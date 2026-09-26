"""Tests for the bus mechanics: _search_providers (broadcast, collect all
responses), _fetch_content (targeted request, first answer) and
_ping_providers - on a real FakeBus, with small fake providers that answer
the way the real ones do (message.reply())."""
import time as real_time

import pytest
from ovos_utils.fakebus import FakeBus

from conftest import (
    ContentFetchError,
    COMMON_READING_SEARCH,
    COMMON_READING_SEARCH_RESPONSE,
    COMMON_READING_FETCH_CONTENT,
    COMMON_READING_FETCH_CONTENT_RESPONSE,
    COMMON_READING_PING,
    COMMON_READING_PONG,
    dispatch_message,
)


@pytest.fixture
def bus(plugin, monkeypatch):
    plugin._bus = FakeBus()
    # the search/ping windows are plain sleeps; FakeBus answers synchronously
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)
    return plugin._bus


def _record(bus, msg_type):
    seen = []
    bus.on(msg_type, seen.append)
    return seen


def test_search_providers_collects_all_responses(plugin, bus):
    requests = _record(bus, COMMON_READING_SEARCH)
    bus.on(COMMON_READING_SEARCH, lambda m: bus.emit(m.reply(
        COMMON_READING_SEARCH_RESPONSE, {"skill_id": "a", "title": "X", "confidence": 0.9})))
    bus.on(COMMON_READING_SEARCH, lambda m: bus.emit(m.reply(
        COMMON_READING_SEARCH_RESPONSE, {"skill_id": "b", "title": "Y", "confidence": 0.5})))

    results = plugin._search_providers(dispatch_message(), "cinderella", timeout=0.01)

    assert {r["skill_id"] for r in results} == {"a", "b"}
    assert requests[0].data["phrase"] == "cinderella"
    assert requests[0].data["content_type"] is None
    assert requests[0].data["requester"] == plugin.skill_id
    # the collector is gone once the window closes
    bus.emit(dispatch_message().forward(COMMON_READING_SEARCH_RESPONSE, {"skill_id": "late"}))
    assert {r["skill_id"] for r in results} == {"a", "b"}


def test_search_carries_the_requests_session_and_language(plugin, bus):
    """Providers see who asked and in which language: the search is
    forwarded from the dispatch (context kept) and says "lang"."""
    requests = _record(bus, COMMON_READING_SEARCH)

    plugin._search_providers(dispatch_message("alice", lang="fr-FR"), None, content_type="story")

    request = requests[0]
    assert request.data["lang"] == "fr-FR"
    assert request.data["phrase"] is None
    assert request.data["content_type"] == "story"
    assert request.context["session"]["session_id"] == "alice"
    assert request.context["source"] == "hive.client"  # routing kept


def test_lang_is_the_language_the_request_was_matched_in(plugin, bus):
    """The payload's "lang" comes from the dispatch's data (the language
    ovos-core matched in), never from the session: for the default session
    a provider's SessionManager.get() returns the device's own language,
    whatever the message carried."""
    searches, pings = _record(bus, COMMON_READING_SEARCH), _record(bus, COMMON_READING_PING)
    fetches = _record(bus, f"{COMMON_READING_FETCH_CONTENT}.x")
    message = dispatch_message("default", lang="fr-FR")
    message.context["session"]["lang"] = "en-US"

    plugin._search_providers(message, None)
    plugin._ping_providers(message)
    with pytest.raises(ContentFetchError):
        plugin._fetch_content(message, {"skill_id": "x", "content_id": "y"}, timeout=0.01)

    assert [m.data["lang"] for m in searches + pings + fetches] == ["fr-FR"] * 3


def test_search_providers_passes_content_type_and_collection_hint(plugin, bus):
    requests = _record(bus, COMMON_READING_SEARCH)

    plugin._search_providers(dispatch_message(), "cinderella", collection_hint="grimm", content_type="story")

    assert requests[0].data["collection_hint"] == "grimm"
    assert requests[0].data["content_type"] == "story"


def test_search_providers_no_responses_returns_empty_list(plugin, bus):
    assert plugin._search_providers(dispatch_message(), "nothing will answer") == []


def test_search_ignores_answers_meant_for_another_session(plugin, bus):
    """Two users searching at the same moment on a hub: each only gets the
    answers to its own search."""
    def provider(message):
        bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {"skill_id": "mine", "confidence": 1.0}))
        bus.emit(dispatch_message("bob").forward(COMMON_READING_SEARCH_RESPONSE,
                                                 {"skill_id": "bobs", "confidence": 1.0}))

    bus.on(COMMON_READING_SEARCH, provider)

    results = plugin._search_providers(dispatch_message("alice"), "cinderella")

    assert [r["skill_id"] for r in results] == ["mine"]


def test_fetch_content_success(plugin, bus):
    requests = _record(bus, f"{COMMON_READING_FETCH_CONTENT}.ovos-skill-grimm-tales.andlo")
    bus.on(f"{COMMON_READING_FETCH_CONTENT}.ovos-skill-grimm-tales.andlo", lambda m: bus.emit(m.reply(
        COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": ["Once upon a time.", "The end."]})))
    candidate = {"skill_id": "ovos-skill-grimm-tales.andlo", "content_id": "Cinderella"}

    paragraphs = plugin._fetch_content(dispatch_message("alice", lang="de-DE"), candidate)

    assert paragraphs == ["Once upon a time.", "The end."]
    assert requests[0].data["content_id"] == "Cinderella"
    assert requests[0].data["lang"] == "de-DE"
    assert requests[0].context["session"]["session_id"] == "alice"


def test_fetch_takes_only_its_own_sessions_text(plugin, bus):
    """wait_for_response() took the first fetch_content.response on the
    bus, whoever it was for - with two stories starting at once, one user
    could be read the other's story."""
    def provider(message):
        bus.emit(dispatch_message("bob").forward(COMMON_READING_FETCH_CONTENT_RESPONSE,
                                                 {"paragraphs": ["Bob's story."]}))
        bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": ["Alice's story."]}))

    bus.on(f"{COMMON_READING_FETCH_CONTENT}.x", provider)

    assert plugin._fetch_content(dispatch_message("alice"), {"skill_id": "x", "content_id": "y"}) == ["Alice's story."]


def test_fetch_content_timeout_raises(plugin, bus):
    with pytest.raises(ContentFetchError):
        plugin._fetch_content(dispatch_message(), {"skill_id": "x", "content_id": "y"}, timeout=0.01)


def test_fetch_content_empty_paragraphs_raises(plugin, bus):
    bus.on(f"{COMMON_READING_FETCH_CONTENT}.x", lambda m: bus.emit(m.reply(
        COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": []})))
    with pytest.raises(ContentFetchError):
        plugin._fetch_content(dispatch_message(), {"skill_id": "x", "content_id": "y"})


def test_ping_providers_collects_all_pongs(plugin, bus):
    pings = _record(bus, COMMON_READING_PING)
    bus.on(COMMON_READING_PING, lambda m: bus.emit(m.reply(
        COMMON_READING_PONG, {"skill_id": "a", "collection": "Grimm's Fairy Tales"})))
    bus.on(COMMON_READING_PING, lambda m: bus.emit(m.reply(
        COMMON_READING_PONG, {"skill_id": "b", "collection": "365tomorrows"})))

    results = plugin._ping_providers(dispatch_message("alice"), timeout=0.01)

    assert {r["skill_id"] for r in results} == {"a", "b"}
    assert pings[0].data["requester"] == plugin.skill_id
    assert pings[0].context["session"]["session_id"] == "alice"


def test_ping_providers_no_pongs_returns_empty_list(plugin, bus):
    assert plugin._ping_providers(dispatch_message()) == []
