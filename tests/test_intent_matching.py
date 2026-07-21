"""Tests for _get_intent_container/_locale_dir_for against the REAL
bundled locale/*.intent files - automated coverage for the matching
behavior validated manually across all 8 languages while building this
(see scripts/build_padacioso_intents.py)."""
import pytest


@pytest.mark.parametrize("lang,phrase,expected_intent", [
    ("en-us", "tell me a story about cinderella", "read_content"),
    ("en-us", "tell me an article about the weather", "read_content"),
    ("en-us", "tell me a story from grimm", "read_by_collection"),
    ("en-us", "continue", "continue"),
    ("da-dk", "fortæl mig en historie om askepot", "read_content"),
    ("da-dk", "fortæl mig en historie fra grimm", "read_by_collection"),
    ("da-dk", "fortsæt", "continue"),
    ("de-de", "erzähl mir eine geschichte über aschenputtel", "read_content"),
    ("de-de", "erzähl mir eine geschichte von grimm", "read_by_collection"),
    ("de-de", "weiter", "continue"),
    ("es-es", "cuéntame un cuento sobre cenicienta", "read_content"),
    ("es-es", "cuéntame un cuento de grimm", "read_by_collection"),
    ("fr-fr", "raconte-moi une histoire sur cendrillon", "read_content"),
    ("fr-fr", "raconte-moi une histoire de grimm", "read_by_collection"),
    ("it-it", "raccontami una storia su cenerentola", "read_content"),
    ("it-it", "raccontami una storia di grimm", "read_by_collection"),
    ("nl-nl", "vertel me een verhaal over assepoester", "read_content"),
    ("nl-nl", "vertel me een verhaal van grimm", "read_by_collection"),
    ("pt-pt", "conta-me uma história sobre cinderela", "read_content"),
    ("pt-pt", "conta-me uma história de grimm", "read_by_collection"),
])
def test_real_bundled_intents_match(plugin, lang, phrase, expected_intent):
    container = plugin._get_intent_container(lang)
    result = container.calc_intent(phrase)
    assert result.get("name") == expected_intent, f"{phrase!r} in {lang}: got {result}"


def test_unsupported_language_falls_back_to_english(plugin):
    container = plugin._get_intent_container("xx-xx")
    result = container.calc_intent("tell me a story about cinderella")
    assert result.get("name") == "read_content"


def test_intent_container_is_cached_per_language(plugin):
    first = plugin._get_intent_container("en-us")
    second = plugin._get_intent_container("en-us")
    assert first is second
