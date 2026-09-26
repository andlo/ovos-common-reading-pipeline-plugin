"""How long the reader waits for a line to be heard (#41).

speak(wait=True) waits for the session's audio_output_end or 15 s. A client
that never reports its playback left 15 s of silence after every sentence,
so every line the reader waits on is given a wait sized to it instead:
len(text) / chars_per_second + margin, rounded up, at most 15 s."""
from unittest.mock import MagicMock

import pytest

from conftest import module, use_real_dialogs

spoken_wait = module.spoken_wait


@pytest.mark.parametrize("text,seconds", [
    ("", 3),  # the margin alone: synthesis before the first word
    ("Yes.", 4),  # 0.3 s of speech + 3, rounded up
    ("x" * 28, 5),  # exactly 2 s of speech
    ("x" * 29, 6),  # a little more rounds up, never down
    ("x" * 140, 13),
    ("x" * 160, 15),  # MAX_SPOKEN_CHARS: 11.4 + 3 rounds up to the cap
    ("x" * 1000, 15),  # never more than wait=True used to wait
])
def test_the_wait_is_sized_to_the_text(text, seconds):
    assert spoken_wait(text) == seconds


def test_the_wait_is_a_whole_number_of_seconds():
    """ovos-workshop 0.1.0 to 0.1.2 read the wait as `wait if
    isinstance(wait, int) else 15`; a float there would wait the full 15 s."""
    for text in ("", "Yes.", "x" * 29, "x" * 1000):
        assert type(spoken_wait(text)) is int
    assert spoken_wait("", margin=0) == 1  # and never 0, which means "don't wait"


def test_the_rate_and_margin_come_from_the_plugin_config(plugin):
    """ovos-core hands the plugin intents["ovos-common-reading-pipeline-plugin"]
    from mycroft.conf as its config."""
    plugin.config = {"chars_per_second": 20, "wait_margin": 1}

    assert plugin._spoken_wait("x" * 40) == 3


def test_the_settings_file_is_used_when_the_config_says_nothing(plugin):
    plugin.config = {}
    plugin.settings["chars_per_second"] = 10
    plugin.settings["wait_margin"] = 0

    assert plugin._spoken_wait("x" * 40) == 4


def test_the_config_wins_over_the_settings_file(plugin):
    plugin.config = {"chars_per_second": 20}
    plugin.settings["chars_per_second"] = 10

    assert plugin._spoken_wait("x" * 40) == 5  # 2 s + the default 3 s margin


@pytest.mark.parametrize("config", [
    {"chars_per_second": 0},
    {"chars_per_second": -5},
    {"chars_per_second": "fast"},
    {"wait_margin": -1},
    {"wait_margin": "some"},
])
def test_a_value_that_makes_no_sense_is_ignored(plugin, config):
    plugin.config = config

    assert plugin._spoken_wait("x" * 28) == 5  # the defaults: 14 chars/s, 3 s
    plugin.log.warning.assert_called()


def test_a_bad_value_is_warned_about_once(plugin):
    plugin.config = {"chars_per_second": "fast"}

    for _ in range(3):
        plugin._spoken_wait("x" * 28)

    assert plugin.log.warning.call_count == 1


def test_a_zero_margin_is_allowed(plugin):
    plugin.config = {"wait_margin": 0}

    assert plugin._spoken_wait("x" * 28) == 2


def test_a_waited_dialog_is_given_the_wait_of_the_line_it_says(plugin, monkeypatch):
    """speak_dialog() takes its wait before it has picked a line, so the
    reader renders the line itself and hands it to speak() the way
    speak_dialog() would, with the wait sized to it."""
    use_real_dialogs(plugin, monkeypatch)
    plugin.speak = MagicMock()

    plugin._speak_dialog_and_wait('continue', data={"title": "Cinderella"})

    (line,), kwargs = plugin.speak.call_args
    assert "Cinderella" in line
    assert kwargs == {"wait": spoken_wait(line), "meta": {"dialog": "continue", "data": {"title": "Cinderella"}}}


def test_a_dialog_with_no_data_still_carries_its_meta(plugin, monkeypatch):
    use_real_dialogs(plugin, monkeypatch)
    plugin.speak = MagicMock()

    plugin._speak_dialog_and_wait('stop_reading')

    (line,), kwargs = plugin.speak.call_args
    assert line in ("Ok. I'll stop reading for now.", "Fine. We can continue another time.")
    assert kwargs == {"wait": spoken_wait(line), "meta": {"dialog": "stop_reading", "data": {}}}
