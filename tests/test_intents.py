"""Tests for match() dispatch logic and the underlying _search_and_read /
_handle_continue / stop behavior. The padacioso IntentContainer itself is
mocked here (its real matching behavior across all 8 languages is
verified separately, live, against the actual bundled *.intent files -
see scripts/build_padacioso_intents.py's docstring) so these tests focus
on what match() does once it has a result."""
from unittest.mock import MagicMock

from conftest import CommonReadingPipeline


def make_message(data=None):
    m = MagicMock()
    m.data = data or {}
    return m


def _wire_common_mocks(plugin):
    plugin.speak_dialog = MagicMock()
    plugin.ask_yesno = MagicMock(return_value="yes")


def _fake_container(result):
    container = MagicMock()
    container.calc_intent = MagicMock(return_value=result)
    return container


def test_match_dispatches_read_content(plugin, monkeypatch):
    _wire_common_mocks(plugin)
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_content", "conf": 0.9, "entities": {"title": "cinderella"}})
    plugin._search_and_read = MagicMock()

    result = plugin.match(["tell me a story about cinderella"], "en-us", make_message())

    plugin._search_and_read.assert_called_once_with("cinderella")
    assert result is not None
    assert result.skill_id == plugin.skill_id


def test_match_dispatches_read_by_collection(plugin):
    _wire_common_mocks(plugin)
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_by_collection", "conf": 0.9, "entities": {"title": None, "collection": "grimm"}})
    plugin._search_and_read = MagicMock()

    plugin.match(["tell me a story from grimm"], "en-us", make_message())

    plugin._search_and_read.assert_called_once_with(None, collection_hint="grimm")


def test_match_below_confidence_threshold_returns_none(plugin):
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_content", "conf": 0.1, "entities": {"title": "cinderella"}})
    plugin._search_and_read = MagicMock()

    result = plugin.match(["mumble mumble cinderella"], "en-us", make_message())

    assert result is None
    plugin._search_and_read.assert_not_called()


def test_match_no_intent_name_returns_none(plugin):
    plugin._intent_containers["en-us"] = _fake_container({"name": None, "entities": {}})

    result = plugin.match(["what is the weather"], "en-us", make_message())

    assert result is None


def test_match_continue_with_nothing_in_progress_declines(plugin):
    """The key improvement over the old skill-based 'continue.intent':
    if nothing is actually in progress, match() returns None instead of
    claiming the utterance and speaking a 'nothing to continue' dialog -
    letting a later pipeline stage try instead."""
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "continue", "conf": 0.95, "entities": {}})
    plugin.settings['last_content'] = None

    result = plugin.match(["continue"], "en-us", make_message())

    assert result is None


def test_match_continue_with_something_in_progress_reads_it(plugin):
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    plugin.settings['last_content'] = candidate
    plugin.settings['progress'][CommonReadingPipeline._progress_key(candidate)] = 7
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "continue", "conf": 0.95, "entities": {}})
    plugin._read_content = MagicMock()

    result = plugin.match(["continue"], "en-us", make_message())

    plugin._read_content.assert_called_once_with(candidate, 7)
    assert result is not None


def test_stop_while_reading_speaks_and_returns_true(plugin):
    _wire_common_mocks(plugin)
    plugin.is_reading = True

    result = plugin.stop()

    assert result is True
    assert plugin.is_reading is False
    # wait=True is required, not optional - see the comment on stop()
    # in __init__.py. Without it, this confirmation was silently
    # getting flushed by OVOS core's own global stop handling before
    # ever reaching the speaker - a real bug found in manual testing.
    plugin.speak_dialog.assert_called_once_with('stop_reading', wait=True)


def test_stop_while_not_reading_returns_false(plugin):
    _wire_common_mocks(plugin)
    plugin.is_reading = False

    assert plugin.stop() is False


def test_match_pause_with_nothing_being_read_declines(plugin):
    """Same decline-rather-than-claim reasoning as 'continue': saying
    'pause' when nothing is actually being read should not be silently
    swallowed by this pipeline - let a later stage try instead."""
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "pause", "conf": 0.95, "entities": {}})
    plugin.is_reading = False

    result = plugin.match(["pause"], "en-us", make_message())

    assert result is None


