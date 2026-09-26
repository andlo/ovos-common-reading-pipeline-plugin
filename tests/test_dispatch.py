"""A real CommonReadingPipeline on a FakeBus, driven the way ovos-core
drives it: match() for the classification, then a dispatch on
"<skill_id>:<intent>" whose handler must report back with
mycroft.skill.handler.complete - the done-signal ovos-core's dispatcher
waits for before it ends the turn with ovos.utterance.handled.

A fake provider answers the search and the fetch; a fake audio service
answers every "speak" with recognizer_loop:audio_output_start/_end on the
same session, the way ovos-audio (or a HiveMind client that reports its
playback) does, so speak(wait=True) paces the story as it would live."""
import inspect
import threading
import time
from importlib.metadata import version

import pytest
from ovos_bus_client.session import SessionManager
from ovos_utils.fakebus import FakeBus

from conftest import (
    COMMON_READING_FETCH_CONTENT,
    COMMON_READING_FETCH_CONTENT_RESPONSE,
    COMMON_READING_SEARCH,
    COMMON_READING_SEARCH_RESPONSE,
    CommonReadingPipeline,
    module,
    session_message,
)

PROVIDER = "ovos-skill-fake-tales.test"
SENTENCES = [f"This is sentence {i} of the story." for i in range(1, 21)]
PLAYBACK = 0.03  # seconds each fake "speak" takes to play


class Recorder:
    def __init__(self, bus, *msg_types):
        self.messages = []
        self.lock = threading.Lock()
        for msg_type in msg_types:
            bus.on(msg_type, self.add)

    def add(self, message):
        with self.lock:
            self.messages.append((time.monotonic(), message))

    def of(self, msg_type):
        with self.lock:
            return [(t, m) for t, m in self.messages if m.msg_type == msg_type]


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    real_sleep = time.sleep
    # the 2 s search window is a plain sleep; a FakeBus provider answers at once
    monkeypatch.setattr(module.time, "sleep", lambda s: real_sleep(min(s, 0.05)))
    bus = FakeBus()
    monkeypatch.setattr(SessionManager, "bus", None)
    SessionManager.connect_to_bus(bus)

    def audio(message):
        def play():
            bus.emit(message.forward("recognizer_loop:audio_output_start"))
            real_sleep(PLAYBACK)
            bus.emit(message.forward("recognizer_loop:audio_output_end"))
        # speak() starts listening for the end just after it emits; an end
        # that beats it is missed and costs the full 15 s wait (as it would
        # live), so give it a head start on a loaded machine
        threading.Timer(0.02, play).start()

    def search(message):
        bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {
            "skill_id": PROVIDER, "content_id": "rapunzel", "title": "Rapunzel",
            "author": "Andrew Lang", "source": "Project Gutenberg", "confidence": 0.95}))

    def fetch(message):
        bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": [" ".join(SENTENCES)]}))

    bus.on("speak", audio)
    bus.on(COMMON_READING_SEARCH, search)
    bus.on(f"{COMMON_READING_FETCH_CONTENT}.{PROVIDER}", fetch)
    plugin = CommonReadingPipeline(bus=bus)
    yield plugin, bus
    plugin.stop()


def _dispatch(plugin, bus, session_id, intent, data=None, lang="en-US"):
    """What ovos-core does with a Match: reply-derive the dispatch from the
    utterance (so it routes back to the client), merge in match_data,
    stamp skill_id and emit on "<skill_id>:<intent>"."""
    utterance = session_message(session_id, "recognizer_loop:utterance",
                                {"utterances": ["..."], "lang": lang}, lang=lang,
                                source="hive.client", destination="skills")
    dispatch = utterance.reply(f"{plugin.skill_id}:{intent}", dict(utterance.data, **(data or {}),
                                                                  utterance="...", lang=lang))
    dispatch.context["skill_id"] = plugin.skill_id
    bus.emit(dispatch)  # FakeBus runs the handler right here, like the dispatcher's emit
    return dispatch


def test_every_intent_has_a_dispatch_handler(live):
    plugin, bus = live
    for name in module.INTENT_HANDLERS:
        assert bus.ee.listeners(f"{plugin.skill_id}:{name}"), name


