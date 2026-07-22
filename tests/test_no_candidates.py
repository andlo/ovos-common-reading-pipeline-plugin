"""Tests for _handle_no_candidates: the three-way dialog choice driven
by ping/pong (see #2) - 'nothing installed' vs 'installed but no
collection match' vs 'installed but no phrase match'."""
from unittest.mock import MagicMock


def _wire(plugin):
    plugin.speak_dialog = MagicMock()
    return plugin


def test_no_pongs_speaks_no_content_providers(plugin):
    _wire(plugin)
    plugin._ping_providers = MagicMock(return_value=[])

    plugin._handle_no_candidates(collection_hint=None)

    plugin.speak_dialog.assert_called_once_with('no_content_providers')


def test_no_pongs_with_collection_hint_still_speaks_no_content_providers(plugin):
    """Even if the user asked for a specific collection, 'nothing
    installed at all' takes priority over 'no such collection' - it's
    the more accurate and more actionable thing to tell them."""
    _wire(plugin)
    plugin._ping_providers = MagicMock(return_value=[])

    plugin._handle_no_candidates(collection_hint="grimm")

    plugin.speak_dialog.assert_called_once_with('no_content_providers')


def test_pongs_but_no_phrase_match_speaks_no_matching_content(plugin):
    _wire(plugin)
    plugin._ping_providers = MagicMock(return_value=[
        {"skill_id": "ovos-skill-grimm-tales.andlo", "collection": "Grimm's Fairy Tales"},
    ])

    plugin._handle_no_candidates(collection_hint=None)

    plugin.speak_dialog.assert_called_once_with('no_matching_content')


def test_pongs_with_collection_hint_speaks_no_such_collection(plugin):
    _wire(plugin)
    plugin._ping_providers = MagicMock(return_value=[
        {"skill_id": "ovos-skill-grimm-tales.andlo", "collection": "Grimm's Fairy Tales"},
    ])

    plugin._handle_no_candidates(collection_hint="perrault")

    plugin.speak_dialog.assert_called_once_with('no_such_collection', data={"collection": "perrault"})


def test_ping_only_fires_once_per_no_candidates_call(plugin):
    """Regression guard: _ping_providers should be called exactly once,
    not once per dialog branch - it's the single source of truth this
    method branches on."""
    _wire(plugin)
    plugin._ping_providers = MagicMock(return_value=[])

    plugin._handle_no_candidates(collection_hint=None)

    plugin._ping_providers.assert_called_once()


def test_search_and_read_calls_handle_no_candidates_when_nothing_found(plugin):
    _wire(plugin)
    plugin._search_providers = MagicMock(return_value=[])
    plugin._handle_no_candidates = MagicMock()

    plugin._search_and_read("cinderella", collection_hint="grimm")

    plugin._handle_no_candidates.assert_called_once_with("grimm")
