"""Tests for _read_content() - the actual paragraph/sentence reading
loop and its bookmark tracking. Notably, before this file, NOTHING
tested this method directly - every other test mocked it out entirely
(plugin._read_content = MagicMock()), which is exactly how a real bug
here went unnoticed: pausing mid-paragraph and resuming would skip the
rest of that paragraph entirely, because the bookmark was tracked at
paragraph granularity and marked 'done' the moment a paragraph
started, not after its sentences were actually spoken. See
ovos-common-reading-pipeline-plugin issue/commit history for the full
story - found via live testing with ovos-tui-client's activity pane.

The loop runs on its own thread in the plugin (see _start_reading); these
tests call it directly, on the test's thread, to check what it reads."""
from unittest.mock import MagicMock

from conftest import CommonReadingPipeline, ContentFetchError, entry, session_message


def _candidate(skill_id="ovos-skill-grimm-tales.andlo", content_id="Cinderella", source="grimmstories.com"):
    return {"skill_id": skill_id, "content_id": content_id, "title": "Cinderella", "source": source}


def _read(plugin, candidate, bookmark=0, message=None):
    """Register `candidate` as the session's story and read it through."""
    message = message or session_message()
    reading = plugin._begin_reading(message, candidate)
    plugin._read_content(message, reading, bookmark)
    return reading


def _spoken(plugin):
    return [c.args[0] for c in plugin.speak.call_args_list]


def _wire(plugin):
    plugin.speak = MagicMock()
    plugin.speak_dialog = MagicMock()


def test_reads_every_sentence_across_multiple_paragraphs(plugin):
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["First sentence. Second sentence", "Third sentence"])

    _read(plugin, _candidate())

    assert _spoken(plugin) == ["First sentence.", "Second sentence", "Third sentence"]


def test_every_sentence_waits_for_its_playback(plugin):
    """Pacing: each sentence goes out with wait=True, so a client that
    reports audio_output_end on the session sets the pace (see #41)."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["One. Two."])

    _read(plugin, _candidate())

    assert all(c.kwargs.get("wait") is True for c in plugin.speak.call_args_list)


def test_sentences_keep_their_full_stops(plugin):
    """Sentences go to speak(), not speak_dialog(): the dialog renderer took
    each sentence for a template name and replaced every '.' with a space."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Mr. Fox walked 3.5 miles. Then he slept."])

    _read(plugin, _candidate())

    assert _spoken(plugin) == ["Mr. Fox walked 3.5 miles.", "Then he slept."]
    plugin.speak_dialog.assert_called_once()  # only the closing 'finished_reading'


def test_finishes_and_clears_bookmark_when_all_sentences_spoken(plugin):
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Only sentence"])
    candidate = _candidate()
    key = CommonReadingPipeline._progress_key(candidate)

    _read(plugin, candidate)

    assert plugin._is_reading("default") is False
    assert "default" not in plugin.settings.get("sessions", {})  # nothing left to resume
    assert plugin._last_content("default") is None
    plugin.speak_dialog.assert_any_call('finished_reading', data={"source": "grimmstories.com"})
    assert key not in plugin.settings.get("sessions", {}).get("default", {}).get("progress", {})


