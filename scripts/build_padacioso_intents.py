#!/usr/bin/env python3
"""Rebuild ReadContent.intent, ReadContentByCollection.intent,
ReadContentByType.intent, and continue.intent for all languages,
avoiding padacioso's unreliable '(word| )' empty-alternative syntax
(confirmed to silently fail to match when the optional word is
omitted) - every optional word (including "me", articles, connectors)
is instead written out as full separate alternative lines. Also adds
natural 'about'/'sobre'/'über' connector-word phrasings, and broadens
content-type vocabulary (story/tale/fairy tale/article/news/document/
report/horoscope/almanac) - this is a general reading pipeline now,
not just a storyteller.

Real gaps found via user testing that this addresses:
- "Tell me about {title}" (a bare catch-all, no content-type word
  required) collided with other skills' own "tell me about X" phrasing
  (e.g. a Wikipedia/biography skill) - "tell me about abraham lincoln"
  could get mis-routed here instead of to a knowledge-lookup skill.
  Removed entirely; every "Tell" pattern now requires an actual
  content-type word, which "Read" doesn't need to (see below).
- "Tell me the story about the little mermaid" didn't match anything -
  every previous pattern connected the content word directly to
  {title} with no "about"/connector option for the bare "the X"
  forms. Added throughout.
- No way to ask for "my horoscope" or "today's horoscope" without a
  {title} at all - every previous pattern required one. New
  ReadContentByType.intent (en-us, da-dk) covers phrasing like "read
  me my horoscope" / "what is my horoscope" / "read the horoscope",
  with content_type forwarded to provider skills as a search hint (see
  __init__.py's ovos.common_reading.search "content_type" field) so
  e.g. a horoscope-only provider can filter/respond appropriately.
- "me" isn't always present ("tell the story cinderella" is as valid
  as "tell me the story cinderella") - both forms are now generated
  for every pattern, not just the with-"me" one.

Note on grammatical gender: German/Spanish/French/Italian/Portuguese
decline their indefinite article by noun gender ('eine Geschichte' but
'ein Artikel'/'einen Bericht'; 'un cuento' but 'una noticia'). Rather
than factor out a shared article (which would produce wrong pairings),
each full 'article+noun' combination is written out as its own
alternation branch. English's 'a'/'an' is handled the same way for the
same reason - simpler here, but still safest to just enumerate rather
than assume a single shared article works with every noun. Danish
neuter/common gender ('et eventyr' but 'en historie') is handled the
same way in ReadContentByType by avoiding a shared possessive
('min'/'mit') across an open {content_type} wildcard entirely - see
that section's own comment.

Only en-us and da-dk got the full new-vocabulary treatment (fairy
tale/horoscope/almanac, ReadContentByType) in this pass - the other 6
languages only got the two SAFE fixes (removing the collision-prone
bare "about" line, adding the "story about {title}" connector variant
using words already validated elsewhere in this same script) since
getting horoscope/almanac/fairy-tale grammar right in 6 more languages
without a native speaker to check needs more care than a good-faith
guess deserves. Tracked as a follow-up, not silently skipped."""
from pathlib import Path

ROOT = Path("/home/andlo/ovos-common-reading-pipeline-plugin/locale")

# content-noun phrases (with grammatically correct article), per language.
# en-us/da-dk expanded with fairy tale/tale/horoscope/almanac; the other
# 6 keep their original set - see module docstring.
NOUNS = {
    "en-us": "(a story|a tale|a fairy tale|a fairytale|an article|a piece of news|a document|documents|a report|reports|a horoscope|an almanac)",
    "da-dk": "(en historie|et eventyr|en artikel|en nyhed|et dokument|dokumenter|en rapport|rapporter|et horoskop|en almanak)",
    "de-de": "(eine Geschichte|einen Artikel|eine Nachricht|ein Dokument|einen Bericht)",
    "es-es": "(un cuento|un artículo|una noticia|un documento|un informe)",
    "fr-fr": "(une histoire|un article|une nouvelle|un document|un rapport)",
    "it-it": "(una storia|un articolo|una notizia|un documento|un rapporto)",
    "nl-nl": "(een verhaal|een artikel|een nieuwsbericht|een document|een rapport)",
    "pt-pt": "(uma história|um artigo|uma notícia|um documento|um relatório)",
}

