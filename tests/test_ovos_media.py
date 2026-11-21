"""Setting "player": "ovos-media" (OpenVoiceOS/ovos-media#240): the story is
handed to the media player as a playlist of sentences with tts// uris, and
this plugin's own "pause" and "continue" are passed on to the player."""
import sys

from ovos_bus_client.message import Message

import pytest

from conftest import module
from test_dispatch import PROVIDER, SENTENCES, Recorder, _dispatch, _start

tts = pytest.importorskip("ovos_ocp_tts_plugin")


@pytest.fixture
def media(tmp_path, monkeypatch):
    plugin, bus = _start(tmp_path, monkeypatch)
    plugin.settings["player"] = "ovos-media"
    yield plugin, bus
    plugin.stop()


def _read(plugin, bus, session_id="alice", lang="en-US"):
    _dispatch(plugin, bus, session_id, "read_content", {"title": "rapunzel"}, lang=lang)
    reading = plugin._readings.get(session_id)
    if reading is not None and reading.thread is not None:
        reading.thread.join(30)


def test_the_story_goes_to_the_player_as_sentences(media):
    plugin, bus = media
    seen = Recorder(bus, module.OCP_PLAY, "speak")
    _read(plugin, bus, lang="da-DK")

    [(_, play)] = seen.of(module.OCP_PLAY)
    playlist = play.data["playlist"]
    assert [tts.parse_tts_uri(e["uri"]) for e in playlist] == [("da-DK", s) for s in SENTENCES]
    assert play.data["media"] == playlist[0]
    assert {e["title"] for e in playlist} == {"Rapunzel"}
    assert {e["artist"] for e in playlist} == {"Andrew Lang"}
    # nothing of the story is spoken by the plugin itself
    assert not [m for _, m in seen.of("speak") if m.data["utterance"] in SENTENCES]
    # to the session that asked, the way every reply of the turn goes
    assert play.context["session"]["session_id"] == "alice"


def test_the_player_has_it_so_the_plugin_is_not_reading(media):
    plugin, bus = media
    _read(plugin, bus)
    assert not plugin._is_reading("alice")
    assert plugin._reads_through_media("alice")
    assert plugin._last_content("alice")["content_id"] == "rapunzel"


def test_a_bookmark_starts_the_player_where_it_stopped(media):
    plugin, bus = media
    seen = Recorder(bus, module.OCP_PLAY)
    reading = plugin._begin_reading(None, {"skill_id": PROVIDER, "content_id": "rapunzel",
                                           "title": "Rapunzel"}, "en-US")
    plugin._read_sentences(None, reading, 7)
    [(_, play)] = seen.of(module.OCP_PLAY)
    assert tts.parse_tts_uri(play.data["media"]["uri"])[1] == SENTENCES[7]
    assert len(play.data["playlist"]) == len(SENTENCES)


class FakePlayer:
    """ovos-media as far as the plugin sees it: it answers "status", reports
    its status when it moves to another track, and says its queue_finished
    dialog when the queue has played to the end."""

    def __init__(self, bus):
        self.bus = bus
        self.state = 1  # PLAYING
        self.position = 0
        self.size = 0
        self.title = ""
        bus.on(module.OCP_PLAY, self.on_play)
        bus.on(module.OCP_PAUSE, lambda m: setattr(self, "state", 2))
        bus.on(module.OCP_RESUME, lambda m: setattr(self, "state", 1))
        bus.on(module.OCP_STATUS, lambda m: bus.emit(m.response(self.status())))

    def on_play(self, message):
        playlist = message.data["playlist"]
        self.size, self.title = len(playlist), message.data["media"]["title"]
        self.state = 1
        self.go_to(playlist.index(message.data["media"]))

    def status(self):
        return {"player_state": self.state, "playlist_position": self.position,
                "playlist_size": self.size, "title": self.title}

    def go_to(self, position):
        """What ovos-media's set_now_playing() reports."""
        self.position = position
        self.bus.emit(Message(module.OCP_STATUS_RESPONSE, self.status()))

    def stop(self):
        self.state = 0

    def finish(self):
        self.go_to(self.size - 1)
        self.state = 0
        self.bus.emit(Message("speak", {"utterance": "that's the end of the queue",
                                        "meta": {"dialog": "queue_finished",
                                                 "skill": "ovos.common_play.favorites"}}))


@pytest.fixture
def player(media):
    plugin, bus = media
    return plugin, bus, FakePlayer(bus)


