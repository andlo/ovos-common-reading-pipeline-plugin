"""Setting "player": "ovos-media" (OpenVoiceOS/ovos-media#240): the story is
handed to the media player as a playlist of sentences with tts// uris, and
this plugin's own "pause" and "continue" are passed on to the player."""
import sys

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


def test_pause_and_continue_are_the_players(media):
    plugin, bus = media
    seen = Recorder(bus, module.OCP_PAUSE, module.OCP_RESUME, module.OCP_PLAY)
    _read(plugin, bus)

    _dispatch(plugin, bus, "alice", "pause")
    _dispatch(plugin, bus, "alice", "continue")
    assert len(seen.of(module.OCP_PAUSE)) == 1
    assert len(seen.of(module.OCP_RESUME)) == 1
    assert len(seen.of(module.OCP_PLAY)) == 1  # continue resumes, it does not start over
    assert not plugin._is_reading("alice")


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
