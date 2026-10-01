"""Where a story came from is said once, after its last sentence.

It used to be said twice: in the announcement ("Here it is: Esben and the
Witch, by Andrew Lang, from Pink Fairy Book, sourced from Project
Gutenberg.") and again in the closing line ("That's the end - sourced from
Project Gutenberg."). The announcement now names the story, its author and
its collection (and whether it was machine translated, which has to be said
before), and the source is left to the end.

These tests read a story with the real locale files, through the plugin's
own announcement and reading loop (on the test's thread instead of the
reader thread), and look at everything that was said, in order."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ovos_bus_client.session import Session

from conftest import report_end, CommonReadingPipeline, REPO_ROOT, dispatch_message, use_real_dialogs

LOCALES = sorted(p.name for p in (Path(REPO_ROOT) / "locale").iterdir() if p.is_dir())
SOURCE = "Project Gutenberg"
STORY = {"skill_id": "ovos-skill-andrew-lang-tales.andlo", "content_id": "Esben and the Witch",
         "title": "Esben and the Witch", "author": "Andrew Lang", "collection": "Pink Fairy Book",
         "source": SOURCE, "confidence": 0.95}
PARAGRAPHS = ["Once upon a time there was a man who had twelve sons. The youngest was called Esben.",
              "Esben went to the witch's house. And there he stayed."]
SENTENCES = ["Once upon a time there was a man who had twelve sons.", "The youngest was called Esben.",
             "Esben went to the witch's house.", "And there he stayed."]
NARRATION = [None, "ssml"]


def _closing_lines(lang, source=SOURCE):
    path = Path(REPO_ROOT) / "locale" / lang / "finished_reading.dialog"
    return {line.strip().format(source=source)
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _listen(plugin, narration=None, on_line=None):
    """Record everything the plugin says, in order: plain speak() (the
    announcement, the dialogs, and the story when not narrating) and
    _speak_ssml() (the story when narrating). `on_line(line)` runs as each
    line is said, the way a user's "stop" arrives while a sentence plays."""
    heard = []

    def hear(utterance, *args, **kwargs):
        heard.append(utterance)
        if on_line:
            on_line(utterance)
        report_end(plugin)  # said, and the client says so

    plugin.speak = MagicMock(side_effect=hear)
    plugin._speak_ssml = MagicMock(side_effect=hear)
    plugin._fetch_content = MagicMock(return_value=PARAGRAPHS)
    if narration:
        plugin.config = {"narration": narration}
    # read on this thread, so the test sees the whole story
    plugin._read_in_background = lambda message, reading, bookmark: plugin._read_content(message, reading, bookmark)
    return heard


def _said_the_source(heard):
    return [line for line in heard if SOURCE in line]


@pytest.mark.parametrize("lang", LOCALES)
def test_the_announcement_never_names_the_source(plugin, monkeypatch, lang):
    use_real_dialogs(plugin, monkeypatch, lang)
    candidate = dict(STORY, machine_translated=True)

    for _ in range(20):  # every line of i_know_that
        line = plugin._render('i_know_that', description=plugin._describe(candidate))
        assert SOURCE not in line
        for field in ("title", "author", "collection"):
            assert candidate[field] in line
        assert plugin._render('machine_translated') in line  # the disclosure stays before the story


@pytest.mark.parametrize("narration", NARRATION)
@pytest.mark.parametrize("lang", LOCALES)
def test_the_source_is_said_once_after_the_last_sentence(plugin, monkeypatch, lang, narration):
    use_real_dialogs(plugin, monkeypatch, lang)
    heard = _listen(plugin, narration)

    plugin._announce_and_read(dispatch_message(lang=lang), STORY, bookmark=0)

    plugin.log.exception.assert_not_called()
    assert heard[1:-1] == SENTENCES
    assert _said_the_source(heard) == [heard[-1]]
    assert heard[-1] in _closing_lines(lang)
    narrated = [c.args[0] for c in plugin._speak_ssml.call_args_list]
    assert narrated == (SENTENCES if narration else [])  # the closing line is never narrated


@pytest.mark.parametrize("narration", NARRATION)
def test_a_stopped_story_never_names_its_source(plugin, monkeypatch, narration):
    use_real_dialogs(plugin, monkeypatch, "en-us")
    message = dispatch_message()

    def stop_during_the_second_sentence(line):
        if line == SENTENCES[1]:
            assert plugin.stop_session(Session("default"))

    heard = _listen(plugin, narration, on_line=stop_during_the_second_sentence)

    plugin._announce_and_read(message, STORY, bookmark=0)

    plugin.log.exception.assert_not_called()
    assert heard[1:3] == SENTENCES[:2]
    assert SENTENCES[2] not in heard
    assert not _said_the_source(heard)


@pytest.mark.parametrize("narration", NARRATION)
def test_a_paused_story_names_its_source_when_it_is_finished(plugin, monkeypatch, narration):
    """Paused: no source. Continued and read to the end: the source, once,
    after the last sentence."""
    use_real_dialogs(plugin, monkeypatch, "en-us")
    message = dispatch_message()

    def pause_during_the_second_sentence(line):
        if line == SENTENCES[1]:
            plugin._handle_pause(dispatch_message(intent="pause"))

    heard = _listen(plugin, narration, on_line=pause_during_the_second_sentence)
    plugin._announce_and_read(message, STORY, bookmark=0)

    assert heard[1:3] == SENTENCES[:2]
    assert not _said_the_source(heard)

    heard = _listen(plugin, narration)
    plugin._handle_continue(dispatch_message(intent="continue"))

    plugin.log.exception.assert_not_called()
    assert heard[1:-1] == SENTENCES[2:]
    assert _said_the_source(heard) == [heard[-1]]
    assert heard[-1] in _closing_lines("en-us")


@pytest.mark.parametrize("lang,other", [("fr-FR", "en-us"), ("de-DE", "en-us"), ("en-US", "fr-fr")])
def test_the_closing_line_is_in_the_language_of_the_session(plugin, monkeypatch, lang, other):
    """Not a language set on the plugin: the one of the request the story
    came from, found on the reader's stack like every speak()."""
    use_real_dialogs(plugin, monkeypatch, other)
    real_lang = next(vars(k)["lang"] for k in CommonReadingPipeline.__mro__[1:] if "lang" in vars(k))
    monkeypatch.setattr(CommonReadingPipeline, "lang", real_lang)
    monkeypatch.setattr(CommonReadingPipeline, "core_lang", other, raising=False)
    heard = _listen(plugin)

    plugin._announce_and_read(dispatch_message(lang=lang), STORY, bookmark=0)

    plugin.log.exception.assert_not_called()
    assert heard[-1] in _closing_lines(lang.lower())
    assert heard[-1] not in _closing_lines(other)
