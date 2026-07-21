"""Tests for handle_read_content / handle_continue, with _search_providers
and _fetch_content mocked out."""
from unittest.mock import MagicMock

from conftest import CommonReading


def make_message(data=None):
    m = MagicMock()
    m.data = data or {}
    return m


def _wire_common_mocks(skill):
    skill.speak_dialog = MagicMock()
    skill.ask_yesno = MagicMock(return_value="yes")
    skill.get_response = MagicMock(return_value="cinderella")


def test_handle_read_content_high_confidence_reads_directly(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella",
                 "author": "Grimm", "confidence": 0.95}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._read_content = MagicMock()

    skill.handle_read_content(make_message({"title": "cinderella"}))

    skill.ask_yesno.assert_not_called()
    skill._read_content.assert_called_once_with(candidate, 0)
    assert skill.settings['last_content'] == candidate


def test_handle_read_content_low_confidence_asks_for_confirmation(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "content_id": "Ash Girl", "title": "Ash Girl", "confidence": 0.3}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._read_content = MagicMock()

    skill.handle_read_content(make_message({"title": "cinderella"}))

    skill.ask_yesno.assert_called_once()
    skill._read_content.assert_called_once()


def test_handle_read_content_confirmation_declined(skill):
    _wire_common_mocks(skill)
    skill.ask_yesno = MagicMock(return_value="no")
    candidate = {"skill_id": "prov.a", "content_id": "Ash Girl", "title": "Ash Girl", "confidence": 0.3}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._read_content = MagicMock()

    skill.handle_read_content(make_message({"title": "cinderella"}))

    skill._read_content.assert_not_called()


def test_handle_read_content_no_providers_installed(skill):
    _wire_common_mocks(skill)
    skill._search_providers = MagicMock(return_value=[])
    skill._read_content = MagicMock()

    skill.handle_read_content(make_message({"title": "cinderella"}))

    skill._read_content.assert_not_called()
    dialog_names = [c.args[0] for c in skill.speak_dialog.call_args_list]
    assert 'no_content_providers' in dialog_names


def test_handle_read_by_collection_passes_hint_and_title(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella",
                 "author": "Grimm", "confidence": 0.95}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._read_content = MagicMock()

    skill.handle_read_by_collection(make_message({"title": "cinderella", "collection": "grimm"}))

    called_args = skill._search_providers.call_args
    assert called_args.kwargs["collection_hint"] == "grimm"
    skill._read_content.assert_called_once()


def test_handle_read_by_collection_without_title_asks_for_a_surprise(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "content_id": "Ash Girl", "title": "Ash Girl", "confidence": 1.0}
    skill._search_providers = MagicMock(return_value=[candidate])
    skill._read_content = MagicMock()

    skill.handle_read_by_collection(make_message({"title": None, "collection": "grimm"}))

    called_args = skill._search_providers.call_args
    assert called_args.args[0] is None
    skill._read_content.assert_called_once()


def test_handle_read_by_collection_unknown_collection(skill):
    _wire_common_mocks(skill)
    skill._search_providers = MagicMock(return_value=[])
    skill._read_content = MagicMock()

    skill.handle_read_by_collection(make_message({"title": None, "collection": "nonexistent author"}))

    skill._read_content.assert_not_called()
    dialog_names = [c.args[0] for c in skill.speak_dialog.call_args_list]
    assert 'no_such_collection' in dialog_names


def test_handle_continue_with_no_active_content(skill):
    _wire_common_mocks(skill)
    skill._read_content = MagicMock()

    skill.handle_continue(make_message())

    skill._read_content.assert_not_called()
    dialog_names = [c.args[0] for c in skill.speak_dialog.call_args_list]
    assert 'nothing_to_continue' in dialog_names


def test_handle_continue_resumes_from_saved_bookmark(skill):
    _wire_common_mocks(skill)
    candidate = {"skill_id": "prov.a", "content_id": "Cinderella", "title": "Cinderella"}
    skill.settings['last_content'] = candidate
    skill.settings['progress'][CommonReading._progress_key(candidate)] = 7
    skill._read_content = MagicMock()

    skill.handle_continue(make_message())

    skill._read_content.assert_called_once_with(candidate, 7)


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
