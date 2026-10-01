"""Opt-in SSML narration (#40): each sentence can carry an SSML version of
itself in data["utterance_ssml"], beside the plain data["utterance"], which
never changes. Off unless the config or the settings say
{"narration": "ssml"}."""
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest

from conftest import CommonReadingPipeline, dispatch_message, module, session_message

narrate = module.narrate
START, PARAGRAPH = module.STORY_START_BREAK_MS, module.PARAGRAPH_BREAK_MS


def _text(ssml):
    """The words an SSML renderer reads, whitespace collapsed."""
    return " ".join("".join(ET.fromstring(ssml).itertext()).split())


def _breaks(ssml):
    return [b.get("time") for b in ET.fromstring(ssml).iter("break")]


# --- the SSML itself -----------------------------------------------------------

@pytest.mark.parametrize("sentence", [
    "Tom & Jerry ate 3 < 4 cakes > 2 pies.",
    'He said "yes" and she said \'no\'.',
    "“Who’s there?” asked the wolf.",
    "‘What ails you, dear wife?’",
    "«Qu'allons-nous faire pour gagner notre vie?",
    "« Bonjour ! » dit-il, « entrez. »",
    "Sie rief: „Hilfe!“ und lief davon.",
    "»Hej!« sagde hun, og gik.",
    "Il était une fois, à Noël, un garçon très âgé; ça alors!",
    "Ærø, Øresund og Åbenrå: søen var stille.",
    "<speak>not a tag</speak> &amp; not an entity",
])
def test_the_ssml_is_well_formed_and_says_the_same_words(sentence):
    ssml = narrate(sentence)

    root = ET.fromstring(ssml)  # raises on anything that isn't well-formed
    assert root.tag == "speak"
    assert _text(ssml) == sentence


def test_characters_xml_cannot_carry_are_dropped():
    ssml = narrate("A bell\x07 rang\x0b twice.")

    assert _text(ssml) == "A bell rang twice."


def test_a_pause_can_lead_the_sentence():
    ssml = narrate("Once upon a time.", PARAGRAPH)

    assert ssml == f'<speak><break time="{PARAGRAPH}ms"/>Once upon a time.</speak>'
    assert narrate("Once upon a time.") == "<speak>Once upon a time.</speak>"


def test_a_dash_after_the_end_of_a_sentence_is_a_change_of_speaker():
    """How Cosquin's Gutenberg text marks the next speaker."""
    ssml = narrate("Faut-il encore être si maltraité?—Si tu te plains encore,» répondait l'autre.")

    assert _breaks(ssml) == [f"{module.SPEAKER_CHANGE_BREAK_MS}ms"]
    assert _text(ssml) == "Faut-il encore être si maltraité? Si tu te plains encore,» répondait l'autre."
    assert _breaks(narrate("dit le loup.—«Et moi aussi,» dit le chevreuil.")) == ["300ms"]


def test_a_dash_between_words_is_a_brief_pause():
    ssml = narrate("I think—I know I think—it might be little Kay.")

    assert _breaks(ssml) == [f"{module.DASH_BREAK_MS}ms"] * 2
    assert _text(ssml) == "I think I know I think it might be little Kay."
    assert _breaks(narrate("The Prince -- for such he was -- rode on.")) == ["200ms"] * 2
    assert _breaks(narrate("Then – they said – nothing.")) == ["200ms"] * 2


def test_a_closing_quote_after_a_dash_stays_with_its_words():
    ssml = narrate("‘But—’ and then he would get behind her.")

    assert ssml == '<speak>‘But’ <break time="200ms"/> and then he would get behind her.</speak>'


@pytest.mark.parametrize("sentence", [
    "From 1805–1812 they lived there.",  # a range
    "Pages 10 – 12 are missing.",
    "— Bonjour, dit-il.",  # a dash that opens the line
    "And then—",  # one that ends it
    "A well-known looking-glass.",  # hyphens
])
def test_dashes_that_are_not_asides_are_left_alone(sentence):
    assert narrate(sentence) == f"<speak>{sentence}</speak>"


def test_an_ellipsis_is_written_the_way_the_voice_pauses_on_it():
    assert narrate("He waited… then he left.") == \
        f'<speak>He waited... <break time="{module.ELLIPSIS_BREAK_MS}ms"/> then he left.</speak>'
    assert narrate("He waited... then he left.") == narrate("He waited… then he left.")
    # at the end, or before the closing quote, the next sentence is its own speak
    assert narrate("He waited…") == "<speak>He waited...</speak>"
    assert narrate("‘I wonder…’ she said.") == "<speak>‘I wonder...’ she said.</speak>"


def test_quoted_dialogue_is_left_to_the_voice():
    sentence = "‘Oh!’ he implored, ‘pardon my presumption; necessity alone drove me to the deed.’"

    assert narrate(sentence) == f"<speak>{sentence}</speak>"


# --- turning it on ------------------------------------------------------------