# "the {content}" forms get an "about"-connector variant everywhere (safe
# regardless of article, since the connector word disambiguates), plus a
# bare "the {content} {title}" form for the most common words specifically
# (story/tale/article) - not exhaustively for every word, since "the
# document {title}"-style bare reference is unusual phrasing for most of
# the newer, less title-oriented nouns (news/report/horoscope/almanac).
READ_CONTENT = {
    "en-us": [
        f"Tell me {NOUNS['en-us']} about {{title}}", f"Tell {NOUNS['en-us']} about {{title}}",
        f"Read me {NOUNS['en-us']} about {{title}}", f"Read {NOUNS['en-us']} about {{title}}",
        "Tell me the story {title}", "Tell the story {title}",
        "Tell me the story about {title}", "Tell the story about {title}",
        "Tell me the tale {title}", "Tell the tale {title}",
        "Tell me the tale about {title}", "Tell the tale about {title}",
        "Tell me the article {title}", "Tell the article {title}",
        "Tell me the article about {title}", "Tell the article about {title}",
        "Read me the story {title}", "Read the story {title}",
        "Read me the story about {title}", "Read the story about {title}",
        "Read me the tale {title}", "Read the tale {title}",
        "Read me the tale about {title}", "Read the tale about {title}",
        "Read me the article {title}", "Read the article {title}",
        "Read me the article about {title}", "Read the article about {title}",
    ],
    "da-dk": [
        f"Fortæl mig {NOUNS['da-dk']} om {{title}}", f"Fortæl {NOUNS['da-dk']} om {{title}}",
        f"Læs mig {NOUNS['da-dk']} om {{title}}", f"Læs {NOUNS['da-dk']} om {{title}}",
        "Fortæl mig historien {title}", "Fortæl historien {title}",
        "Fortæl mig historien om {title}", "Fortæl historien om {title}",
        "Fortæl mig artiklen {title}", "Fortæl artiklen {title}",
        "Fortæl mig artiklen om {title}", "Fortæl artiklen om {title}",
        "Læs mig historien {title}", "Læs historien {title}",
        "Læs mig historien om {title}", "Læs historien om {title}",
        "Læs mig artiklen {title}", "Læs artiklen {title}",
        "Læs mig artiklen om {title}", "Læs artiklen om {title}",
    ],
    # de/es/fr/it/nl/pt: only the two safe fixes (drop the collision-prone
    # bare line, add the "about"-connector variant on the existing
    # story/article words) - no new vocabulary this pass, see docstring.
    "de-de": [f"Erzähl mir {NOUNS['de-de']} über {{title}}", f"Lies mir {NOUNS['de-de']} über {{title}}",
              "Erzähl mir die Geschichte {title}", "Erzähl mir die Geschichte über {title}",
              "Erzähl mir den Artikel {title}", "Erzähl mir den Artikel über {title}",
              "Lies mir die Geschichte {title}"],
    "es-es": [f"Cuéntame {NOUNS['es-es']} sobre {{title}}", f"Léeme {NOUNS['es-es']} sobre {{title}}",
              "Cuéntame el cuento {title}", "Cuéntame el cuento sobre {title}",
              "Cuéntame el artículo {title}", "Cuéntame el artículo sobre {title}",
              "Léeme el cuento {title}"],
    "fr-fr": [f"Raconte-moi {NOUNS['fr-fr']} sur {{title}}", f"Lis-moi {NOUNS['fr-fr']} sur {{title}}",
              "Raconte-moi l'histoire {title}", "Raconte-moi l'histoire sur {title}",
              "Raconte-moi l'article {title}", "Raconte-moi l'article sur {title}",
              "Lis-moi l'histoire {title}"],
    "it-it": [f"Raccontami {NOUNS['it-it']} su {{title}}", f"Leggimi {NOUNS['it-it']} su {{title}}",
              "Raccontami la storia {title}", "Raccontami la storia su {title}",
              "Raccontami l'articolo {title}", "Raccontami l'articolo su {title}",
              "Leggimi la storia {title}"],
    "nl-nl": [f"Vertel me {NOUNS['nl-nl']} over {{title}}", f"Lees me {NOUNS['nl-nl']} over {{title}}",
              "Vertel me het verhaal {title}", "Vertel me het verhaal over {title}",
              "Vertel me het artikel {title}", "Vertel me het artikel over {title}",
              "Lees me het verhaal {title}"],
    "pt-pt": [f"Conta-me {NOUNS['pt-pt']} sobre {{title}}", f"Lê-me {NOUNS['pt-pt']} sobre {{title}}",
              "Conta-me a história {title}", "Conta-me a história sobre {title}",
              "Conta-me o artigo {title}", "Conta-me o artigo sobre {title}",
              "Lê-me a história {title}"],
}

