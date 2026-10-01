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


def _start(tmp_path, monkeypatch, sentences=SENTENCES, reports_playback=True):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    real_sleep = time.sleep
    # the 2 s search window is a plain sleep; a FakeBus provider answers at once
    monkeypatch.setattr(module.time, "sleep", lambda s: real_sleep(min(s, 0.05)))
    bus = FakeBus()
    monkeypatch.setattr(SessionManager, "bus", None)
    SessionManager.connect_to_bus(bus)

    # One voice, as a client has: what it is sent is said in order, one at a
    # time, however many sentences the reader sends ahead.
    said = []
    voice = threading.Condition()

    def speaker():
        while True:
            with voice:
                while not said:
                    voice.wait()
                message = said.pop(0)
            if message is None:
                return
            # speak() starts listening for the end just after it emits; an end
            # that beats it is missed and costs the full 15 s wait (as it would
            # live), so give it a head start on a loaded machine
            real_sleep(0.02)
            bus.emit(message.forward("recognizer_loop:audio_output_start"))
            real_sleep(PLAYBACK)
            bus.emit(message.forward("recognizer_loop:audio_output_end"))

    threading.Thread(target=speaker, daemon=True).start()

    def audio(message):
        with voice:
            said.append(message)
            voice.notify()

    def search(message):
        bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {
            "skill_id": PROVIDER, "content_id": "rapunzel", "title": "Rapunzel",
            "author": "Andrew Lang", "source": "Project Gutenberg", "confidence": 0.95}))

    def fetch(message):
        bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": [" ".join(sentences)]}))

    if reports_playback:
        bus.on("speak", audio)
    bus.on(COMMON_READING_SEARCH, search)
    bus.on(f"{COMMON_READING_FETCH_CONTENT}.{PROVIDER}", fetch)
    plugin = CommonReadingPipeline(bus=bus)
    # A fake voice says a sentence in PLAYBACK, far faster than the
    # 30 characters a second no sentence is allowed to beat; let it.
    plugin._read_ahead_timing = {"fastest": 10_000}
    return plugin, bus


@pytest.fixture
def live(tmp_path, monkeypatch):
    plugin, bus = _start(tmp_path, monkeypatch)
    yield plugin, bus
    plugin.stop()


@pytest.fixture
def quiet(tmp_path, monkeypatch):
    """A client that plays what it is sent and never says so: no
    audio_output_start/end at all (#41)."""
    plugin, bus = _start(tmp_path, monkeypatch, sentences=SENTENCES[:5], reports_playback=False)
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
    assert result.match_data == {"content_type": "story", "title": "rapunzel"}
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


def test_never_more_than_three_sentences_are_out_unsaid(live):
    """Pacing: the reader sends ahead so the client never waits on the round
    trip between sentences, but a client holds at most READ_AHEAD sentences
    it has not finished saying, counted by its audio_output_end."""
    plugin, bus = live
    events = Recorder(bus, "speak", "recognizer_loop:audio_output_end")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    plugin._readings["alice"].thread.join(60)

    held, most = 0, 0
    reading = False
    for _, m in events.messages:
        if m.msg_type == "speak" and m.data["utterance"] in SENTENCES:
            reading = True
            held += 1
            most = max(most, held)
        elif m.msg_type == "recognizer_loop:audio_output_end" and reading and held:
            held -= 1
    assert most == module.READ_AHEAD == 3


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


def test_a_client_that_never_reports_playback_waits_each_sentence_its_own_length(quiet):
    """#41: nothing answers the speaks. Three go out together, and then each
    sentence is held for as long as it takes to say, not wait=True's 15 s.
    The rate is turned up here so every wait is the 1 s floor and the test
    stays short."""
    plugin, bus = quiet
    plugin.config = {"chars_per_second": 1000, "wait_margin": 0}
    speaks = Recorder(bus, "speak")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    reader = plugin._readings["alice"].thread
    reader.join(30)

    assert not reader.is_alive()
    story = [(t, m.data["utterance"]) for t, m in speaks.of("speak") if m.data["utterance"] in SENTENCES]
    assert [u for _, u in story] == SENTENCES[:5]
    assert [plugin._spoken_wait(u) for _, u in story] == [1] * 5
    gaps = [b - a for (a, _), (b, _) in zip(story, story[1:])]
    assert all(gap < 0.3 for gap in gaps[:2]), gaps  # read ahead
    assert all(0.9 < gap < 1.5 for gap in gaps[2:]), gaps  # then one per sentence