def test_match_is_fast_and_does_nothing_but_classify(live):
    plugin, bus = live
    plugin._get_intent_container("en-US")  # trained (the plugin warms this up at start)
    sent = Recorder(bus, "message")
    emitted = []
    original_emit = bus.emit
    bus.emit = lambda message: emitted.append(message) or original_emit(message)

    started = time.monotonic()
    result = plugin.match(["tell me the story rapunzel"], "en-US", session_message("alice"))
    elapsed = time.monotonic() - started

    assert result.match_type == f"{plugin.skill_id}:read_content"
    assert result.match_data == {"title": "rapunzel"}
    assert emitted == [] and sent.messages == []
    # padacioso 1.x (the newest non-pre-release on PyPI) starts a process
    # pool for every calc_intent and takes seconds whatever the plugin does
    if int(version("padacioso").split(".")[0]) >= 2:
        assert elapsed < 0.5


def test_the_handler_reports_the_done_signal_the_dispatcher_needs(live):
    """ovos-core's dispatcher resolves the dispatch from
    mycroft.skill.handler.complete by session, context["skill_id"] and
    data["intent_name"]; all three must match the dispatch."""
    plugin, bus = live
    signals = Recorder(bus, "mycroft.skill.handler.start", "mycroft.skill.handler.complete")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})

    (_, start), = signals.of("mycroft.skill.handler.start")
    (_, complete), = signals.of("mycroft.skill.handler.complete")
    # ovos-workshop < 9 has no intent_name on add_event; its done-signal
    # names the skill only, which the dispatcher accepts as well
    names_intent = "intent_name" in inspect.signature(plugin.add_event).parameters
    for signal in (start, complete):
        assert signal.context["skill_id"] == plugin.skill_id
        assert signal.context["session"]["session_id"] == "alice"
        if names_intent:
            assert signal.data["intent_name"] == "read_content"


def test_the_handler_returns_before_the_story_ends(live):
    """The turn ends when the handler returns. It must return once the
    story has started, not when it is over - or "stop" and "pause" cannot
    reach this plugin while it reads."""
    plugin, bus = live
    signals = Recorder(bus, "mycroft.skill.handler.complete", "speak")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    reading = plugin._readings["alice"]
    completed_at = signals.of("mycroft.skill.handler.complete")[0][0]
    assert reading.thread.is_alive()

    reading.thread.join(60)
    story = [(t, m) for t, m in signals.of("speak") if m.data["utterance"] in SENTENCES]
    assert [m.data["utterance"] for _, m in story] == SENTENCES
    assert sum(1 for t, _ in story if t > completed_at) >= len(SENTENCES) - 2


def test_story_sentences_carry_the_originating_session_and_route(live):
    """speak() takes its context from the Message it finds on the stack
    (dig_for_message). The reader thread has the dispatch as a parameter,
    so every sentence goes out forwarded from it: the session a HiveMind
    hub routes on, the source/destination, and the session's language."""
    plugin, bus = live
    speaks = Recorder(bus, "speak")

    dispatch = _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"}, lang="fr-FR")
    plugin._readings["alice"].thread.join(60)

    story = [m for _, m in speaks.of("speak") if m.data["utterance"] in SENTENCES]
    assert len(story) == len(SENTENCES)
    for message in story:
        assert message.context["session"]["session_id"] == "alice"
        assert message.context["source"] == dispatch.context["source"]
        assert message.context["destination"] == dispatch.context["destination"]
        assert message.context["skill_id"] == plugin.skill_id
        assert message.data["lang"] == "fr-FR"


def test_each_sentence_waits_for_its_own_playback(live):
    """Pacing: the next sentence goes out only after the client reported
    the end of the previous one (audio_output_end on that session)."""
    plugin, bus = live
    events = Recorder(bus, "speak", "recognizer_loop:audio_output_end")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    plugin._readings["alice"].thread.join(60)

    sequence = [m.msg_type for _, m in events.messages
                if m.msg_type != "speak" or m.data["utterance"] in SENTENCES]
    first = sequence.index("speak")
    for a, b in zip(sequence[first::2], sequence[first + 1::2]):
        assert (a, b) == ("speak", "recognizer_loop:audio_output_end")


def test_two_sessions_read_side_by_side_and_stop_separately(live):
    plugin, bus = live
    speaks = Recorder(bus, "speak")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    _dispatch(plugin, bus, "bob", "read_any_story")
    alice, bob = plugin._readings["alice"], plugin._readings["bob"]
    time.sleep(PLAYBACK * 4)
    # a targeted stop from Alice, as ovos-core's stop pipeline sends it
    bus.emit(session_message("alice", f"{plugin.skill_id}.stop"))
    alice.thread.join(60)
    bob.thread.join(60)

    def heard(session_id):
        return [m.data["utterance"] for _, m in speaks.of("speak")
                if m.context["session"]["session_id"] == session_id and m.data["utterance"] in SENTENCES]

    assert heard("bob") == SENTENCES
    assert 0 < len(heard("alice")) < len(SENTENCES)
