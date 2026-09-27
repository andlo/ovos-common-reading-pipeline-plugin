"""Tests for match() dispatch logic and the underlying _search_and_read /
_handle_continue / stop behavior. The padacioso IntentContainer itself is
mocked here (its real matching behavior across all 8 languages is
verified separately, live, against the actual bundled *.intent files -
see scripts/build_padacioso_intents.py's docstring) so these tests focus
on what match() does once it has a result, and on what each handler does
with the dispatch ovos-core sends it."""
from unittest.mock import MagicMock

from conftest import (
    CommonReadingPipeline,
    ContentFetchError,
    dispatch_message,
    entry,
    module,
    session_message,
)


def _wire_common_mocks(plugin):
    plugin.speak = MagicMock()
    plugin.speak_dialog = MagicMock()
    plugin.ask_yesno = MagicMock(return_value="yes")


def _fake_container(result):
    container = MagicMock()
    container.calc_intent = MagicMock(return_value=result)
    return container


def _emitted(plugin, msg_type):
    return [c.args[0] for c in plugin.bus.emit.call_args_list if c.args[0].msg_type == msg_type]


def test_match_returns_the_read_content_match_without_doing_the_work(plugin):
    """match() only classifies: the search, the speech and the story all
    wait for ovos-core's dispatch to the handler."""
    _wire_common_mocks(plugin)
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_content", "conf": 0.9, "entities": {"title": "cinderella"}})
    plugin._search_and_read = MagicMock()

    result = plugin.match(["tell me a story about cinderella"], "en-us", session_message())

    assert result is not None
    assert result.skill_id == plugin.skill_id
    assert result.match_type == f"{plugin.skill_id}:read_content"
    assert result.utterance == "tell me a story about cinderella"
    plugin._search_and_read.assert_not_called()
    plugin.speak.assert_not_called()
    plugin.speak_dialog.assert_not_called()
    plugin.bus.emit.assert_not_called()


def test_match_data_is_never_none_real_crash_found_via_live_testing(plugin):
    """IntentHandlerMatch.match_data defaults to None if not given
    explicitly - ovos-core's own handle_utterance does
    data.update(match.match_data) on it unconditionally, and None
    isn't iterable, so a bare IntentHandlerMatch(...) without
    match_data= crashes ovos-core with a TypeError, silently
    discarding the match and falling through to common-query/fallback
    instead. Confirmed via a live screenshot showing exactly this
    traceback. This test would have caught it - asserts match_data is
    always a dict (the actual entities), never None, regardless of
    which branch of match() produced the result."""
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_content", "conf": 0.9, "entities": {"title": "cinderella"}})

    result = plugin.match(["tell me a story about cinderella"], "en-us", session_message())

    assert result.match_data is not None
    assert isinstance(result.match_data, dict)
    assert result.match_data == {"title": "cinderella"}


def test_match_data_is_a_dict_even_without_entities(plugin):
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_any_story", "conf": 1.0, "entities": None})

    result = plugin.match(["tell me a story"], "en-us", session_message())

    assert result.match_type == f"{plugin.skill_id}:read_any_story"
    assert result.match_data == {}


def test_read_content_handler_searches_for_the_title(plugin):
    plugin._search_and_read = MagicMock()
    message = dispatch_message(data={"title": "cinderella"})

    plugin.handle_read_content(message)

    plugin._search_and_read.assert_called_once_with(message, "cinderella")


def test_read_by_collection_handler_passes_the_collection_hint(plugin):
    plugin._search_and_read = MagicMock()
    message = dispatch_message(intent="read_by_collection", data={"collection": "grimm"})

    plugin.handle_read_by_collection(message)

    plugin._search_and_read.assert_called_once_with(message, None, collection_hint="grimm")


def test_read_by_type_handler_passes_the_content_type(plugin):
    plugin._search_and_read = MagicMock()
    message = dispatch_message(intent="read_by_type", data={"content_type": "horoscope"})

    plugin.handle_read_by_type(message)

    plugin._search_and_read.assert_called_once_with(message, None, content_type="horoscope")


def test_read_any_story_handler_searches_with_no_phrase(plugin):
    """"Tell me a story": no title, so the providers pick one themselves."""
    plugin._search_and_read = MagicMock()
    message = dispatch_message(intent="read_any_story")

    plugin.handle_read_any_story(message)

    plugin._search_and_read.assert_called_once_with(message, None, content_type="story")


def test_match_below_confidence_threshold_returns_none(plugin):
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "read_content", "conf": 0.1, "entities": {"title": "cinderella"}})

    result = plugin.match(["mumble mumble cinderella"], "en-us", session_message())

    assert result is None


