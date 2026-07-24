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
    ("en-us", "pause", "pause"),
    # real gaps found via user testing, now covered - see
    # scripts/build_padacioso_intents.py's docstring for the full story
    ("en-us", "tell me about abraham lincoln", None),  # collision fix: no longer claimed here
    ("en-us", "tell me the story about the little mermaid", "read_content"),
    ("en-us", "tell the story cinderella", "read_content"),  # "me" is optional
    ("en-us", "tell me a fairytale about the ugly duckling", "read_content"),
    ("en-us", "read me my horoscope", "read_by_type"),
    ("en-us", "read the horoscope", "read_by_type"),
    ("en-us", "what is my horoscope", "read_by_type"),
    ("en-us", "read me today's horoscope", "read_by_type"),
    ("en-us", "read the almanac", "read_by_type"),
    ("en-us", "read the weather report", "read_by_type"),
    ("en-us", "find cinderella from archive", "read_by_collection"),
    ("da-dk", "fortæl mig en historie om askepot", "read_content"),
    ("da-dk", "fortæl mig en historie fra grimm", "read_by_collection"),
    ("da-dk", "fortsæt", "continue"),
    ("da-dk", "pause", "pause"),
    ("da-dk", "fortæl mig historien om den lille havfrue", "read_content"),
    ("da-dk", "fortæl historien askepot", "read_content"),  # "mig" is optional
    ("da-dk", "læs mit horoskop", "read_by_type"),
    ("da-dk", "hvad er dagens horoskop", "read_by_type"),
    ("de-de", "erzähl mir eine geschichte über aschenputtel", "read_content"),
    ("de-de", "erzähl mir eine geschichte von grimm", "read_by_collection"),
    ("de-de", "weiter", "continue"),
    ("de-de", "pause", "pause"),
    ("es-es", "cuéntame un cuento sobre cenicienta", "read_content"),
    ("es-es", "cuéntame un cuento de grimm", "read_by_collection"),
    ("es-es", "pausa", "pause"),
    ("fr-fr", "raconte-moi une histoire sur cendrillon", "read_content"),
    ("fr-fr", "raconte-moi une histoire de grimm", "read_by_collection"),
    ("fr-fr", "pause", "pause"),
    ("it-it", "raccontami una storia su cenerentola", "read_content"),
    ("it-it", "raccontami una storia di grimm", "read_by_collection"),
    ("it-it", "pausa", "pause"),
    ("nl-nl", "vertel me een verhaal over assepoester", "read_content"),
    ("nl-nl", "vertel me een verhaal van grimm", "read_by_collection"),
    ("nl-nl", "pauze", "pause"),
    ("pt-pt", "conta-me uma história sobre cinderela", "read_content"),
    ("pt-pt", "conta-me uma história de grimm", "read_by_collection"),
    ("pt-pt", "pausa", "pause"),
])
def test_real_bundled_intents_match(plugin, lang, phrase, expected_intent):
    container = plugin._get_intent_container(lang)
    result = container.calc_intent(phrase)
    assert result.get("name") == expected_intent, f"{phrase!r} in {lang}: got {result}"


def test_content_type_entity_captured_for_horoscope(plugin):
    """Confirms content_type is actually captured (not just that
    read_by_type wins) - this is what gets forwarded to provider
    skills as a search hint, see __init__.py's match()."""
    container = plugin._get_intent_container("en-us")
    result = container.calc_intent("read the horoscope")
    assert result.get("entities", {}).get("content_type") == "horoscope"


def test_collection_and_title_together_is_a_known_fragile_combination(plugin):
    """NOT a passing assertion of correct behavior - documents a real,
    pre-existing limitation (not introduced by the vocabulary work
    above) confirmed via live testing: combining both a title AND a
    collection in one utterance can lose to the plainer read_content
    pattern, swallowing "from {collection}" into the title instead of
    recognizing it separately. The bare "from {collection}" form
    without a title (see "tell me a story from grimm" above) is NOT
    affected - only the combination is fragile. See
    scripts/build_padacioso_intents.py's KNOWN LIMITATION comment."""
    container = plugin._get_intent_container("en-us")
    result = container.calc_intent("tell me the story about the little mermaid from andersen")
    # documents the CURRENT (undesired but real) behavior, not the
    # desired one - if this starts failing, the underlying padacioso
    # matching behavior changed and this test (and the comment it
    # points at) should be revisited, not just patched to match
    assert result.get("name") == "read_content"


def test_unsupported_language_falls_back_to_english(plugin):
    container = plugin._get_intent_container("xx-xx")
    result = container.calc_intent("tell me a story about cinderella")
    assert result.get("name") == "read_content"


def test_intent_container_is_cached_per_language(plugin):
    first = plugin._get_intent_container("en-us")
    second = plugin._get_intent_container("en-us")
    assert first is second