def test_pause_and_continue_are_the_players(player):
    plugin, bus, _ = player
    seen = Recorder(bus, module.OCP_PAUSE, module.OCP_RESUME, module.OCP_PLAY)
    _read(plugin, bus)

    _dispatch(plugin, bus, "alice", "pause")
    _dispatch(plugin, bus, "alice", "continue")
    assert len(seen.of(module.OCP_PAUSE)) == 1
    assert len(seen.of(module.OCP_RESUME)) == 1
    assert len(seen.of(module.OCP_PLAY)) == 1  # continue resumes, it does not start over
    assert not plugin._is_reading("alice")


def test_the_bookmark_follows_the_player(player):
    plugin, bus, fake = player
    _read(plugin, bus)
    fake.go_to(5)
    key = plugin._progress_key(plugin._last_content("alice"))
    assert plugin.settings["sessions"]["alice"]["progress"][key] == 5


def test_another_playlist_does_not_move_the_bookmark(player):
    plugin, bus, fake = player
    _read(plugin, bus)
    fake.go_to(4)
    bus.emit(Message(module.OCP_STATUS_RESPONSE, {"playlist_position": 1, "playlist_size": 3,
                                                  "title": "Some Song", "player_state": 1}))
    key = plugin._progress_key(plugin._last_content("alice"))
    assert plugin.settings["sessions"]["alice"]["progress"][key] == 4


def test_continue_after_a_stop_starts_again_at_the_bookmark(player):
    plugin, bus, fake = player
    seen = Recorder(bus, module.OCP_PLAY, module.OCP_RESUME)
    _read(plugin, bus)
    fake.go_to(6)
    fake.stop()  # "stop": the player has let go of the story

    _dispatch(plugin, bus, "alice", "continue")
    reading = plugin._readings.get("alice")
    if reading is not None and reading.thread is not None:
        reading.thread.join(30)
    plays = seen.of(module.OCP_PLAY)
    assert len(plays) == 2 and not seen.of(module.OCP_RESUME)
    assert tts.parse_tts_uri(plays[1][1].data["media"]["uri"])[1] == SENTENCES[6]


def test_read_to_the_end_it_closes_with_the_source(player):
    plugin, bus, fake = player
    said = Recorder(bus, "speak")
    _read(plugin, bus)
    fake.finish()

    closing = [m for _, m in said.of("speak")
               if (m.data.get("meta") or {}).get("dialog") == "finished_reading"]
    assert len(closing) == 1
    assert closing[0].context["session"]["session_id"] == "alice"
    assert not plugin._reads_through_media("alice")
    assert plugin._last_content("alice") is None  # nothing left to continue


def test_the_end_of_another_queue_is_not_the_end_of_the_story(player):
    plugin, bus, fake = player
    said = Recorder(bus, "speak")
    _read(plugin, bus)
    fake.go_to(3)  # the story is still in the middle
    bus.emit(Message("speak", {"utterance": "that's the end of the queue",
                               "meta": {"dialog": "queue_finished"}}))
    assert not [m for _, m in said.of("speak")
                if (m.data.get("meta") or {}).get("dialog") == "finished_reading"]
    assert plugin._reads_through_media("alice")


@pytest.mark.parametrize("lang, utterance", [("en-us", "pause the story"), ("da-dk", "pause historien")])
def test_pause_is_ours_to_match_while_the_player_reads(media, lang, utterance):
    """Nobody "plays" a fairy tale: the reading words stay this plugin's,
    also while the player has the story."""
    from conftest import session_message
    plugin, bus = media
    asking = session_message("alice", "recognizer_loop:utterance", lang=lang)
    assert plugin.match_high([utterance], lang, asking) is None  # nothing read yet
    _read(plugin, bus)
    match = plugin.match_high([utterance], lang, asking)
    assert match is not None and match.match_type.endswith(":pause")


def test_without_the_extractor_it_is_read_the_usual_way(media, monkeypatch):
    plugin, bus = media
    monkeypatch.setitem(sys.modules, "ovos_ocp_tts_plugin", None)  # import fails
    seen = Recorder(bus, module.OCP_PLAY, "speak")
    _read(plugin, bus)
    assert not seen.of(module.OCP_PLAY)
    assert [m.data["utterance"] for _, m in seen.of("speak")
            if m.data["utterance"] in SENTENCES] == SENTENCES
    assert not plugin._reads_through_media("alice")


def test_speak_stays_the_default(tmp_path, monkeypatch):
    plugin, bus = _start(tmp_path, monkeypatch)
    try:
        seen = Recorder(bus, module.OCP_PLAY)
        _read(plugin, bus)
        assert not seen.of(module.OCP_PLAY)
    finally:
        plugin.stop()