def test_a_client_that_reports_playback_still_sets_the_pace(live):
    """The sized wait is only the longest a sentence is held: once three are
    out, the next goes as soon as the client reports the end of one. Twenty
    sentences sized at 6 s each are read in a second or two."""
    plugin, bus = live
    events = Recorder(bus, "speak", "recognizer_loop:audio_output_end")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    plugin._readings["alice"].thread.join(60)

    story = [t for t, m in events.of("speak") if m.data["utterance"] in SENTENCES]
    ends = [t for t, _ in events.of("recognizer_loop:audio_output_end")]
    assert len(story) == len(SENTENCES)
    assert sum(plugin._spoken_wait(s) for s in SENTENCES) >= 100
    assert story[-1] - story[0] < 10
    for following in story[3:]:
        end = max(t for t in ends if t <= following)
        assert following - end < 0.5


def test_a_client_that_ends_every_sentence_at_once_cannot_race_the_story(plugin):
    """2026-10-01, Story Time: a phone on vibrate ended each sentence unsaid
    within milliseconds, and a reader that waited for nothing else sent the
    whole story in ten seconds. No sentence is over sooner than a voice could
    say it, so a client that says nothing gets the story at reading pace."""
    window = module._ReadAhead(3, 30, clock=plugin.clock.now, pause=plugin.clock.advance)
    never = threading.Event()
    sent_at = []
    for _ in range(6):
        window.wait_for_room(never)
        sent_at.append(plugin.clock.now() - 1000)
        window.sent("x" * 30, 4)
        window.ended()
    assert [round(t, 2) for t in sent_at] == [0, 0, 0, 1, 2, 3]


def test_a_client_that_reports_nothing_is_paced_by_each_sentence(plugin):
    window = module._ReadAhead(3, 30, clock=plugin.clock.now, pause=plugin.clock.advance)
    never = threading.Event()
    sent_at = []
    for _ in range(6):
        window.wait_for_room(never)
        sent_at.append(plugin.clock.now() - 1000)
        window.sent("x" * 30, 4)
    assert [round(t, 2) for t in sent_at] == [0, 0, 0, 4, 8, 12]


def test_the_window_and_the_floor_come_from_the_plugin_config(plugin):
    """Both live in mycroft.conf, intents["ovos-common-reading-pipeline-plugin"],
    like every other option: no value is fixed in the code."""
    seen = {}
    real = module._ReadAhead

    def spy(size, fastest=module.FASTEST_CHARS_PER_SECOND, **timing):
        seen.update(size=size, fastest=fastest)
        return real(size, fastest, **timing)

    plugin._read_ahead_timing = {}
    plugin.speak = lambda *a, **kw: None
    plugin.speak_dialog = lambda *a, **kw: None
    plugin._fetch_content = lambda *a, **kw: []
    plugin.config = {"read_ahead": 1, "fastest_chars_per_second": 50}
    module._ReadAhead, saved = spy, module._ReadAhead
    try:
        reading = plugin._begin_reading(session_message(), {"skill_id": "p.a", "content_id": "c", "title": "T"})
        plugin._read_content(session_message(), reading, 0)
    finally:
        module._ReadAhead = saved
    assert seen == {"size": 1, "fastest": 50}


def test_a_window_of_one_is_the_old_pace(plugin):
    assert module._ReadAhead(1).size == 1
    assert module._ReadAhead(0).size == 1  # never less than one


def test_narrated_sentences_carry_ssml_beside_the_same_text(live):
    """#40 on a real bus: with narration on, every sentence still goes out on
    speak()'s topic, forwarded from the dispatch (session, route, language),
    with the plain text unchanged and its SSML in utterance_ssml."""
    plugin, bus = live
    plugin.config = {"narration": "ssml"}
    speaks = Recorder(bus, "speak")

    dispatch = _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"}, lang="fr-FR")
    plugin._readings["alice"].thread.join(60)

    story = [m for _, m in speaks.of("speak") if m.data["utterance"] in SENTENCES]
    assert [m.data["utterance"] for m in story] == SENTENCES
    for message in story:
        assert message.context["session"]["session_id"] == "alice"
        assert message.context["source"] == dispatch.context["source"]
        assert message.context["destination"] == dispatch.context["destination"]
        assert message.data["lang"] == "fr-FR"
        assert message.data["utterance_ssml"] == module.narrate(
            message.data["utterance"],
            module.STORY_START_BREAK_MS if message is story[0] else 0)
    # the announcement and the other dialogs stay plain
    assert all("utterance_ssml" not in m.data for _, m in speaks.of("speak") if m not in story)


def test_without_narration_no_sentence_carries_ssml(live):
    plugin, bus = live
    speaks = Recorder(bus, "speak")

    _dispatch(plugin, bus, "alice", "read_content", {"title": "rapunzel"})
    plugin._readings["alice"].thread.join(60)

    assert speaks.of("speak")
    assert all("utterance_ssml" not in m.data for _, m in speaks.of("speak"))
