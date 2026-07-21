"""Tests for handle_Tales / handle_continue, with _search_providers and
_fetch_story mocked out so we can focus on the arbitration/confirmation
flow and bookmark bookkeeping in isolation."""
from unittest.mock import MagicMock

from conftest import CommonTales


def make_message(data=None):
    m = MagicMock()
    m.data = data or {}
    return m


def _wire_common_mocks(skill):
    skill.speak_dialog = MagicMock()
    skill.ask_yesno = MagicMock(return_value="yes")
    skill.get_response = MagicMock(return_value="cinderella")


def test_handle_tales_high_confidence_tells_story_directly(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "story_id": "Cinderella", "title": "Cinderella",
                 "author": "Grimm", "confidence": 0.95}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._tell_story = MagicMock()

    skill.handle_Tales(make_message({"tale": "cinderella"}))

    skill.ask_yesno.assert_not_called()  # confidence high enough, no confirmation needed
    skill._tell_story.assert_called_once_with(candidate, 0)
    assert skill.settings['last_story'] == candidate


def test_handle_tales_low_confidence_asks_for_confirmation(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "story_id": "Ash Girl", "title": "Ash Girl", "confidence": 0.3}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._tell_story = MagicMock()

    skill.handle_Tales(make_message({"tale": "cinderella"}))

    skill.ask_yesno.assert_called_once()
    skill._tell_story.assert_called_once()


def test_handle_tales_confirmation_declined_does_not_tell_story(skill):
    _wire_common_mocks(skill)
    skill.ask_yesno = MagicMock(return_value="no")
    candidate = {"skill_id": "prov.a", "story_id": "Ash Girl", "title": "Ash Girl", "confidence": 0.3}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._tell_story = MagicMock()

    skill.handle_Tales(make_message({"tale": "cinderella"}))

    skill._tell_story.assert_not_called()


def test_handle_tales_no_providers_installed(skill):
    _wire_common_mocks(skill)
    skill._search_providers = MagicMock(return_value=[])
    skill._tell_story = MagicMock()

    skill.handle_Tales(make_message({"tale": "cinderella"}))

    skill._tell_story.assert_not_called()
    dialog_names = [c.args[0] for c in skill.speak_dialog.call_args_list]
    assert 'no_story_providers' in dialog_names


def test_handle_tales_by_collection_passes_hint_and_tale(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.grimm", "story_id": "Cinderella", "title": "Cinderella", "confidence": 0.95}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._tell_story = MagicMock()

    skill.handle_tales_by_collection(make_message({"tale": "cinderella", "collection": "grimm"}))

    skill._search_providers.assert_called_once_with("cinderella", collection_hint="grimm")
    skill._tell_story.assert_called_once_with(candidate, 0)


def test_handle_tales_by_collection_without_tale_asks_for_a_surprise(skill):
    """'tell me a story from Grimm' with no specific title named - phrase
    is None, provider is expected to offer something of its own choosing."""
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.grimm", "story_id": "Rumpelstiltskin",
                 "title": "Rumpelstiltskin", "confidence": 0.9}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._tell_story = MagicMock()

    skill.handle_tales_by_collection(make_message({"collection": "grimm"}))

    skill._search_providers.assert_called_once_with(None, collection_hint="grimm")
    skill._tell_story.assert_called_once()


def test_handle_tales_by_collection_unknown_collection(skill):
    _wire_common_mocks(skill)
    skill._search_providers = MagicMock(return_value=[])
    skill._tell_story = MagicMock()

    skill.handle_tales_by_collection(make_message({"collection": "aesop"}))

    skill._tell_story.assert_not_called()
    dialog_names = [c.args[0] for c in skill.speak_dialog.call_args_list]
    assert 'no_such_collection' in dialog_names
    no_such_call = next(c for c in skill.speak_dialog.call_args_list if c.args[0] == 'no_such_collection')
    assert no_such_call.kwargs["data"]["collection"] == "aesop"


def test_handle_continue_with_no_active_story(skill):
    _wire_common_mocks(skill)
    skill._tell_story = MagicMock()

    skill.handle_continue(make_message())

    skill._tell_story.assert_not_called()
    dialog_names = [c.args[0] for c in skill.speak_dialog.call_args_list]
    assert 'no_story_to_continue' in dialog_names


def test_handle_continue_resumes_from_saved_bookmark(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "story_id": "Cinderella", "title": "Cinderella"}
    skill.settings['last_story'] = candidate
    skill.settings['progress'][CommonTales._progress_key(candidate)] = 7
    skill._tell_story = MagicMock()

    skill.handle_continue(make_message())

    skill._tell_story.assert_called_once_with(candidate, 7)


def test_stop_while_reading_speaks_and_returns_true(skill):
    _wire_common_mocks(skill)
    skill.is_reading = True

    result = skill.stop()

    assert result is True
    assert skill.is_reading is False


def test_stop_while_not_reading_returns_false(skill):
    _wire_common_mocks(skill)
    skill.is_reading = False

    assert skill.stop() is False
