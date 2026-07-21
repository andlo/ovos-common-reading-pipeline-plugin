#!/usr/bin/env python3
"""Rebuild ReadContent.intent, ReadContentByCollection.intent and
continue.intent for all languages, avoiding padacioso's unreliable
'(word| )' empty-alternative syntax (confirmed to silently fail to match
when the optional word is omitted) - every optional word is instead
written out as full separate alternative lines. Also adds natural
'about'/'sobre'/'über' connector-word phrasings that were missing
entirely from the original patterns (found via live testing), and
broadens content-type vocabulary beyond just 'story' (story/tale/
article/news/document/report) - this is a general reading pipeline now,
not just a storyteller.

Note on grammatical gender: German/Spanish/French/Italian/Portuguese
decline their indefinite article by noun gender ('eine Geschichte' but
'ein Artikel'/'einen Bericht'; 'un cuento' but 'una noticia'). Rather
than factor out a shared article (which would produce wrong pairings),
each full 'article+noun' combination is written out as its own
alternation branch. English's 'a'/'an' is handled the same way for the
same reason - simpler here, but still safest to just enumerate rather
than assume a single shared article works with every noun."""
from pathlib import Path

ROOT = Path("/home/andlo/ovos-common-reading-pipeline-plugin/locale")

# content-noun phrases (with grammatically correct article), per language
NOUNS = {
    "en-us": "(a story|a tale|an article|a piece of news|a document|a report)",
    "da-dk": "(en historie|en artikel|en nyhed|et dokument|en rapport)",
    "de-de": "(eine Geschichte|einen Artikel|eine Nachricht|ein Dokument|einen Bericht)",
    "es-es": "(un cuento|un artículo|una noticia|un documento|un informe)",
    "fr-fr": "(une histoire|un article|une nouvelle|un document|un rapport)",
    "it-it": "(una storia|un articolo|una notizia|un documento|un rapporto)",
    "nl-nl": "(een verhaal|een artikel|een nieuwsbericht|een document|een rapport)",
    "pt-pt": "(uma história|um artigo|uma notícia|um documento|um relatório)",
}

READ_CONTENT = {
    # NOTE: deliberately no bare 'Tell me a story {title}' pattern - it's
    # ambiguous with ReadContentByCollection's 'Tell me a story from
    # {collection}' (both score equally, tie-break is unpredictable, see
    # git history for the real failure this caused - 'tell me a story
    # from grimm' was parsed as a *title* 'from grimm'). Every remaining
    # pattern has a distinguishing connector word.
    "en-us": [f"Tell me {NOUNS['en-us']} about {{title}}", f"Read me {NOUNS['en-us']} about {{title}}",
              "Tell me the story {title}", "Tell me the article {title}",
              "Read me the story {title}", "Read me the article {title}",
              "Tell me about {title}"],
    "da-dk": [f"Fortæl mig {NOUNS['da-dk']} om {{title}}", f"Læs mig {NOUNS['da-dk']} om {{title}}",
              "Fortæl mig historien {title}", "Fortæl mig artiklen {title}",
              "Læs mig historien {title}", "Fortæl mig om {title}"],
    "de-de": [f"Erzähl mir {NOUNS['de-de']} über {{title}}", f"Lies mir {NOUNS['de-de']} über {{title}}",
              "Erzähl mir die Geschichte {title}", "Erzähl mir den Artikel {title}",
              "Lies mir die Geschichte {title}", "Erzähl mir von {title}"],
    "es-es": [f"Cuéntame {NOUNS['es-es']} sobre {{title}}", f"Léeme {NOUNS['es-es']} sobre {{title}}",
              "Cuéntame el cuento {title}", "Cuéntame el artículo {title}",
              "Léeme el cuento {title}", "Cuéntame sobre {title}"],
    "fr-fr": [f"Raconte-moi {NOUNS['fr-fr']} sur {{title}}", f"Lis-moi {NOUNS['fr-fr']} sur {{title}}",
              "Raconte-moi l'histoire {title}", "Raconte-moi l'article {title}",
              "Lis-moi l'histoire {title}", "Parle-moi de {title}"],
    "it-it": [f"Raccontami {NOUNS['it-it']} su {{title}}", f"Leggimi {NOUNS['it-it']} su {{title}}",
              "Raccontami la storia {title}", "Raccontami l'articolo {title}",
              "Leggimi la storia {title}", "Parlami di {title}"],
    "nl-nl": [f"Vertel me {NOUNS['nl-nl']} over {{title}}", f"Lees me {NOUNS['nl-nl']} over {{title}}",
              "Vertel me het verhaal {title}", "Vertel me het artikel {title}",
              "Lees me het verhaal {title}", "Vertel me over {title}"],
    "pt-pt": [f"Conta-me {NOUNS['pt-pt']} sobre {{title}}", f"Lê-me {NOUNS['pt-pt']} sobre {{title}}",
              "Conta-me a história {title}", "Conta-me o artigo {title}",
              "Lê-me a história {title}", "Fala-me sobre {title}"],
}