def test_match_no_intent_name_returns_none(plugin):
    plugin._intent_containers["en-us"] = _fake_container({"name": None, "entities": {}})

    result = plugin.match(["what is the weather"], "en-us", session_message())

    assert result is None


def test_match_continue_with_nothing_in_progress_declines(plugin):
    """The key improvement over the old skill-based 'continue.intent':
    if nothing is actually in progress, match() returns None instead of
    claiming the utterance and speaking a 'nothing to continue' dialog -
    letting a later pipeline stage try instead."""
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "continue", "conf": 0.95, "entities": {}})

    result = plugin.match(["continue"], "en-us", session_message())

    assert result is None


def test_match_continue_with_something_in_progress_claims_it(plugin):
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    plugin.settings["sessions"] = {"default": {"last_content": candidate}}
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "continue", "conf": 0.95, "entities": {}})

    result = plugin.match(["continue"], "en-us", session_message())

    assert result.match_type == f"{plugin.skill_id}:continue"


def test_continue_handler_resumes_from_the_bookmark(plugin):
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    plugin.settings["sessions"] = {"default": {
        "last_content": candidate, "progress": {CommonReadingPipeline._progress_key(candidate): 7}}}
    plugin._read_in_background = MagicMock()
    message = dispatch_message(intent="continue")

    plugin.handle_continue(message)

    plugin.speak_dialog.assert_called_once_with('continue', data={"title": "Cinderella"}, wait=True)
    (sent, reading, bookmark), _ = plugin._read_in_background.call_args
    assert (sent, reading.candidate, bookmark) == (message, candidate, 7)


def test_continue_while_already_reading_does_not_start_a_second_reader(plugin):
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    plugin._begin_reading(session_message(), candidate)
    plugin._read_in_background = MagicMock()

    plugin.handle_continue(dispatch_message(intent="continue"))

    plugin._read_in_background.assert_not_called()
    plugin.speak_dialog.assert_not_called()


def test_stop_while_reading_speaks_and_returns_true(plugin):
    _wire_common_mocks(plugin)
    plugin._begin_reading(None, {"skill_id": "prov.a", "content_id": "x", "title": "X"})

    result = plugin.stop()

    assert result is True
    assert plugin._is_reading("default") is False
    # wait=True is required, not optional - see the comment on
    # stop_session() in __init__.py. Without it, this confirmation was
    # silently getting flushed by OVOS core's own global stop handling
    # before ever reaching the speaker - a real bug found in manual testing.
    plugin.speak_dialog.assert_called_once_with('stop_reading', wait=True)


def test_stop_while_not_reading_returns_false(plugin):
    _wire_common_mocks(plugin)

    assert plugin.stop() is False
    plugin.speak_dialog.assert_not_called()


def test_match_pause_with_nothing_being_read_declines(plugin):
    """Same decline-rather-than-claim reasoning as 'continue': saying
    'pause' when nothing is actually being read should not be silently
    swallowed by this pipeline - let a later stage try instead."""
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "pause", "conf": 0.95, "entities": {}})

    result = plugin.match(["pause"], "en-us", session_message())

    assert result is None


def test_pause_while_reading_stops_and_speaks_paused_dialog(plugin):
    """The actual fix: 'pause' is matched by this pipeline's OWN intent
    parser, not left to OVOS's global stop vocabulary (which may or may
    not treat 'pause' as a synonym for 'stop') - so it reliably works
    regardless of core-level vocabulary."""
    _wire_common_mocks(plugin)
    plugin._begin_reading(session_message(), {"skill_id": "prov.a", "content_id": "x", "title": "X"})
    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "pause", "conf": 0.95, "entities": {}})

    result = plugin.match(["pause"], "en-us", session_message())
    assert result.match_type == f"{plugin.skill_id}:pause"
    plugin.handle_pause(dispatch_message(intent="pause"))

    assert plugin._is_reading("default") is False
    # wait=True is required, not optional - same reasoning/bug as stop()
    plugin.speak_dialog.assert_called_once_with('paused', wait=True)


