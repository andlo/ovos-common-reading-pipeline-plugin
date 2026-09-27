"""End to end through ovos-core's own IntentService, dispatcher and stop
pipeline, on a FakeBus: the plugin, a fake provider, and a fake audio
service that reports playback on each session. Skipped where ovos-core is
not installed (it is not a dependency of this plugin); written against
ovos-core 3.7, which bounds match() and ends each turn on the handler's
done-signal."""
import threading
import time

import pytest

pytest.importorskip("ovos_core.intent_services.dispatcher")

from ovos_bus_client.message import Message  # noqa: E402
from ovos_bus_client.session import SessionManager  # noqa: E402
from ovos_core.intent_services.service import IntentService  # noqa: E402
from ovos_core.intent_services.stop_service import StopService  # noqa: E402
from ovos_utils.fakebus import FakeBus  # noqa: E402

from conftest import (  # noqa: E402
    COMMON_READING_FETCH_CONTENT,
    COMMON_READING_FETCH_CONTENT_RESPONSE,
    COMMON_READING_SEARCH,
    COMMON_READING_SEARCH_RESPONSE,
    CommonReadingPipeline,
)

PROVIDER = "ovos-skill-fake-tales.test"
SENTENCES = [f"This is sentence {i} of the story." for i in range(1, 61)]
PIPELINE = ["ovos-stop-pipeline-plugin-high", "ovos-common-reading-pipeline-plugin"]


class Hub:
    """ovos-core plus the plugin; clients say things and echo back the
    session each turn ends with, as a HiveMind client does."""

    def __init__(self, bus):
        self.bus = bus
        self.log = []
        self.lock = threading.Lock()
        self.sessions = {}
        for topic in ("ovos.utterance.handled", "speak", "ovos.intent.matched"):
            bus.on(topic, self._record)

    def _record(self, message):
        with self.lock:
            self.log.append((time.monotonic(), message))

    def say(self, session_id, text):
        carrier = self.sessions.get(session_id) or {"session_id": session_id, "lang": "en-US",
                                                    "pipeline": PIPELINE}
        message = Message("recognizer_loop:utterance", {"utterances": [text], "lang": "en-US"},
                          {"session": carrier, "source": f"client.{session_id}", "destination": "skills"})
        started = time.monotonic()
        threading.Thread(target=self.bus.emit, args=(message,), daemon=True).start()
        return started

    def handled(self, session_id, after, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                for t, m in self.log:
                    if t >= after and m.msg_type == "ovos.utterance.handled" \
                            and m.context["session"]["session_id"] == session_id:
                        self.sessions[session_id] = m.context["session"]
                        return t
            time.sleep(0.02)
        return None

    def heard(self, session_id, after=0.0):
        with self.lock:
            return [(t, m.data["utterance"]) for t, m in self.log
                    if m.msg_type == "speak" and t >= after
                    and m.context["session"]["session_id"] == session_id]


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    bus = FakeBus()
    monkeypatch.setattr(SessionManager, "bus", None)

    def audio(message):
        def play():
            bus.emit(message.forward("recognizer_loop:audio_output_start"))
            time.sleep(0.05)
            bus.emit(message.forward("recognizer_loop:audio_output_end"))
        threading.Timer(0.02, play).start()  # see test_dispatch.py

    bus.on("speak", audio)
    bus.on(COMMON_READING_SEARCH, lambda m: bus.emit(m.reply(COMMON_READING_SEARCH_RESPONSE, {
        "skill_id": PROVIDER, "content_id": "rapunzel", "title": "Rapunzel", "confidence": 1.0})))
    bus.on(f"{COMMON_READING_FETCH_CONTENT}.{PROVIDER}", lambda m: bus.emit(m.reply(
        COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": [" ".join(SENTENCES)]})))

    intents = IntentService(bus, config={}, preload_pipelines=False)
    plugin = CommonReadingPipeline(bus=bus)
    plugin._get_intent_container("en-US")
    intents.pipeline_plugins["ovos-common-reading-pipeline-plugin"] = plugin
    intents.pipeline_plugins["ovos-stop-pipeline-plugin"] = StopService(bus)
    yield Hub(bus), plugin
    plugin.stop()
    intents.shutdown()


def test_the_turn_ends_while_the_story_is_read(hub):
    """"Tell me the story Rapunzel": ovos.utterance.handled arrives after
    the search window (2 s), not after the story, and the story goes on."""
    hub, plugin = hub
    asked = hub.say("alice", "tell me the story Rapunzel")

    ended = hub.handled("alice", asked)

    assert ended is not None and ended - asked < 5
    assert plugin._is_reading("alice")
    time.sleep(2.0)
    story_after_the_turn = [u for t, u in hub.heard("alice", ended) if u in SENTENCES]
    assert len(story_after_the_turn) >= 3


def test_one_users_stop_leaves_the_others_story_alone(hub):
    hub, plugin = hub
    for who in ("alice", "bob"):
        assert hub.handled(who, hub.say(who, "tell me the story Rapunzel")) is not None

    # somebody with nothing playing says stop: ovos-core's global stop
    assert hub.handled("carol", hub.say("carol", "stop")) is not None
    time.sleep(0.3)
    assert plugin._is_reading("alice") and plugin._is_reading("bob")

    # bob says stop: the stop pipeline targets the plugin for bob only
    stopped = hub.say("bob", "stop")
    assert hub.handled("bob", stopped) is not None
    time.sleep(0.5)
    assert not plugin._is_reading("bob")
    assert plugin._is_reading("alice")
    later = time.monotonic()
    time.sleep(1.0)
    assert hub.heard("alice", later) and not [u for _, u in hub.heard("bob", later) if u in SENTENCES]
