"""Tests for _get_intent_container/_locale_dir_for against the REAL
bundled locale/*.intent files - automated coverage for the matching
behavior validated manually across all 8 languages while building this
(see scripts/build_padacioso_intents.py)."""
import pytest


@pytest.mark.parametrize("lang,phrase,expected_intent", [
    ("en-us", "tell me a story about cinderella", "read_content"),
    ("en-us", "tell me an article about the weather", "read_content"),
    ("en-us", "tell me a story from grimm", "read_by_collection"),
    # real gap found via live testing: "Tell me a {collection} story"
    # existed but its "Read" mirror didn't, across ALL 8 languages -
    # see scripts/build_padacioso_intents.py's READ_BY_COLLECTION
    ("en-us", "read me a grimm story", "read_by_collection"),
    ("da-dk", "læs mig en grimm-historie", "read_by_collection"),
    ("de-de", "lies mir eine grimm-Geschichte", "read_by_collection"),
    ("es-es", "léeme un cuento de grimm", "read_by_collection"),
    ("fr-fr", "lis-moi une histoire de grimm", "read_by_collection"),
    ("it-it", "leggimi una storia di grimm", "read_by_collection"),
    ("nl-nl", "lees me een grimm-verhaal", "read_by_collection"),
    ("pt-pt", "lê-me uma história de grimm", "read_by_collection"),
    ("en-us", "continue", "continue"),
    ("en-us", "pause", "pause"),
    # real gaps found via user testing, now covered - see
    # scripts/build_padacioso_intents.py's docstring for the full story
    ("en-us", "tell me about abraham lincoln", None),  # collision fix: no longer claimed here
    ("en-us", "tell me the story about the little mermaid", "read_content"),
    ("en-us", "tell the story cinderella", "read_content"),  # "me" is optional
    ("en-us", "tell me a fairytale about the ugly duckling", "read_content"),
    ("en-us", "read me my horoscope", "read_by_type"),
    # "What is my horoscope" deliberately no longer supported - real
    # feedback: this is a reading pipeline, not a "what" pipeline
    # (Common Query's domain) - see build_padacioso_intents.py's
    # READ_CONTENT_BY_TYPE comment.
    ("en-us", "what is my horoscope", None),
    ("en-us", "read me today's horoscope", "read_by_type"),
    ("en-us", "read me my almanac", "read_by_type"),
    ("en-us", "tell me today's weather report", "read_by_type"),
    ("en-us", "find cinderella from archive", "read_by_collection"),
    ("da-dk", "fortæl mig en historie om askepot", "read_content"),
    ("da-dk", "fortæl mig en historie fra grimm", "read_by_collection"),
    ("da-dk", "fortsæt", "continue"),
    ("da-dk", "pause", "pause"),
    ("da-dk", "fortæl mig historien om den lille havfrue", "read_content"),
    ("da-dk", "fortæl historien askepot", "read_content"),  # "mig" is optional
    ("da-dk", "læs mit horoskop", "read_by_type"),
    # "Hvad er dagens X" deliberately no longer supported - same
    # reasoning as en-us's "What is my X" removal above.
    ("da-dk", "hvad er dagens horoskop", None),
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
    # "Can you..." question forms (en-us/da-dk) - real request: users
    # naturally phrase this as a question too, not just an imperative.
    # Deliberately still gated on the NOUNS list, same as the plain
    # imperative forms - a fully open "Can you read me {title}" (no
    # noun required at all) was tried and reverted, since it collided
    # with this plugin's OWN read_by_collection/read_by_type patterns
    # (e.g. "read me a grimm story", "read me my horoscope" both
    # started tying against a bare, unrestricted {title} wildcard).
    ("en-us", "can you read me an article about boiling an egg", "read_content"),
    ("en-us", "can you read a story about cinderella", "read_content"),
    ("en-us", "can you tell me a story about the little mermaid", "read_content"),
    ("da-dk", "kan du læse mig en historie om askepot", "read_content"),
    ("da-dk", "kan du fortælle mig en historie om den lille havfrue", "read_content"),
    # "tell me a story" with no title: its own intent, read_any_story, which
    # searches with phrase=None so a provider picks the story. Must not take
    # the titled/collection forms, and never anything that isn't a story.
    ("en-us", "tell me a story", "read_any_story"),
    ("en-us", "Tell me a fairy tale", "read_any_story"),
    ("en-us", "read me a bedtime story", "read_any_story"),
    ("en-us", "can you tell me another story", "read_any_story"),
    ("en-us", "tell me a story please", "read_any_story"),
    ("en-us", "tell me a story about cinderella", "read_content"),
    ("en-us", "tell me a story from grimm", "read_by_collection"),
    ("en-us", "tell me a joke", None),
    ("en-us", "read me an article", None),
    ("da-dk", "fortæl mig et eventyr", "read_any_story"),
    ("da-dk", "læs et eventyr op for mig", "read_any_story"),
    ("da-dk", "fortæl en historie for mig", "read_any_story"),
    ("da-dk", "fortæl mig en vittighed", None),
    ("fr-fr", "raconte-moi une histoire", "read_any_story"),
    ("fr-fr", "raconte moi une histoire", "read_any_story"),  # STT without the hyphen
    ("fr-fr", "lis-moi un conte", "read_any_story"),
    ("fr-fr", "raconte-moi un conte", "read_any_story"),
    ("fr-fr", "raconte-nous une histoire", "read_any_story"),
    ("fr-fr", "peux-tu me raconter une histoire", "read_any_story"),
    ("fr-fr", "raconte-moi une histoire s'il te plaît", "read_any_story"),
    ("fr-fr", "raconte-moi une histoire sur cendrillon", "read_content"),
    ("fr-fr", "raconte-moi une histoire de cosquin", "read_by_collection"),
    ("fr-fr", "lis-moi les nouvelles", None),
    ("fr-fr", "raconte-moi une blague", None),
    ("de-de", "erzähl mir eine Geschichte", "read_any_story"),
    ("de-de", "erzähle mir eine geschichte", "read_any_story"),
    ("de-de", "lies mir ein Märchen vor", "read_any_story"),
    ("de-de", "erzähl mir ein Märchen", "read_any_story"),
    ("de-de", "kannst du mir eine Geschichte vorlesen", "read_any_story"),
    ("de-de", "erzähl uns bitte eine Geschichte", "read_any_story"),
    ("de-de", "erzähl mir eine geschichte über aschenputtel", "read_content"),
    ("de-de", "lies mir eine grimm-Geschichte", "read_by_collection"),
    ("de-de", "lies mir die Nachrichten vor", None),
    ("de-de", "erzähl mir einen Witz", None),
    ("es-es", "cuéntame un cuento", "read_any_story"),
    ("it-it", "raccontami una fiaba", "read_any_story"),
    ("nl-nl", "lees me een sprookje voor", "read_any_story"),
    ("pt-pt", "conta-me uma história", "read_any_story"),
    ("es-es", "cuéntame un chiste", None),
    ("it-it", "raccontami una barzelletta", None),
    ("nl-nl", "vertel me een mop", None),
    ("pt-pt", "conta-me uma piada", None),
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
    result = container.calc_intent("read me my horoscope")
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


def test_region_and_case_variants_share_the_language_container(plugin):
    """ovos-core hands match() "fr-FR"; a Canadian device says "fr-CA".
    Both are French: same locale folder, same trained container."""
    french = plugin._get_intent_container("fr-fr")
    assert plugin._get_intent_container("fr-FR") is french
    assert plugin._get_intent_container("fr-CA") is french
    assert french.calc_intent("raconte-moi une histoire").get("name") == "read_any_story"

