"""Tests for _read_content() - the actual paragraph/sentence reading
loop and its bookmark tracking. Notably, before this file, NOTHING
tested this method directly - every other test mocked it out entirely
(plugin._read_content = MagicMock()), which is exactly how a real bug
here went unnoticed: pausing mid-paragraph and resuming would skip the
rest of that paragraph entirely, because the bookmark was tracked at
paragraph granularity and marked 'done' the moment a paragraph
started, not after its sentences were actually spoken. See
ovos-common-reading-pipeline-plugin issue/commit history for the full
story - found via live testing with ovos-tui-client's activity pane."""
from unittest.mock import MagicMock

from conftest import CommonReadingPipeline, ContentFetchError


def _candidate(skill_id="ovos-skill-grimm-tales.andlo", content_id="Cinderella", source="grimmstories.com"):
    return {"skill_id": skill_id, "content_id": content_id, "title": "Cinderella", "source": source}


def test_reads_every_sentence_across_multiple_paragraphs(plugin):
    plugin.speak_dialog = MagicMock()
    plugin._fetch_content = MagicMock(return_value=["First sentence. Second sentence", "Third sentence"])
    candidate = _candidate()

    plugin._read_content(candidate, bookmark=0)

    spoken = [c.args[0] for c in plugin.speak_dialog.call_args_list if c.args and c.args[0] != 'finished_reading']
    assert spoken == ["First sentence", "Second sentence", "Third sentence"]


def test_finishes_and_clears_bookmark_when_all_sentences_spoken(plugin):
    plugin.speak_dialog = MagicMock()
    plugin._fetch_content = MagicMock(return_value=["Only sentence"])
    candidate = _candidate()
    key = CommonReadingPipeline._progress_key(candidate)
    plugin.settings['progress'][key] = 0
    plugin.settings['last_content'] = candidate

    plugin._read_content(candidate, bookmark=0)

    assert plugin.is_reading is False
    assert key not in plugin.settings['progress']
    assert plugin.settings['last_content'] is None
    plugin.speak_dialog.assert_any_call('finished_reading', data={"source": "grimmstories.com"})


def test_pausing_mid_single_large_paragraph_preserves_remaining_sentences(plugin):
    """The actual bug, reproduced: a provider that returns the WHOLE
    story as one big paragraph (no \\n\\n breaks in the source) used to
    lose everything after the pause point on resume, because the old
    code tracked progress per-PARAGRAPH and marked the single paragraph
    'done' as soon as it started - before any of its sentences had
    actually been spoken."""
    plugin.speak_dialog = MagicMock()
    whole_story = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five"
    plugin._fetch_content = MagicMock(return_value=[whole_story])  # ONE paragraph, five sentences
    candidate = _candidate()
    key = CommonReadingPipeline._progress_key(candidate)

    # simulate pausing after the second sentence
    call_count = {"n": 0}
    real_speak = plugin.speak_dialog

    def speak_then_pause_after_two(dialog, *a, **kw):
        call_count["n"] += 1
        real_speak(dialog, *a, **kw)
        if call_count["n"] == 2:
            plugin.is_reading = False

    plugin.speak_dialog = MagicMock(side_effect=speak_then_pause_after_two)
    plugin._read_content(candidate, bookmark=0)

    assert plugin.settings['progress'][key] == 2  # exactly the 2 sentences actually heard
    spoken_so_far = [c.args[0] for c in plugin.speak_dialog.call_args_list]
    assert spoken_so_far == ["Sentence one", "Sentence two"]

    # now resume from that bookmark - the remaining 3 sentences must
    # all be spoken, none skipped
    plugin.is_reading = False  # _handle_continue always sets this before calling _read_content
    plugin.speak_dialog = MagicMock()
    bookmark = plugin.settings['progress'][key]

    plugin._read_content(candidate, bookmark=bookmark)

    resumed_spoken = [c.args[0] for c in plugin.speak_dialog.call_args_list if c.args[0] != 'finished_reading']
    assert resumed_spoken == ["Sentence three", "Sentence four", "Sentence five"]


def test_fetch_error_speaks_content_unavailable_and_stops_reading(plugin):
    plugin.speak_dialog = MagicMock()
    plugin._fetch_content = MagicMock(side_effect=ContentFetchError("boom"))
    candidate = _candidate()

    plugin._read_content(candidate, bookmark=0)

    assert plugin.is_reading is False
    plugin.speak_dialog.assert_called_once_with('content_unavailable')


def test_bookmark_of_zero_starts_from_the_very_first_sentence(plugin):
    plugin.speak_dialog = MagicMock()
    plugin._fetch_content = MagicMock(return_value=["One. Two. Three"])
    candidate = _candidate()

    plugin._read_content(candidate, bookmark=0)

    spoken = [c.args[0] for c in plugin.speak_dialog.call_args_list if c.args[0] != 'finished_reading']
    assert spoken == ["One", "Two", "Three"]