def test_pause_then_continue_resumes_from_the_bookmark(plugin):
    """The actual end-to-end behavior a user cares about: pause mid-
    story, then continue, and it picks up where it left off - proving
    pause and the existing continue/bookmark machinery compose
    correctly, not just that each works in isolation."""
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    key = CommonReadingPipeline._progress_key(candidate)
    plugin._begin_reading(session_message(), candidate)
    entry(plugin)["progress"][key] = 3

    plugin.handle_pause(dispatch_message(intent="pause"))
    assert plugin._is_reading("default") is False
    # bookmark from before the pause is untouched by pausing itself
    assert entry(plugin)["progress"][key] == 3

    plugin._intent_containers["en-us"] = _fake_container(
        {"name": "continue", "conf": 0.95, "entities": {}})
    plugin._read_in_background = MagicMock()

    assert plugin.match(["continue"], "en-us", session_message()) is not None
    message = dispatch_message(intent="continue")
    plugin.handle_continue(message)

    (sent, reading, bookmark), _ = plugin._read_in_background.call_args
    assert (sent, reading.candidate, bookmark) == (message, candidate, 3)


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

    plugin._search_and_read(dispatch_message(), "cinderella")

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
    message = dispatch_message()

    plugin._search_and_read(message, "cinderella")

    plugin._announce_and_read.assert_called_once_with(message, candidate, bookmark=0)


def test_low_confidence_confirmation_no_declines_without_reading(plugin):
    _wire_common_mocks(plugin)
    plugin._search_providers = MagicMock(return_value=[
        {"skill_id": "prov.a", "content_id": "x", "title": "Cinderella", "confidence": 0.4},
    ])
    plugin._announce_and_read = MagicMock()
    plugin.ask_yesno.return_value = "no"

    plugin._search_and_read(dispatch_message(), "cinderella")

    plugin._announce_and_read.assert_not_called()
    assert any(c[0][0] == "no_content" for c in plugin.speak_dialog.call_args_list)


def test_high_confidence_skips_confirmation_entirely(plugin):
    """>= CONFIDENCE_THRESHOLD reads immediately - no 'is it that one?'
    round trip at all."""
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "x", "title": "Cinderella", "confidence": 0.95}
    plugin._search_providers = MagicMock(return_value=[candidate])
    plugin._announce_and_read = MagicMock()
    message = dispatch_message()

    plugin._search_and_read(message, "cinderella")

    plugin.ask_yesno.assert_not_called()
    plugin._announce_and_read.assert_called_once_with(message, candidate, bookmark=0)


def test_a_random_story_at_the_providers_confidence_is_read_without_asking(plugin):
    """The providers answer "tell me a story" (no phrase) with one random
    story at confidence 0.9 - above CONFIDENCE_THRESHOLD, so no yes/no."""
    _wire_common_mocks(plugin)
    candidate = {"skill_id": "prov.a", "content_id": "x", "title": "Rapunzel", "confidence": 0.9}
    plugin._search_providers = MagicMock(return_value=[candidate])
    plugin._announce_and_read = MagicMock()
    message = dispatch_message(intent="read_any_story")

    plugin.handle_read_any_story(message)

    plugin._search_providers.assert_called_once_with(message, None, collection_hint=None, content_type="story")
    plugin.ask_yesno.assert_not_called()
    plugin._announce_and_read.assert_called_once_with(message, candidate, bookmark=0)


# --- _activate()/_deactivate() - the real "stop doesn't interrupt reading" bug fix ---
#
# Confirmed via a live screenshot: saying "stop" mid-story did nothing at
# all, eventually forcing a full ovos-core restart. Root cause: OVOS's
# global stop pipeline determines which skill(s) to call .stop() on via
# the session's active_skills list, and this plugin was never being
# added to it (no ConversationalSkill inheritance, so no activate()/
# deactivate() at all) - so stop() was never even being invoked through
# the normal path, regardless of the reading loop's own (correct)
# stop checks.

def test_activate_emits_intent_service_skills_activate(plugin):
    plugin._activate()
    plugin.bus.emit.assert_called_once()
    sent = plugin.bus.emit.call_args[0][0]
    assert sent.msg_type == "intent.service.skills.activate"
    assert sent.data["skill_id"] == plugin.skill_id


def test_deactivate_emits_intent_service_skills_deactivate(plugin):
    plugin._deactivate()
    plugin.bus.emit.assert_called_once()
    sent = plugin.bus.emit.call_args[0][0]
    assert sent.msg_type == "intent.service.skills.deactivate"
    assert sent.data["skill_id"] == plugin.skill_id


def test_activation_lands_on_the_session_that_asked(plugin):
    plugin._activate(session_message("alice"))
    plugin._deactivate(session_message("alice"))

    for sent in (_emitted(plugin, "intent.service.skills.activate")
                 + _emitted(plugin, "intent.service.skills.deactivate")):
        assert sent.context["session"]["session_id"] == "alice"