# content-type-ONLY requests, no {title} at all - "read me my
# horoscope", "what is my horoscope", "read me today's horoscope".
# en-us/da-dk only (see module docstring).
#
# content_type stays a genuinely open, generic wildcard - deliberately
# NOT special-cased per content word (no dedicated "horoscope intent",
# "almanac intent", etc). This pipeline doesn't know or care what
# content types exist, the same way OCP doesn't distinguish jazz from
# disco as a "media type" - it just captures whatever word the user
# said and forwards it as a hint on the search broadcast (see
# COMMON_READING_SEARCH's "content_type" field), letting PROVIDER
# skills decide what they support. Confirmed via live testing this
# works cleanly for horoscope/almanac/weather report/recipe/etc, no
# collisions.
#
# The bare "Read/Tell me the {content_type}" form (no "my"/"today's"
# qualifier) was tried and REMOVED - not just "usually resolves the
# right way", but confirmed via CI running a different Python version
# (3.12) than local testing (3.11/3.14) to be a genuinely
# NON-DETERMINISTIC tie against read_content's "the {noun} about
# {title}" pattern whenever content_type captures one of read_content's
# OWN vocabulary words (story/tale/article/fairytale) followed by
# "about X" - local testing resolved it one way, CI resolved the exact
# same input the OPPOSITE way. A coin-flip across environments is a
# real bug, not a documentable edge case, so the bare "the X" form is
# gone entirely. "my {content_type}"/"today's {content_type}" have NO
# such overlap with read_content's templates (which never contain
# "my"/"today's" at all) and remain fully safe and generic - "read the
# horoscope" (bare, no "my") is consequently NOT supported; "read me
# my horoscope" / "what is my horoscope" / "read me today's horoscope"
# are.
#
# Danish additionally avoids a shared "min"/"mit" possessive across the
# open {content_type} wildcard (grammatical gender - "mit horoskop" but
# "min historie" would be wrong the other way round) by using "dagens"
# (today's - gender-invariant) for the wildcard-based lines, and
# hardcoding a couple of horoscope-specific "mit"/definite forms as
# their own literal (non-wildcard) lines instead.
READ_CONTENT_BY_TYPE = {
    "en-us": [
        "Read me my {content_type}", "Read my {content_type}",
        "Tell me my {content_type}", "Tell my {content_type}",
        "What is my {content_type}",
        "Read me today's {content_type}", "Tell me today's {content_type}",
    ],
    "da-dk": [
        "Læs mig dagens {content_type}", "Fortæl mig dagens {content_type}",
        "Hvad er dagens {content_type}",
        "Læs mit horoskop", "Fortæl mig mit horoskop", "Læs horoskopet",
        "Hvad siger mit horoskop",
    ],
}

