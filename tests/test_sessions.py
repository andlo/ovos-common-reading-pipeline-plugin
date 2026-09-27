"""Per-session reading state: on a HiveMind hub every user shares one
instance of this plugin, so each session's story, stop flag, bookmark and
"continue" must be its own. Everything here used to be global
(is_reading, settings['last_content'], settings['progress']): one
visitor's "stop" ended another's story and "continue" resumed whatever
anyone had read last."""
import threading
import time
from unittest.mock import MagicMock

import pytest

from conftest import (
    CommonReadingPipeline,
    dispatch_message,
    entry,
    module,
    session_message,
)

CINDERELLA = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella", "source": "s"}
RAPUNZEL = {"skill_id": "prov.a", "content_id": "Rapunzel", "title": "Rapunzel", "source": "s"}


def _wire(plugin):
    plugin.speak = MagicMock()
    plugin.speak_dialog = MagicMock()
    return plugin


def _fake_container(name):
    container = MagicMock()
    container.calc_intent = MagicMock(return_value={"name": name, "conf": 0.95, "entities": {}})
    return container


def _stop_from(plugin, session_id, msg_type="mycroft.stop"):
    """Deliver a stop the way ovos-workshop does: _handle_session_stop
    with the stop message of `session_id` ("mycroft.stop" is the global
    stop's topic, "<skill_id>.stop" the targeted one's)."""
    message = session_message(session_id, msg_type)
    plugin._handle_session_stop(message)
    return [c.args[0] for c in plugin.bus.emit.call_args_list
            if c.args[0].msg_type == f"{plugin.skill_id}.stop.response"][-1]


def test_a_stop_from_one_session_leaves_the_other_reading(plugin):
    _wire(plugin)
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    response = _stop_from(plugin, "alice", f"{plugin.skill_id}.stop")

    assert response.data["result"] is True
    assert plugin._is_reading("alice") is False
    assert plugin._is_reading("bob") is True
    # the confirmation goes to the session that said stop
    plugin.speak_dialog.assert_called_once_with('stop_reading', wait=True)


def test_a_global_stop_from_an_idle_session_stops_nobody(plugin):
    """Carol says "stop" with nothing of hers playing: ovos-core's stop
    pipeline finds nothing to target and broadcasts the global stop, which
    ovos-workshop turns into stop_session(carol) and then stop(). Neither
    may end Alice's or Bob's story."""
    _wire(plugin)
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    response = _stop_from(plugin, "carol")

    assert response.data["result"] is False
    assert plugin._is_reading("alice") and plugin._is_reading("bob")
    plugin.speak_dialog.assert_not_called()


def test_a_global_stop_stops_the_session_that_said_it(plugin):
    _wire(plugin)
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    _stop_from(plugin, "bob")

    assert plugin._is_reading("alice") is True
    assert plugin._is_reading("bob") is False


def test_a_stop_naming_no_session_stops_every_story(plugin):
    """stop() is the fallback for a stop that names no session at all - a
    bare "mycroft.stop" on the bus, or ovos-core shutting the plugin down."""
    _wire(plugin)
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    plugin._handle_session_stop(module.Message("mycroft.stop"))

    assert not plugin._is_reading("alice") and not plugin._is_reading("bob")
    assert plugin.speak_dialog.call_count == 2  # each session hears its own confirmation


def test_stop_during_shutdown_stops_every_story(plugin):
    _wire(plugin)
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    assert plugin.stop() is True
    assert not plugin._is_reading("alice") and not plugin._is_reading("bob")


def test_the_global_stop_confirms_to_each_session_on_its_own_route(plugin, monkeypatch):
    """stop() speaks one confirmation per stopped story, forwarded from the
    request that started it, so each reaches its own client."""
    plugin.speak_dialog = MagicMock(side_effect=lambda *a, **kw: routes.append(
        module.dig_for_message().context["session"]["session_id"]))
    routes = []
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    plugin.stop()

    assert sorted(routes) == ["alice", "bob"]