def test_match_pause_while_reading_stops_and_speaks_paused_dialog(plugin):
    """The actual fix: 'pause' is matched by this pipeline's OWN intent
    parser, not left to OVOS's global stop vocabulary (which may or may
    not treat 'pause' as a synonym for 'stop') - so it reliably works
    regardless of core-level vocabulary."""
    _wire_common_mocks(plugin)
    plugin.is_reading = True
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "pause", "conf": 0.95, "entities": {}})

    result = plugin.match(["pause"], "en-us", make_message())

    assert plugin.is_reading is False
    # wait=True is required, not optional - same reasoning/bug as stop()
    plugin.speak_dialog.assert_called_once_with('paused', wait=True)
    assert result is not None


def test_pause_then_continue_resumes_from_the_bookmark(plugin):
    """The actual end-to-end behavior a user cares about: pause mid-
    story, then continue, and it picks up where it left off - proving
    pause and the existing continue/bookmark machinery compose
    correctly, not just that each works in isolation."""
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    plugin.settings['last_content'] = candidate
    key = CommonReadingPipeline._progress_key(candidate)
    plugin.settings['progress'][key] = 3
    plugin.is_reading = True

    plugin._handle_pause()
    assert plugin.is_reading is False
    # bookmark from before the pause is untouched by pausing itself
    assert plugin.settings['progress'][key] == 3

    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "continue", "conf": 0.95, "entities": {}})
    plugin._read_content = MagicMock()

    plugin.match(["continue"], "en-us", make_message())

    plugin._read_content.assert_called_once_with(candidate, 3)


def test_low_confidence_confirmation_speaks_with_wait_before_asking(plugin):
    """Real bug fixed here: 'that_would_be' MUST be spoken with
    wait=True before ask_yesno() opens its listening window - without
    it, the window opens (and can time out) while the confirmation
    question is still queued/playing, not synced to when the user
    could actually have heard it and started answering. Reported
    symptom: saying "yes" immediately after "is it that one?" landed
    in fallback_unknown instead of being caught here."""
    _wire_common_mocks(plugin)
    plugin._search_providers = MagicMock(return_value=[
        {"skill_id": "prov.a", "content_id": "x", "title": "Cinderella", "confidence": 0.4},
    ])
    plugin._announce_and_read = MagicMock()
    call_order = []
    plugin.speak_dialog.side_effect = lambda *a, **kw: call_order.append(("speak", a, kw))
    plugin.ask_yesno.side_effect = lambda *a, **kw: call_order.append(("ask", a, kw)) or "yes"

    plugin._search_and_read("cinderella")

    speak_call = next(c for c in call_order if c[0] == "speak")
    assert speak_call[1][0] == "that_would_be"
    assert speak_call[2].get("wait") is True
    # and it must have happened BEFORE ask_yesno, not just with wait=True
    assert call_order.index(speak_call) < next(i for i, c in enumerate(call_order) if c[0] == "ask")


def test_low_confidence_confirmation_yes_reads_the_candidate(plugin):
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "x", "title": "Cinderella", "confidence": 0.4}
    plugin._search_providers = MagicMock(return_value=[candidate])
    plugin._announce_and_read = MagicMock()
    plugin.ask_yesno.return_value = "yes"

    plugin._search_and_read("cinderella")

    plugin._announce_and_read.assert_called_once_with(candidate, bookmark=0)


def test_low_confidence_confirmation_no_declines_without_reading(plugin):
    _wire_common_mocks(plugin)
    plugin._search_providers = MagicMock(return_value=[
        {"skill_id": "prov.a", "content_id": "x", "title": "Cinderella", "confidence": 0.4},
    ])
    plugin._announce_and_read = MagicMock()
    plugin.ask_yesno.return_value = "no"

    plugin._search_and_read("cinderella")

    plugin._announce_and_read.assert_not_called()
    assert any(c[0][0] == "no_content" for c in plugin.speak_dialog.call_args_list)


def test_high_confidence_skips_confirmation_entirely(plugin):
    """>= CONFIDENCE_THRESHOLD reads immediately - no 'is it that one?'
    round trip at all."""
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "x", "title": "Cinderella", "confidence": 0.95}
    plugin._search_providers = MagicMock(return_value=[candidate])
    plugin._announce_and_read = MagicMock()

    plugin._search_and_read("cinderella")

    plugin.ask_yesno.assert_not_called()
    plugin._announce_and_read.assert_called_once_with(candidate, bookmark=0)