def test_finishing_without_a_source_says_so_in_the_locale(plugin):
    """No English "the source" stand-in: a provider that names no source
    gets the finished_reading_unsourced dialog instead."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Only sentence"])

    _read(plugin, _candidate(source=None))

    plugin.speak_dialog.assert_called_once_with('finished_reading_unsourced')


def test_pausing_mid_single_large_paragraph_preserves_remaining_sentences(plugin):
    """The actual bug, reproduced: a provider that returns the WHOLE
    story as one big paragraph (no \\n\\n breaks in the source) used to
    lose everything after the pause point on resume, because the old
    code tracked progress per-PARAGRAPH and marked the single paragraph
    'done' as soon as it started - before any of its sentences had
    actually been spoken."""
    _wire(plugin)
    whole_story = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five"
    plugin._fetch_content = MagicMock(return_value=[whole_story])  # ONE paragraph, five sentences
    candidate = _candidate()
    key = CommonReadingPipeline._progress_key(candidate)

    # simulate pausing after the second sentence
    def speak_then_pause_after_two(sentence, **kw):
        if plugin.speak.call_count == 2:
            plugin._stop_reading("default")

    plugin.speak.side_effect = speak_then_pause_after_two
    _read(plugin, candidate)

    assert entry(plugin)["progress"][key] == 2  # exactly the 2 sentences actually heard
    assert _spoken(plugin) == ["Sentence one.", "Sentence two."]
    assert plugin._last_content("default") == candidate  # still there for "continue"

    # now resume from that bookmark - the remaining 3 sentences must
    # all be spoken, none skipped
    _wire(plugin)
    bookmark = entry(plugin)["progress"][key]

    _read(plugin, candidate, bookmark=bookmark)

    assert _spoken(plugin) == ["Sentence three.", "Sentence four.", "Sentence five"]


def test_fetch_error_speaks_content_unavailable_and_stops_reading(plugin):
    _wire(plugin)
    plugin._fetch_content = MagicMock(side_effect=ContentFetchError("boom"))

    _read(plugin, _candidate())

    assert plugin._is_reading("default") is False
    plugin.speak_dialog.assert_called_once_with('content_unavailable')
    plugin.speak.assert_not_called()


def test_an_unexpected_error_does_not_leave_the_session_reading(plugin):
    """Whatever goes wrong on the reader thread, the session must not stay
    marked as reading - can_stop would claim every later "stop"."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["One. Two."])
    plugin.speak.side_effect = RuntimeError("tts went away")

    _read(plugin, _candidate())

    assert plugin._is_reading("default") is False
    plugin.log.exception.assert_called_once()


def test_bookmark_of_zero_starts_from_the_very_first_sentence(plugin):
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["One. Two. Three"])

    _read(plugin, _candidate())

    assert _spoken(plugin) == ["One.", "Two.", "Three"]


def test_a_bookmark_from_the_old_splitter_resumes_where_the_words_left_off(plugin):
    """A bookmark saved before SPLITTER_VERSION counted chunks of the old
    '. ' split. "Mr. Fox" was two of those chunks and is part of one sentence
    now, so the old index 2, read as a new index, would skip "He ran." --
    the two old chunks heard were "Mr" and "Fox came home", so it must
    resume at "He ran."."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Mr. Fox came home. He ran. The end"])
    candidate = _candidate()
    key = CommonReadingPipeline._progress_key(candidate)
    plugin.settings["sessions"] = {"default": {"progress": {key: 2}}}  # old split: ["Mr", "Fox came home", "He ran", "The end"]

    _read(plugin, candidate, bookmark=2)

    assert _spoken(plugin) == ["He ran.", "The end"]


def test_a_bookmark_from_this_splitter_is_used_as_it_is(plugin):
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Mr. Fox came home. He ran. The end"])
    candidate = _candidate()
    key = CommonReadingPipeline._progress_key(candidate)
    plugin.settings["sessions"] = {"default": {"progress_splitter": {key: 2}}}

    _read(plugin, candidate, bookmark=1)

    assert _spoken(plugin) == ["He ran.", "The end"]
    assert key not in plugin.settings.get("sessions", {}).get("default", {}).get("progress_splitter", {})


def test_a_newer_story_in_the_same_session_takes_over(plugin):
    """Asking for another story while one plays stops the first one at its
    next sentence; its reader must not then clear the new story's state or
    say 'finished_reading' over it."""
    _wire(plugin)
    plugin._fetch_content = MagicMock(return_value=["Alpha. Beta. Gamma."])
    first, second = _candidate(content_id="first"), _candidate(content_id="second")
    message = session_message()
    old = plugin._begin_reading(message, first)

    def start_second_story(sentence, **kw):
        if plugin.speak.call_count == 1:
            plugin._begin_reading(message, second)

    plugin.speak.side_effect = start_second_story
    plugin._read_content(message, old, 0)

    assert _spoken(plugin) == ["Alpha."]
    assert plugin._is_reading("default") is True  # the second story
    assert plugin._last_content("default") == second
    plugin.speak_dialog.assert_not_called()