# KNOWN LIMITATION (pre-existing, not introduced by the above additions
# - confirmed via live testing): combining BOTH a title AND a collection
# in one utterance ("tell me the story about the little mermaid from
# andersen") is fragile - padacioso ties read_content's plain "the
# story {title}" pattern against read_by_collection's more specific
# "the story {title} from {collection}" one, and the LESS specific
# pattern (read_content, swallowing "from andersen" into the title
# itself) wins more often than not. The BARE "from {collection}" form
# without an explicit title works reliably ("tell me a story from
# grimm", "find {title} from {collection}") - it's specifically the
# combination of both in one utterance that's unreliable. Tracked as a
# follow-up issue rather than silently left undocumented; padacioso
# doesn't appear to consistently prefer the more specific of two tied
# wildcard patterns, so this may need a structurally different
# approach, not just word reordering, to actually fix.
READ_BY_COLLECTION = {
    "en-us": [
        f"Tell me {NOUNS['en-us']} from {{collection}}", f"Tell {NOUNS['en-us']} from {{collection}}",
        f"Read me {NOUNS['en-us']} from {{collection}}", f"Read {NOUNS['en-us']} from {{collection}}",
        "Tell me the story {title} from {collection}", "Tell the story {title} from {collection}",
        "Tell me the story about {title} from {collection}", "Tell the story about {title} from {collection}",
        "Tell me the tale {title} from {collection}", "Tell the tale {title} from {collection}",
        "Tell me the tale about {title} from {collection}", "Tell the tale about {title} from {collection}",
        "Tell me the article {title} from {collection}", "Tell the article {title} from {collection}",
        "Tell me the article about {title} from {collection}", "Tell the article about {title} from {collection}",
        "Read me the story {title} from {collection}", "Read the story {title} from {collection}",
        "Read me the story about {title} from {collection}", "Read the story about {title} from {collection}",
        "Read me the tale {title} from {collection}", "Read the tale {title} from {collection}",
        "Read me the tale about {title} from {collection}", "Read the tale about {title} from {collection}",
        "Read me the article {title} from {collection}", "Read the article {title} from {collection}",
        "Read me the article about {title} from {collection}", "Read the article about {title} from {collection}",
        "Tell me a story by {collection}", "Tell me a {collection} story",
        "Read me a story by {collection}", "Read me a {collection} story",
        "Tell me a {collection} story about {title}", "Read me a {collection} story about {title}",
        "Find {title} by {collection}",
        "Find {title} from {collection}",
    ],
    "da-dk": [
        f"Fortæl mig {NOUNS['da-dk']} fra {{collection}}", f"Fortæl {NOUNS['da-dk']} fra {{collection}}",
        f"Læs mig {NOUNS['da-dk']} fra {{collection}}", f"Læs {NOUNS['da-dk']} fra {{collection}}",
        "Fortæl mig historien {title} fra {collection}", "Fortæl historien {title} fra {collection}",
        "Fortæl mig historien om {title} fra {collection}", "Fortæl historien om {title} fra {collection}",
        "Fortæl mig artiklen {title} fra {collection}", "Fortæl artiklen {title} fra {collection}",
        "Fortæl mig artiklen om {title} fra {collection}", "Fortæl artiklen om {title} fra {collection}",
        "Læs mig historien {title} fra {collection}", "Læs historien {title} fra {collection}",
        "Læs mig historien om {title} fra {collection}", "Læs historien om {title} fra {collection}",
        "Fortæl mig en historie af {collection}", "Læs mig en historie af {collection}",
        "Fortæl mig en {collection}-historie", "Læs mig en {collection}-historie",
        "Fortæl mig en {collection}-historie om {title}", "Læs mig en {collection}-historie om {title}",
        "Find {title} af {collection}", "Find {title} fra {collection}",
    ],
    "de-de": [f"Erzähl mir {NOUNS['de-de']} von {{collection}}", f"Lies mir {NOUNS['de-de']} von {{collection}}",
              "Erzähl mir die Geschichte {title} von {collection}",
              "Erzähl mir eine {collection}-Geschichte", "Lies mir eine {collection}-Geschichte",
              "Erzähl mir eine {collection}-Geschichte über {title}", "Lies mir eine {collection}-Geschichte über {title}",
              "Finde {title} von {collection}"],
    "es-es": [f"Cuéntame {NOUNS['es-es']} de {{collection}}", f"Léeme {NOUNS['es-es']} de {{collection}}",
              "Cuéntame el cuento {title} de {collection}",
              "Cuéntame un cuento de {collection}", "Léeme un cuento de {collection}",
              "Cuéntame un cuento de {collection} sobre {title}", "Léeme un cuento de {collection} sobre {title}",
              "Busca {title} de {collection}"],
    "fr-fr": [f"Raconte-moi {NOUNS['fr-fr']} de {{collection}}", f"Lis-moi {NOUNS['fr-fr']} de {{collection}}",
              "Raconte-moi l'histoire {title} de {collection}",
              "Raconte-moi une histoire de {collection}", "Lis-moi une histoire de {collection}",
              "Raconte-moi une histoire de {collection} sur {title}", "Lis-moi une histoire de {collection} sur {title}",
              "Trouve {title} de {collection}"],
    "it-it": [f"Raccontami {NOUNS['it-it']} di {{collection}}", f"Leggimi {NOUNS['it-it']} di {{collection}}",
              "Raccontami la storia {title} di {collection}",
              "Raccontami una storia di {collection}", "Leggimi una storia di {collection}",
              "Raccontami una storia di {collection} su {title}", "Leggimi una storia di {collection} su {title}",
              "Trova {title} di {collection}"],
    "nl-nl": [f"Vertel me {NOUNS['nl-nl']} van {{collection}}", f"Lees me {NOUNS['nl-nl']} van {{collection}}",
              "Vertel me het verhaal {title} van {collection}",
              "Vertel me een {collection}-verhaal", "Lees me een {collection}-verhaal",
              "Vertel me een {collection}-verhaal over {title}", "Lees me een {collection}-verhaal over {title}",
              "Zoek {title} van {collection}"],
    "pt-pt": [f"Conta-me {NOUNS['pt-pt']} de {{collection}}", f"Lê-me {NOUNS['pt-pt']} de {{collection}}",
              "Conta-me a história {title} de {collection}",
              "Conta-me uma história de {collection}", "Lê-me uma história de {collection}",
              "Conta-me uma história de {collection} sobre {title}", "Lê-me uma história de {collection} sobre {title}",
              "Encontra {title} de {collection}"],
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
for lang, lines in READ_CONTENT_BY_TYPE.items():
    (ROOT / lang / "ReadContentByType.intent").write_text("\n".join(lines) + "\n", encoding="utf-8")
for lang, lines in CONTINUE.items():
    (ROOT / lang / "continue.intent").write_text("\n".join(lines) + "\n", encoding="utf-8")

print("Rewrote ReadContent.intent, ReadContentByCollection.intent, ReadContentByType.intent (en-us/da-dk only), continue.intent")
