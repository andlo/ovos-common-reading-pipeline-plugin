"""A request for the news belongs to news skills. They come later in the
pipeline than this plugin, so match() must leave it alone - in every
language that used to claim it - while still claiming stories.

These go through match() with the real bundled locale files: the intents no
longer list a word for the news, and the open slots that can still capture
one ("read the {title}", "read me today's {content_type}") are declined
against locale/<lang>/news.voc."""
import pytest

from conftest import announce_typical_providers, session_message

NEWS = [
    # the bare "read the {title}" line took all of these, title and all
    ("en-us", "read the news"),
    ("en-us", "read me the news"),
    ("en-us", "tell me the news"),
    ("en-us", "can you read me the news"),
    ("en-us", "please read the news"),
    ("en-us", "read me the latest news about france"),
    ("en-us", "tell me the latest news"),
    ("en-us", "read me the news about the election"),
    ("en-us", "read the headlines"),
    ("en-us", "read me the latest BBC News"),
    # "my/today's {content_type}"
    ("en-us", "read me today's news"),
    ("en-us", "read me my news briefing"),
    # "a piece of news" was one of the kinds of text the intents listed
    ("en-us", "read me a piece of news about france"),
    ("en-us", "read me the latest piece of news about france"),
    ("da-dk", "læs nyheden om frankrig"),
    ("da-dk", "læs mig den seneste nyhed om frankrig"),
    ("da-dk", "fortæl mig en nyhed om valget"),
    ("da-dk", "læs mig dagens nyheder"),
    ("da-dk", "læs dagens avis for mig"),
    ("de-de", "lies mir eine Nachricht über Frankreich"),
    ("de-de", "erzähl mir eine Nachricht über die Wahl"),
    ("es-es", "léeme una noticia sobre Francia"),
    ("es-es", "¿puedes leerme una noticia sobre Francia"),
    ("it-it", "leggimi una notizia su Francia"),
    ("it-it", "puoi raccontarmi una notizia su le elezioni"),
    ("nl-nl", "lees me een nieuwsbericht over Frankrijk"),
    ("pt-pt", "lê-me uma notícia sobre França"),
    ("pt-pt", "podes ler-me uma notícia sobre França"),
    # never claimed, and still not
    ("fr-fr", "lis-moi les nouvelles"),
    ("fr-fr", "lis-moi les dernières nouvelles sur la France"),
    ("de-de", "lies mir die Nachrichten vor"),
]

STORIES = [
    ("en-us", "read the story Rapunzel", "read_content", "rapunzel"),
    ("en-us", "tell me the story Cinderella", "read_content", "cinderella"),
    ("en-us", "read me the little mermaid", "read_content", "the little mermaid"),
    ("en-us", "tell me a story about the ugly duckling", "read_content", "the ugly duckling"),
    ("en-us", "read me the latest post from ovosblog", "read_by_collection", None),
    ("en-us", "read me today's horoscope", "read_by_type", None),
    ("en-us", "tell me a story", "read_any_story", None),
    ("da-dk", "læs historien om rapunzel", "read_content", "rapunzel"),
    ("da-dk", "fortæl mig eventyret om den grimme ælling", "read_content", "den grimme ælling"),
    ("de-de", "erzähl mir die Geschichte Rapunzel", "read_content", "rapunzel"),
    ("es-es", "cuéntame el cuento Cenicienta", "read_content", "cenicienta"),
    ("it-it", "raccontami la storia Cenerentola", "read_content", "cenerentola"),
    ("nl-nl", "vertel me het verhaal Assepoester", "read_content", "assepoester"),
    ("pt-pt", "conta-me a história Cinderela", "read_content", "cinderela"),
    ("fr-fr", "raconte-moi l'histoire la biche blanche", "read_content", "biche blanche"),
    # kept on purpose: in a reading request "une nouvelle" is the literary
    # short story as often as a news item, and French asks for the news in
    # the plural ("les nouvelles", above)
    ("fr-fr", "lis-moi une nouvelle sur la mer", "read_content", "mer"),
]


@pytest.fixture(scope="module")
def trained():
    return {}  # locale folder -> container, trained once for the whole module


@pytest.fixture
def plugin(plugin, trained):
    plugin._intent_containers = trained
    announce_typical_providers(plugin)
    return plugin


@pytest.mark.parametrize("lang,utterance", NEWS)
def test_a_request_for_the_news_is_left_to_news_skills(plugin, lang, utterance):
    assert plugin.match([utterance], lang, session_message(lang=lang)) is None


@pytest.mark.parametrize("lang,utterance,intent,title", STORIES)
def test_stories_are_still_claimed(plugin, lang, utterance, intent, title):
    result = plugin.match([utterance], lang, session_message(lang=lang))

    assert result is not None, f"{utterance!r} in {lang} was not claimed"
    assert result.match_type == f"{plugin.skill_id}:{intent}"
    if title is not None:
        assert result.match_data["title"].lower() == title


def test_the_next_hypothesis_is_tried_after_a_news_one(plugin):
    """match() gets every STT hypothesis; declining one for the news must not
    stop it looking at the others."""
    result = plugin.match(["read the news", "read the snow queen"], "en-us", session_message())

    assert result is not None
    assert result.utterance == "read the snow queen"


def test_news_is_matched_as_a_word_not_inside_one(plugin):
    assert plugin._asks_for_news({"title": "gavin newsom"}, "en-us") is False
    assert plugin._asks_for_news({"title": "the news"}, "en-us") is True
    assert plugin._asks_for_news({"title": "Latest  NEWS from France"}, "en-us") is True
    assert plugin._asks_for_news({"content_type": "news briefing"}, "en-us") is True
    assert plugin._asks_for_news({"content_type": "horoscope"}, "en-us") is False


def test_a_language_without_a_news_list_declines_nothing(plugin):
    """fr-fr has no news.voc: none of its slots can capture the news as the
    kind of text asked for."""
    assert plugin._asks_for_news({"title": "les actualités"}, "fr-fr") is False