def test_can_stop_only_answers_for_the_asking_session(plugin):
    plugin._begin_reading(session_message("alice"), CINDERELLA)

    assert plugin.can_stop(session_message("alice")) is True
    assert plugin.can_stop(session_message("bob")) is False


def test_pause_only_pauses_the_session_that_said_it(plugin):
    _wire(plugin)
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._begin_reading(session_message("bob"), RAPUNZEL)

    plugin.handle_pause(dispatch_message("alice", intent="pause"))

    assert plugin._is_reading("alice") is False
    assert plugin._is_reading("bob") is True


def test_pause_is_declined_for_a_session_that_is_not_reading(plugin):
    plugin._begin_reading(session_message("alice"), CINDERELLA)
    plugin._intent_containers["en-us"] = _fake_container("pause")

    assert plugin.match(["pause"], "en-us", session_message("alice")) is not None
    assert plugin.match(["pause"], "en-us", session_message("bob")) is None


def test_continue_resumes_each_sessions_own_story(plugin):
    _wire(plugin)
    plugin.settings["sessions"] = {
        "alice": {"last_content": CINDERELLA, "progress": {CommonReadingPipeline._progress_key(CINDERELLA): 4}},
        "bob": {"last_content": RAPUNZEL, "progress": {CommonReadingPipeline._progress_key(RAPUNZEL): 9}},
    }
    plugin._read_in_background = MagicMock()
    alice, bob = dispatch_message("alice", intent="continue"), dispatch_message("bob", intent="continue")

    plugin.handle_continue(alice)
    plugin.handle_continue(bob)

    resumed = [(c.args[0], c.args[1].candidate, c.args[2]) for c in plugin._read_in_background.call_args_list]
    assert resumed == [(alice, CINDERELLA, 4), (bob, RAPUNZEL, 9)]


