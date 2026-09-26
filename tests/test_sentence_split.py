"""split_sentences() and migrate_bookmark() - what the reader hands to TTS.

The old split was para.split('. '): "Mr. Fox" became two sentences, '!' and
'?' never ended one, and a long sentence with no period could run past the
15s wait_while_speaking timeout (#35).
"""
import pytest

from conftest import module

split_sentences = module.split_sentences
migrate_bookmark = module.migrate_bookmark
MAX_SPOKEN_CHARS = module.MAX_SPOKEN_CHARS


@pytest.mark.parametrize("text,expected", [
    ("Is it you? Yes! It is.", ["Is it you?", "Yes!", "It is."]),
    ("He waited… Then he left.", ["He waited…", "Then he left."]),
    ("He waited... then he left.", ["He waited... then he left."]),
    ("Mr. Fox met Dr. Owl.", ["Mr. Fox met Dr. Owl."]),
    ("H. C. Andersen wrote it. The end.", ["H. C. Andersen wrote it.", "The end."]),
    ("In 1805. Then it rained.", ["In 1805.", "Then it rained."]),
    ("Den 1. januar kom sneen. Så smeltede den.", ["Den 1. januar kom sneen.", "Så smeltede den."]),
    ("Am 3. Mai war es warm. Dann nicht mehr.", ["Am 3. Mai war es warm.", "Dann nicht mehr."]),
    ("Man sagt z.B. dies. Und das.", ["Man sagt z.B. dies.", "Und das."]),
    ("M. Dupont arriva. Il pleuvait.", ["M. Dupont arriva.", "Il pleuvait."]),
])
def test_sentences_end_where_a_reader_would_stop(text, expected):
    assert split_sentences(text) == expected


@pytest.mark.parametrize("text,expected", [
    ('"Oh!" said the princess. Then she slept.', ['"Oh!" said the princess.', "Then she slept."]),
    ("“Help!” She ran.", ["“Help!”", "She ran."]),
    ("»Hej!« sagde han. Så gik han.", ["»Hej!« sagde han.", "Så gik han."]),
    ("„Hilfe!“ Sie lief davon.", ["„Hilfe!“", "Sie lief davon."]),
    ("« Bonjour ! » dit-il. Puis il partit.", ["« Bonjour ! » dit-il.", "Puis il partit."]),
    ("« Au revoir ! » Il partit.", ["« Au revoir ! »", "Il partit."]),
    ("Han gik. »Hej!« sagde hun.", ["Han gik.", "»Hej!« sagde hun."]),
])
def test_dialogue_keeps_its_quotes_and_its_attribution(text, expected):
    assert split_sentences(text) == expected


def test_the_long_sentence_from_issue_35_is_cut_at_a_clause():
    sentence = ("And every night I will rise up and pray for you -- in winter that you may be "
                "able to warm yourself at a fire, and in summer that you may not faint away in "
                "the heat, and so on and on for ever and ever.")
    chunks = split_sentences(sentence)
    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_SPOKEN_CHARS for chunk in chunks)
    assert chunks[0].endswith(",") or chunks[0].endswith("--")
    assert " ".join(chunks).split() == sentence.split()


def test_a_sentence_with_no_clause_boundary_is_cut_at_a_space():
    sentence = " ".join(["word"] * 80) + "."
    chunks = split_sentences(sentence)
    assert all(len(chunk) <= MAX_SPOKEN_CHARS for chunk in chunks)
    assert " ".join(chunks).split() == sentence.split()


@pytest.mark.parametrize("text", [
    "One. Two! Three? Four… five... six. «Sept» « huit » „neun“ »ti« end",
    "Mr. and Mrs. Dursley, of number four, Privet Drive, were proud to say that they were "
    "perfectly normal, thank you very much; they were the last people you'd expect to be "
    "involved in anything strange or mysterious, because they just didn't hold with such "
    "nonsense -- not at all.",
    "", "   ", "no terminator at all",
])
def test_no_word_is_ever_lost_or_reordered(text):
    assert " ".join(split_sentences(text)).split() == text.split()


def test_an_old_bookmark_moves_to_the_first_word_not_yet_heard():
    paragraphs = ["Mr. Fox came home. He ran.", "The end"]
    # old chunks: ["Mr", "Fox came home", "He ran.", "The end"]; 2 of them heard
    # = "Mr Fox came home"; the new chunk holding the next word is "He ran."
    assert migrate_bookmark(paragraphs, 2) == 1
    # one old chunk heard ("Mr"): its sentence is started, not finished - hear it again
    assert migrate_bookmark(paragraphs, 1) == 0
    assert migrate_bookmark(paragraphs, 0) == 0
    assert migrate_bookmark(paragraphs, 4) == 3


@pytest.mark.parametrize("text, expected", [
    # the usual Danish spelling, no space between the initials
    ("H.C. Andersen skrev det i 1835. Det blev trykt.",
     ["H.C. Andersen skrev det i 1835.", "Det blev trykt."]),
    ("Eventyret er af H.C. Andersen. Det er kort.",
     ["Eventyret er af H.C. Andersen.", "Det er kort."]),
    ("J.R.R. Tolkien wrote it. It is long.",
     ["J.R.R. Tolkien wrote it.", "It is long."]),
    # the spaced spelling keeps working
    ("H. C. Andersen skrev det. Det blev trykt.",
     ["H. C. Andersen skrev det.", "Det blev trykt."]),
])
def test_dotted_initials_do_not_end_a_sentence(text, expected):
    assert split_sentences(text) == expected