READ_BY_COLLECTION = {
    "en-us": [f"Tell me {NOUNS['en-us']} from {{collection}}", f"Read me {NOUNS['en-us']} from {{collection}}",
              "Tell me the story {title} from {collection}", "Read me the story {title} from {collection}",
              "Tell me a story by {collection}", "Tell me a {collection} story",
              "Tell me a {collection} story about {title}", "Find {title} by {collection}"],
    "da-dk": [f"Fortæl mig {NOUNS['da-dk']} fra {{collection}}", f"Læs mig {NOUNS['da-dk']} fra {{collection}}",
              "Fortæl mig historien {title} fra {collection}", "Fortæl mig en historie af {collection}",
              "Fortæl mig en {collection}-historie", "Fortæl mig en {collection}-historie om {title}",
              "Find {title} af {collection}"],
    "de-de": [f"Erzähl mir {NOUNS['de-de']} von {{collection}}", f"Lies mir {NOUNS['de-de']} von {{collection}}",
              "Erzähl mir die Geschichte {title} von {collection}", "Erzähl mir eine {collection}-Geschichte",
              "Erzähl mir eine {collection}-Geschichte über {title}", "Finde {title} von {collection}"],
    "es-es": [f"Cuéntame {NOUNS['es-es']} de {{collection}}", f"Léeme {NOUNS['es-es']} de {{collection}}",
              "Cuéntame el cuento {title} de {collection}", "Cuéntame un cuento de {collection} sobre {title}",
              "Busca {title} de {collection}"],
    "fr-fr": [f"Raconte-moi {NOUNS['fr-fr']} de {{collection}}", f"Lis-moi {NOUNS['fr-fr']} de {{collection}}",
              "Raconte-moi l'histoire {title} de {collection}",
              "Raconte-moi une histoire de {collection} sur {title}", "Trouve {title} de {collection}"],
    "it-it": [f"Raccontami {NOUNS['it-it']} di {{collection}}", f"Leggimi {NOUNS['it-it']} di {{collection}}",
              "Raccontami la storia {title} di {collection}",
              "Raccontami una storia di {collection} su {title}", "Trova {title} di {collection}"],
    "nl-nl": [f"Vertel me {NOUNS['nl-nl']} van {{collection}}", f"Lees me {NOUNS['nl-nl']} van {{collection}}",
              "Vertel me het verhaal {title} van {collection}", "Vertel me een {collection}-verhaal",
              "Vertel me een {collection}-verhaal over {title}", "Zoek {title} van {collection}"],
    "pt-pt": [f"Conta-me {NOUNS['pt-pt']} de {{collection}}", f"Lê-me {NOUNS['pt-pt']} de {{collection}}",
              "Conta-me a história {title} de {collection}",
              "Conta-me uma história de {collection} sobre {title}", "Encontra {title} de {collection}"],
}

CONTINUE = {
    "en-us": ["Continue telling the story", "Continue telling the tale", "Continue reading",
              "Continue the story", "Continue story", "Continue"],
    "da-dk": ["Fortsæt historien", "Fortsæt med at læse", "Fortsæt"],
    "de-de": ["Erzähl die Geschichte weiter", "Lies weiter", "Mach weiter", "Weiter"],
    "es-es": ["Continúa el cuento", "Sigue leyendo", "Continúa"],
    "fr-fr": ["Continue l'histoire", "Continue de lire", "Continue"],
    "it-it": ["Continua la storia", "Continua a leggere", "Continua"],
    "nl-nl": ["Ga verder met het verhaal", "Ga verder met lezen", "Ga verder"],
    "pt-pt": ["Continua a história", "Continua a ler", "Continua"],
}

for lang, lines in READ_CONTENT.items():
    (ROOT / lang / "ReadContent.intent").write_text("\n".join(lines) + "\n", encoding="utf-8")
for lang, lines in READ_BY_COLLECTION.items():
    (ROOT / lang / "ReadContentByCollection.intent").write_text("\n".join(lines) + "\n", encoding="utf-8")
for lang, lines in CONTINUE.items():
    (ROOT / lang / "continue.intent").write_text("\n".join(lines) + "\n", encoding="utf-8")

print("Rewrote ReadContent.intent, ReadContentByCollection.intent, continue.intent for all 8 languages")
