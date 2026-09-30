"""match() against the real bundled locale files (reading.json,
continue.intent, pause.intent) and a realistic set of provider
vocabularies (conftest.announce_typical_providers): which sentences are
claimed, as what, in every language."""
import pytest
from ovos_bus_client.message import Message

from conftest import announce, announce_typical_providers, module, session_message


@pytest.fixture
def plugin(plugin):
    announce_typical_providers(plugin)
    return plugin


def _intent(plugin, lang, phrase):
    result = plugin.match([phrase], lang, session_message(lang=lang))
    return result.match_type.split(":")[-1] if result else None


@pytest.mark.parametrize("lang,phrase,expected_intent", [
    ("en-us", "tell me a story about cinderella", "read_content"),
    ("en-us", "tell me an article about the weather", "read_content"),
    ("en-us", "tell me a story from grimm", "read_by_collection"),
    ("en-us", "read me a grimm story", "read_by_collection"),
    ("da-dk", "læs mig en grimm-historie", "read_by_collection"),
    ("de-de", "lies mir eine grimm-Geschichte", "read_by_collection"),
    ("es-es", "léeme un cuento de grimm", "read_by_collection"),
    ("fr-fr", "lis-moi une histoire de grimm", "read_by_collection"),
    ("it-it", "leggimi una storia di grimm", "read_by_collection"),
    ("nl-nl", "lees me een grimm-verhaal", "read_by_collection"),
    ("pt-pt", "lê-me uma história de grimm", "read_by_collection"),
    ("en-us", "tell me about abraham lincoln", None),
    ("en-us", "tell me the story about the little mermaid", "read_content"),
    ("en-us", "tell the story cinderella", "read_content"),  # "me" is optional
    ("en-us", "tell me a fairytale about the ugly duckling", "read_content"),
    ("en-us", "read me my horoscope", "read_by_type"),
    ("en-us", "what is my horoscope", None),  # a question, not a reading request
    ("en-us", "read me today's horoscope", "read_by_type"),
    ("en-us", "read me my almanac", "read_by_type"),
    ("en-us", "read me an article", "read_by_type"),
    ("en-us", "find cinderella from archive", "read_by_collection"),
    ("da-dk", "fortæl mig en historie om askepot", "read_content"),
    ("da-dk", "fortæl mig en historie fra grimm", "read_by_collection"),
    ("da-dk", "fortsæt", None),  # nothing to continue in this session
    ("da-dk", "fortæl mig historien om den lille havfrue", "read_content"),
    ("da-dk", "fortæl historien askepot", "read_content"),  # "mig" is optional
    ("da-dk", "læs mit horoskop", "read_by_type"),
    ("da-dk", "læs løvens horoskop", "read_content"),
    ("da-dk", "hvad er dagens horoskop", None),
    ("de-de", "erzähl mir eine geschichte über aschenputtel", "read_content"),
    ("de-de", "erzähl mir eine geschichte von grimm", "read_by_collection"),
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
    ("en-us", "can you read me an article about boiling an egg", "read_content"),
    ("en-us", "can you read a story about cinderella", "read_content"),
    ("en-us", "can you tell me a story about the little mermaid", "read_content"),
    ("da-dk", "kan du læse mig en historie om askepot", "read_content"),
    ("da-dk", "kan du fortælle mig en historie om den lille havfrue", "read_content"),
    # "tell me a story": no title, the providers pick one
    ("en-us", "tell me a story", "read_any_story"),
    ("en-us", "Tell me a fairy tale", "read_any_story"),
    ("en-us", "read me a bedtime story", "read_any_story"),
    ("en-us", "can you tell me another story", "read_any_story"),
    ("en-us", "tell me a story please", "read_any_story"),
    ("en-us", "tell me a joke", None),
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
    ("fr-fr", "raconte-moi une histoire de cosquin", "read_by_collection"),
    ("fr-fr", "lis-moi une nouvelle sur la mer", "read_content"),
    ("fr-fr", "lis-moi les nouvelles", None),
    ("fr-fr", "raconte-moi une blague", None),
    ("de-de", "erzähl mir eine Geschichte", "read_any_story"),
    ("de-de", "erzähle mir eine geschichte", "read_any_story"),
    ("de-de", "lies mir ein Märchen vor", "read_any_story"),
    ("de-de", "erzähl mir ein Märchen", "read_any_story"),
    ("de-de", "kannst du mir eine Geschichte vorlesen", "read_any_story"),
    ("de-de", "erzähl uns bitte eine Geschichte", "read_any_story"),
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
def test_sentences_are_claimed_as(plugin, lang, phrase, expected_intent):
    assert _intent(plugin, lang, phrase) == expected_intent, f"{phrase!r} in {lang}"


# Issue #50: live on a testing-channel install these went to read_content,
# ahead of the weather and date-time skills they belong to.
OTHER_SKILLS = [
    "can you tell me the weather", "can you tell me the weather in here",
    "can you tell me the weather currently", "can you tell me the weather right now",
    "tell me the current day", "tell me the current day in Africa",
    "can you tell me the day", "can you tell me the day of the month",
    "can you tell me the day of the calendar", "tell me the year", "tell me the current year",
    "tell me the present year", "tell me the time again please", "tell me the time",
    "tell me today's weather report", "read my messages", "read the shopping list",
    "read me my emails", "tell me a joke",
]


@pytest.mark.parametrize("phrase", OTHER_SKILLS)
def test_other_skills_sentences_are_left_alone(plugin, phrase):
    assert plugin.match([phrase], "en-us", session_message()) is None


def test_the_entities_that_reach_the_handler(plugin):
    result = plugin.match(["tell me my leo horoscope"], "en-us", session_message())
    assert result.match_data == {"content_type": "horoscope", "title": "leo"}  # #33

    result = plugin.match(["read me my horoscope"], "en-us", session_message())
    assert result.match_data == {"content_type": "horoscope"}

    result = plugin.match(["read latest post from ovosblog"], "en-us", session_message())
    assert result.match_type.endswith(":read_by_collection")
    assert result.match_data == {"content_type": "post", "collection": "ovosblog"}


def test_collection_and_title_together(plugin):
    """Used to lose "from andersen" into the title (padacioso tied the two
    patterns). Taken apart word by word now."""
    result = plugin.match(["tell me the story about the little mermaid from andersen"], "en-us",
                          session_message())
    assert result.match_type.endswith(":read_by_collection")
    assert result.match_data == {"content_type": "story", "collection": "andersen",
                                 "title": "The Little Mermaid"}


def test_a_title_a_provider_announced_goes_out_as_announced(plugin):
    result = plugin.match(["tell me a story about the ugly ducklin"], "en-us", session_message())
    assert result.match_data["title"] == "The Ugly Duckling"


@pytest.mark.parametrize("phrase,title", [
    ("tell me the little mermaid", "The Little Mermaid"),
    ("read me the snow queen", "The Snow Queen"),
    ("read me rapunzel", "Rapunzel"),
])
def test_a_bare_known_title_is_claimed_at_the_low_stage(plugin, phrase, title):
    assert plugin.match_high([phrase], "en-us", session_message()) is None
    result = plugin.match_low([phrase], "en-us", session_message())
    assert result.match_type.endswith(":read_content")
    assert result.match_data == {"title": title}


def test_a_bare_unknown_title_is_not_claimed(plugin):
    for phrase in ("tell me the weather", "read me the tinder", "tell me the time",
                   "read me the little mermaids adventures in space"):
        assert plugin.match_low([phrase], "en-us", session_message()) is None, phrase


def test_danish_bare_title(plugin):
    result = plugin.match_low(["læs den lille havfrue"], "da-dk", session_message(lang="da-dk"))
    assert result.match_data == {"title": "Den lille havfrue"}


def test_a_new_kind_of_text_needs_no_pipeline_release(plugin):
    """#36: a provider that announces "recipe" is reachable at once."""
    assert plugin.match(["read me a recipe"], "en-us", session_message()) is None
    announce(plugin, "recipes.test", "en-us", content_types={"recipe": ["recipe", "recipes"]})
    result = plugin.match(["read me a recipe for pancakes"], "en-us", session_message())
    assert result.match_data == {"content_type": "recipe", "title": "pancakes"}


def test_a_provider_that_goes_away_takes_its_words_with_it(plugin):
    assert plugin.match(["read me my horoscope"], "en-us", session_message()) is not None
    plugin._handle_vocabulary(Message(module.COMMON_READING_VOCABULARY,
                                      {"skill_id": "horoscope.test", "remove": True}))
    assert plugin.match(["read me my horoscope"], "en-us", session_message()) is None


def test_vocabulary_is_per_language(plugin):
    """The horoscope provider announced English and Danish words only."""
    assert plugin.match(["lies mir mein Horoskop"], "de-de", session_message(lang="de-de")) is None


def test_the_pipeline_asks_loaded_providers_for_their_vocabulary(plugin):
    plugin._request_vocabulary()
    sent = [c.args[0] for c in plugin.bus.emit.call_args_list]
    assert [m.msg_type for m in sent] == [module.COMMON_READING_VOCABULARY_GET]


def test_unsupported_language_falls_back_to_english(plugin):
    assert _intent(plugin, "xx-xx", "tell me a story about cinderella") == "read_content"


def test_intent_container_is_cached_per_language(plugin):
    first = plugin._get_intent_container("en-us")
    second = plugin._get_intent_container("en-us")
    assert first is second


def test_region_and_case_variants_share_the_language_words(plugin):
    """ovos-core hands match() "fr-FR"; a Canadian device says "fr-CA"."""
    french = plugin._get_intent_container("fr-fr")
    assert plugin._get_intent_container("fr-FR") is french
    assert plugin._get_intent_container("fr-CA") is french
    assert _intent(plugin, "fr-CA", "raconte-moi une histoire") == "read_any_story"
    assert _intent(plugin, "fr-FR", "raconte-moi une histoire") == "read_any_story"


def test_continue_and_pause_are_still_sentences(plugin):
    assert plugin._get_intent_container("en-us").calc_intent("continue")["name"] == "continue"
    assert plugin._get_intent_container("en-us").calc_intent("pause")["name"] == "pause"