def test_a_stop_during_the_announcement_stops_the_story(plugin):
    """The story is registered before "Here it is: ..." is spoken, so a stop
    said over the announcement finds it, and the story never starts."""
    _wire_common_mocks(plugin)
    plugin._read_content = MagicMock()

    def stop_while_announcing(key, **kw):
        if key == 'i_know_that':
            assert plugin.can_stop(session_message()) is True
            assert plugin.stop_session(module.SessionManager.get(session_message())) is True

    plugin.speak_dialog.side_effect = stop_while_announcing

    plugin._announce_and_read(dispatch_message(), {"skill_id": "p", "content_id": "c", "title": "T"}, 0)

    plugin._read_content.assert_not_called()
    assert plugin._is_reading("default") is False


def test_start_reading_activates_before_reading(plugin):
    """The core fix: without this, OVOS has no way to know this plugin
    is the thing currently speaking when 'stop' is said."""
    _wire_common_mocks(plugin)
    plugin._fetch_content = MagicMock(return_value=["One sentence."])

    reading = plugin._start_reading(session_message(), {"skill_id": "p", "content_id": "c", "title": "Test"}, 0)
    reading.thread.join(5)

    assert len(_emitted(plugin, "intent.service.skills.activate")) == 1


def test_read_content_deactivates_when_finished_reading(plugin):
    _wire_common_mocks(plugin)
    plugin._fetch_content = MagicMock(return_value=["One sentence."])
    message = session_message()
    reading = plugin._begin_reading(message, {"skill_id": "p", "content_id": "c", "title": "Test", "source": "t"})

    plugin._read_content(message, reading, 0)

    assert len(_emitted(plugin, "intent.service.skills.deactivate")) == 1


def test_read_content_deactivates_on_fetch_error(plugin):
    _wire_common_mocks(plugin)
    plugin._fetch_content = MagicMock(side_effect=ContentFetchError("boom"))
    message = session_message()
    reading = plugin._begin_reading(message, {"skill_id": "p", "content_id": "c", "title": "Test"})

    plugin._read_content(message, reading, 0)

    assert len(_emitted(plugin, "intent.service.skills.deactivate")) == 1


def test_stop_deactivates(plugin):
    _wire_common_mocks(plugin)
    plugin._begin_reading(None, {"skill_id": "p", "content_id": "c", "title": "Test"})

    plugin.stop()

    assert len(_emitted(plugin, "intent.service.skills.deactivate")) == 1


def test_stop_sets_the_stop_flag_before_speaking_the_confirmation(plugin):
    """Real race condition found via live testing: with the flag set
    AFTER speak_dialog('stop_reading', wait=True) instead of before,
    there's a window where the reading loop's own thread (blocked in its
    own wait=True call for whatever sentence is currently playing) wakes
    up, sees it may go on (stop's own speak_dialog call hasn't returned
    yet - it's queued behind that same sentence), and queues ONE MORE
    sentence before stop gets a chance to set the flag. Reported symptom:
    reading continued for one more sentence after saying "stop". This
    test asserts the ORDER directly via a side_effect that checks the
    flag at the moment speak_dialog is actually called - it must already
    be set by then."""
    _wire_common_mocks(plugin)
    reading = plugin._begin_reading(session_message("alice"), {"skill_id": "p", "content_id": "c", "title": "T"})
    observed = {}

    def fake_speak_dialog(*a, **kw):
        observed["stopped_at_speak_time"] = reading.stopped.is_set()
        observed["reading_at_speak_time"] = plugin._is_reading("alice")

    plugin.speak_dialog.side_effect = fake_speak_dialog

    plugin._handle_session_stop(session_message("alice", "mycroft.stop"))

    assert observed == {"stopped_at_speak_time": True, "reading_at_speak_time": False}


def test_pause_deactivates(plugin):
    _wire_common_mocks(plugin)
    plugin._begin_reading(session_message(), {"skill_id": "p", "content_id": "c", "title": "Test"})

    plugin.handle_pause(dispatch_message(intent="pause"))

    assert len(_emitted(plugin, "intent.service.skills.deactivate")) == 1


# --- can_stop() - required override, or OVOSSkill.can_stop() raises NotImplementedError ---
#
# Confirmed via a live screenshot: once _activate() started correctly
# registering this plugin as active while reading, OVOS's stop pipeline
# began actually querying it via can_stop() as part of the normal
# stop-ack flow - and without this override, that raised
# NotImplementedError on every single stop/pause.

def test_can_stop_true_while_reading(plugin):
    plugin._begin_reading(session_message(), {"skill_id": "p", "content_id": "c", "title": "T"})
    assert plugin.can_stop(session_message()) is True


def test_can_stop_false_when_not_reading(plugin):
    assert plugin.can_stop(session_message()) is False