def test_continue_fetches_in_the_language_the_story_was_found_in(plugin):
    """Alice found a French story, paused it, and says "continue" in
    English: the text is still asked for in French. A French-only provider
    answers nothing in another language."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Il était une fois."])
    french = dispatch_message("alice", lang="fr-FR")
    plugin._begin_reading(french, CINDERELLA)
    plugin.handle_pause(dispatch_message("alice", intent="pause", lang="fr-FR"))

    started = []
    read_in_background = plugin._read_in_background
    plugin._read_in_background = lambda *a, **kw: started.append(read_in_background(*a, **kw))

    plugin.handle_continue(dispatch_message("alice", intent="continue", lang="en-US"))
    started[0].thread.join(5)

    assert plugin._fetch_content.call_args.kwargs["lang"] == "fr-FR"


def test_continue_is_declined_for_a_session_with_nothing_to_resume(plugin):
    """Alice paused a story; Bob never read anything. "continue" from Bob
    is not ours to claim."""
    plugin.settings["sessions"] = {"alice": {"last_content": CINDERELLA}}
    plugin._intent_containers["en-us"] = _fake_container("continue")

    assert plugin.match(["continue"], "en-us", session_message("alice")) is not None
    assert plugin.match(["continue"], "en-us", session_message("bob")) is None


def test_two_sessions_read_at_once_and_one_stops(plugin):
    """Two reader threads, one per session, both mid-story; Alice stops.
    Bob's story reads to the end, Alice's stops at a sentence boundary, and
    every sentence went to the session whose story it is."""
    heard = {"alice": [], "bob": []}
    alice_started = threading.Event()

    def speak(sentence, wait=False, **kw):
        session = module.dig_for_message().context["session"]["session_id"]
        heard[session].append(sentence)
        if session == "alice":
            alice_started.set()
        time.sleep(0.01)

    plugin.speak = speak
    plugin.speak_dialog = MagicMock()
    story = " ".join(f"Sentence {i} ends here." for i in range(1, 41))
    plugin._fetch_content = MagicMock(return_value=[story])

    alice = plugin._start_reading(dispatch_message("alice"), CINDERELLA, 0)
    bob = plugin._start_reading(dispatch_message("bob"), RAPUNZEL, 0)
    assert alice_started.wait(5)
    _stop_from(plugin, "alice", f"{plugin.skill_id}.stop")
    alice.thread.join(5)
    bob.thread.join(5)

    assert len(heard["bob"]) == 40  # read to the end
    assert 1 <= len(heard["alice"]) < 40  # stopped part way
    assert heard["bob"] == [f"Sentence {i} ends here." for i in range(1, 41)]
    assert heard["alice"] == heard["bob"][:len(heard["alice"])]
    # Alice keeps her bookmark, exactly where she stopped; Bob's story is done
    key = CommonReadingPipeline._progress_key(CINDERELLA)
    assert entry(plugin, "alice")["progress"][key] == len(heard["alice"])
    assert plugin._last_content("alice") == CINDERELLA
    assert plugin._last_content("bob") is None


def test_flat_settings_from_before_sessions_move_to_the_default_session(plugin):
    """A local device paused a story on an older version: its bookmark and
    last_content sat at the top of the settings. They now belong to the
    default session, so "continue" there picks up where it left off."""
    key = CommonReadingPipeline._progress_key(CINDERELLA)
    plugin._settings.update({"last_content": CINDERELLA, "progress": {key: 12},
                             "progress_splitter": {key: 2}, "__mycroft_skill_firstrun": False})

    plugin._migrate_flat_settings()

    assert "last_content" not in plugin.settings and "progress" not in plugin.settings
    assert entry(plugin)["last_content"] == CINDERELLA
    assert entry(plugin)["progress"] == {key: 12}
    assert entry(plugin)["progress_splitter"] == {key: 2}
    assert plugin.settings["__mycroft_skill_firstrun"] is False  # everything else untouched
    # and nobody else inherits it
    assert plugin._last_content("alice") is None


def test_migrating_keeps_what_the_default_session_already_has(plugin):
    key = CommonReadingPipeline._progress_key(CINDERELLA)
    plugin._settings.update({"last_content": RAPUNZEL, "progress": {key: 1},
                             "sessions": {"default": {"last_content": CINDERELLA, "progress": {key: 30}}}})

    plugin._migrate_flat_settings()

    assert entry(plugin)["last_content"] == CINDERELLA
    assert entry(plugin)["progress"][key] == 30


def test_migrating_an_empty_flat_layout_leaves_nothing_behind(plugin):
    plugin._settings.update({"last_content": None, "progress": {}})

    plugin._migrate_flat_settings()

    assert plugin.settings == {}


def test_migrated_settings_are_written_to_disk(plugin):
    store = MagicMock()
    plugin._settings = type("Settings", (dict,), {"store": store})(last_content=CINDERELLA)

    plugin._migrate_flat_settings()

    store.assert_called_once()


def test_old_sessions_are_forgotten_beyond_the_limit(plugin, monkeypatch):
    monkeypatch.setattr(module, "MAX_REMEMBERED_SESSIONS", 3)
    plugin.settings["sessions"] = {"default": {"last_content": CINDERELLA, "touched": 0}}
    for i, sid in enumerate(["s1", "s2", "s3", "s4"]):
        with plugin._state_lock:
            plugin._session_entry(sid, create=True)["touched"] = i + 1
    plugin._begin_reading(session_message("s1"), RAPUNZEL)  # reading: never forgotten

    sessions = set(plugin.settings["sessions"])

    assert "default" in sessions and "s1" in sessions
    assert len(sessions) == 3
    assert "s2" not in sessions  # the least recently used


@pytest.mark.parametrize("carrier", [None, "not-a-dict"])
def test_a_message_without_a_usable_session_counts_as_the_default_session(carrier):
    context = {} if carrier is None else {"session": carrier}
    assert module._session_id(module.Message("x", {}, context)) == "default"