def _wire(plugin, paragraphs):
    plugin.speak = MagicMock()
    plugin.speak_dialog = MagicMock()
    plugin._speak_ssml = MagicMock()
    plugin._fetch_content = MagicMock(return_value=paragraphs)


def _read(plugin, bookmark=0):
    message = session_message()
    reading = plugin._begin_reading(message, {"skill_id": "p.a", "content_id": "c", "title": "T"})
    plugin._read_content(message, reading, bookmark)


STORY = ["Once upon a time there was a king. He had three sons.",
         "The eldest was proud—far too proud. The youngest was kind."]
SENTENCES = ["Once upon a time there was a king.", "He had three sons.",
             "The eldest was proud—far too proud.", "The youngest was kind."]


def test_narration_is_off_by_default(plugin):
    _wire(plugin, STORY)

    _read(plugin)

    assert [c.args[0] for c in plugin.speak.call_args_list] == SENTENCES
    plugin._speak_ssml.assert_not_called()


@pytest.mark.parametrize("where", ["config", "settings"])
def test_narration_is_turned_on_by_the_config_or_the_settings(plugin, where):
    _wire(plugin, STORY)
    if where == "config":
        plugin.config = {"narration": "ssml"}  # intents["ovos-common-reading-pipeline-plugin"]
    else:
        plugin.settings["narration"] = "ssml"

    _read(plugin)

    plugin.speak.assert_not_called()
    calls = plugin._speak_ssml.call_args_list
    # the plain text is exactly what it was; the reader paces it, not speak()
    assert [c.args[0] for c in calls] == SENTENCES
    assert all("wait" not in c.kwargs for c in calls)
    ssml = [c.args[1] for c in calls]
    assert ssml == [
        f'<speak><break time="{START}ms"/>Once upon a time there was a king.</speak>',
        "<speak>He had three sons.</speak>",
        f'<speak><break time="{PARAGRAPH}ms"/>The eldest was proud <break time="200ms"/> far too proud.</speak>',
        "<speak>The youngest was kind.</speak>",
    ]


def test_the_config_can_turn_it_off_over_the_settings(plugin):
    _wire(plugin, STORY)
    plugin.config = {"narration": "off"}
    plugin.settings["narration"] = "ssml"

    _read(plugin)

    plugin._speak_ssml.assert_not_called()


def test_a_resumed_story_starts_with_the_lead_in_pause(plugin):
    """After "Continuing ...", the first sentence heard gets the pause the
    announcement gets, even in the middle of a paragraph."""
    _wire(plugin, STORY)
    plugin.config = {"narration": "SSML"}
    key = CommonReadingPipeline._progress_key({"skill_id": "p.a", "content_id": "c"})
    plugin.settings["sessions"] = {"default": {"progress_splitter": {key: module.SPLITTER_VERSION}}}

    _read(plugin, bookmark=1)

    ssml = [c.args[1] for c in plugin._speak_ssml.call_args_list]
    assert ssml[0] == f'<speak><break time="{START}ms"/>He had three sons.</speak>'
    assert ssml[1].startswith(f'<speak><break time="{PARAGRAPH}ms"/>The eldest')


# --- the message ----------------------------------------------------------------

def test_the_narrated_speak_is_speak_with_one_more_field(plugin, monkeypatch):
    """ovos-workshop's speak() takes no extra data; _speak_ssml() is its code
    with utterance_ssml added. Same topic, context (session, route,
    skill_id), data and meta, from the same message on the stack."""
    waits = []
    monkeypatch.setattr(module.SessionManager, "wait_while_speaking",
                        lambda timeout, session: waits.append((timeout, session.session_id, session.is_speaking)))
    ssml = "<speak>Il était une fois.</speak>"

    def reader(message):  # the message is found on the stack, as in _read_sentences
        plugin.speak("Il était une fois.", wait=7)
        plugin._speak_ssml("Il était une fois.", ssml, wait=7)

    reader(dispatch_message("alice", lang="fr-FR"))

    plain, narrated = [c.args[0] for c in plugin.bus.emit.call_args_list]
    assert narrated.msg_type == plain.msg_type == module.SPEAK_TOPIC
    assert narrated.context == plain.context
    assert narrated.context["session"]["session_id"] == "alice"
    assert narrated.context["skill_id"] == plugin.skill_id
    data = dict(narrated.data)
    assert data.pop("utterance_ssml") == ssml
    assert data == plain.data
    assert waits == [(7, "alice", True), (7, "alice", True)]


def test_without_a_wait_nothing_is_waited_for(plugin, monkeypatch):
    waited = MagicMock()
    monkeypatch.setattr(module.SessionManager, "wait_while_speaking", waited)

    plugin._speak_ssml("Hello.", "<speak>Hello.</speak>")

    waited.assert_not_called()
    (sent,), _ = plugin.bus.emit.call_args
    assert sent.data["utterance"] == "Hello."
