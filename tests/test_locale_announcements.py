"""The announcement before a story ("<title>, by <author>, from
<collection>, ...") used to glue English words into every language:
_describe() hard-coded "by", "from", "sourced from", "machine translated",
and the closing line fell back to "the source". Those words now come from
the locale, so a French or German story is announced in French or German
from start to end."""
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from conftest import REPO_ROOT, use_real_dialogs

LOCALES = sorted(p.name for p in (Path(REPO_ROOT) / "locale").iterdir() if p.is_dir())
NEW_DIALOGS = ["by_author", "from_collection", "sourced_from", "machine_translated",
               "finished_reading_unsourced"]
ENGLISH_JOINERS = {"by", "from", "sourced", "translated", "the", "machine"}

LA_BICHE = {"skill_id": "ovos-skill-cosquin-tales.andlo", "content_id": "LA BICHE BLANCHE",
            "title": "La Biche blanche", "author": "Emmanuel Cosquin",
            "collection": "Contes populaires de Lorraine", "source": "Projet Gutenberg",
            "machine_translated": True}
ASCHENBROEDEL = {"skill_id": "ovos-skill-bechstein-tales.andlo", "content_id": "Aschenbrödel",
                 "title": "Aschenbrödel", "author": "Ludwig Bechstein",
                 "collection": "Deutsches Märchenbuch", "source": "Projekt Gutenberg",
                 "machine_translated": True}


def _words(text, candidate):
    """The words of `text` that the locale added, i.e. not the candidate's own."""
    for value in candidate.values():
        if isinstance(value, str):
            text = text.replace(value, " ")
    return set(re.findall(r"[^\W\d_]+", text.lower()))


@pytest.mark.parametrize("lang", LOCALES)
@pytest.mark.parametrize("dialog", NEW_DIALOGS)
def test_every_locale_ships_the_announcement_dialogs(lang, dialog):
    path = Path(REPO_ROOT) / "locale" / lang / f"{dialog}.dialog"
    assert path.is_file(), f"{lang} has no {dialog}.dialog"
    assert path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("lang", LOCALES)
def test_every_locale_ships_the_any_story_intent(lang):
    assert (Path(REPO_ROOT) / "locale" / lang / "ReadAnyStory.intent").is_file()


def test_french_description_reads_naturally(plugin, monkeypatch):
    use_real_dialogs(plugin, monkeypatch, "fr-fr")

    assert plugin._describe(LA_BICHE) == (
        "La Biche blanche, par Emmanuel Cosquin, tiré du recueil Contes populaires de Lorraine, "
        "source : Projet Gutenberg, traduit automatiquement")
    assert plugin._describe_short(LA_BICHE) == "La Biche blanche, par Emmanuel Cosquin"


def test_german_description_reads_naturally(plugin, monkeypatch):
    use_real_dialogs(plugin, monkeypatch, "de-de")

    assert plugin._describe(ASCHENBROEDEL) == (
        "Aschenbrödel, von Ludwig Bechstein, aus der Sammlung Deutsches Märchenbuch, "
        "Quelle: Projekt Gutenberg, maschinell übersetzt")
    assert plugin._describe_short(ASCHENBROEDEL) == "Aschenbrödel, von Ludwig Bechstein"


@pytest.mark.parametrize("lang,candidate", [("fr-fr", LA_BICHE), ("de-de", ASCHENBROEDEL)])
def test_announcements_carry_no_english_words(plugin, monkeypatch, lang, candidate):
    """What is actually spoken before the story - 'i_know_that' around the
    description, and the 'is it that one?' lead-in - has no English left."""
    use_real_dialogs(plugin, monkeypatch, lang)
    plugin.speak = MagicMock()

    for _ in range(10):  # the dialogs pick a random line; try them all
        plugin.speak_dialog('i_know_that', data={"description": plugin._describe(candidate)})
        plugin.speak_dialog('that_would_be', data={"description": plugin._describe_short(candidate)})
        plugin.speak_dialog('finished_reading_unsourced')

    spoken = [c.args[0] for c in plugin.speak.call_args_list]
    assert spoken
    for line in spoken:
        assert not _words(line, candidate) & ENGLISH_JOINERS, line


def test_english_description_is_unchanged(plugin, monkeypatch):
    use_real_dialogs(plugin, monkeypatch, "en-us")
    candidate = {"title": "Cinderella", "author": "Brothers Grimm", "collection": "Household Tales",
                 "source": "grimmstories.com", "machine_translated": True}

    assert plugin._describe(candidate) == (
        "Cinderella, by Brothers Grimm, from Household Tales, sourced from grimmstories.com, machine translated")


@pytest.mark.parametrize("lang", ["fr-fr", "de-de", "da-dk", "es-es", "it-it", "nl-nl", "pt-pt"])
def test_no_locale_renders_a_dialog_name(plugin, monkeypatch, lang):
    """A missing dialog would be spoken as its file name ("by_author")."""
    use_real_dialogs(plugin, monkeypatch, lang)
    candidate = {"title": "T", "author": "A", "collection": "C", "source": "S", "machine_translated": True}

    description = plugin._describe(candidate)

    assert "_" not in description
    assert plugin._render('finished_reading_unsourced') != "finished_reading_unsourced"
