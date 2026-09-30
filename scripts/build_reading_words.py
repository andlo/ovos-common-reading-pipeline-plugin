#!/usr/bin/env python3
"""Write locale/<lang>/reading.json - the words match() uses to take a
reading request apart (see "How a request is recognised" in README.md).

Recognition works like OCP's: the sentence has to start with a reading
verb ("tell me", "read me", "fortæl mig", "lies mir"), and what follows
has to name something a provider has told the pipeline about - a kind of
text ("story", "horoscope", "article"), a collection ("grimm",
"andersen") or, for the low stage, a title. The pipeline itself only
knows the words that take the sentence apart; the vocabulary of what can
be read comes from the providers (ovos.common_reading.vocabulary), plus
the story words below so the story providers work out of the box.

Keys:
- verbs: how a request opens, longest match wins. Includes the modal
  forms ("can you tell me") and, for languages that put the verb last
  ("Kannst du mir eine Geschichte erzählen", "Lies mir ... vor"), the
  opening part; the closing part is in "suffixes".
- suffixes: words that close a request and carry no meaning ("please",
  "for mig", "vor", "vorlesen"). Stripped from the end, repeatedly.
- about: connectors in front of a title ("about", "om", "über").
- from: connectors in front of a collection ("from", "by", "fra").
- filler: articles, possessives and the like, dropped around the title
  ("a", "the", "my", "today's", "another").
- latest: "latest"/"newest" - dropped; a provider asked for a kind of
  text with no title answers with its newest (or a random) item anyway.
- content_types: the pipeline's own kinds of text, canonical name ->
  the words for it. Only stories: every other kind comes from the
  providers that serve it, so the pipeline never claims "tell me the
  weather report" just because "report" is a word for a kind of text.

Hyphens and apostrophes are spaces here and in the utterance ("raconte-
moi" = "raconte moi", "l'histoire" = "l histoire"), and accents are
ignored, so each word is listed once.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "locale"

WORDS = {
    "en-us": {
        "verbs": ["tell me", "tell us", "tell", "read me", "read us", "read", "read to me", "read out",
                  "can you tell me", "can you tell", "can you read me", "can you read",
                  "could you tell me", "could you tell", "could you read me", "could you read",
                  "would you tell me", "would you tell", "would you read me", "would you read",
                  "please tell me", "please tell", "please read me", "please read", "find"],
        "suffixes": ["please", "to me", "for me", "to us", "for us", "out loud", "aloud"],
        "about": ["about", "regarding", "on", "of", "for", "called", "named"],
        "from": ["from", "by"],
        "filler": ["a", "an", "the", "some", "another", "other", "one", "me", "my", "our",
                   "today", "todays", "today s", "daily", "any", "something"],
        "latest": ["latest", "newest", "most recent", "recent"],
        "content_types": {"story": ["story", "stories", "tale", "tales", "fairy tale", "fairy tales",
                                    "fairytale", "fairytales", "bedtime story", "bedtime stories"]},
    },
    "da-dk": {
        "verbs": ["fortæl mig", "fortæl os", "fortæl", "læs mig", "læs os", "læs", "læs op",
                  "kan du fortælle mig", "kan du fortælle", "kan du læse mig", "kan du læse",
                  "kunne du fortælle mig", "kunne du fortælle", "kunne du læse mig", "kunne du læse",
                  "vil du fortælle mig", "vil du fortælle", "vil du læse mig", "vil du læse",
                  "fortæl mig venligst", "venligst fortæl mig", "venligst fortæl",
                  "læs mig venligst", "venligst læs mig", "venligst læs", "find"],
        "suffixes": ["op for mig", "for mig", "op for os", "for os", "op", "tak", "venligst"],
        "about": ["om", "omkring", "for", "der hedder", "kaldet"],
        "from": ["fra", "af"],
        "filler": ["en", "et", "den", "det", "de", "min", "mit", "mine", "vores", "dagens", "i dag",
                   "noget", "nogle", "anden", "andet", "andre"],
        "latest": ["seneste", "nyeste", "den seneste", "det seneste", "den nyeste", "det nyeste"],
        "content_types": {"story": ["historie", "historien", "historier", "eventyr", "eventyret",
                                    "eventyrene", "godnathistorie", "godnathistorien",
                                    "fortælling", "fortællingen"]},
    },
    "de-de": {
        "verbs": ["erzähl mir", "erzähle mir", "erzähl uns", "erzähle uns", "erzähl", "erzähle",
                  "lies mir", "lies uns", "lies", "lies vor",
                  "kannst du mir", "kannst du uns", "könntest du mir", "könntest du uns",
                  "würdest du mir", "würdest du uns", "finde"],
        "suffixes": ["bitte", "vor", "erzählen", "vorlesen", "vorlesen bitte"],
        "about": ["über", "namens"],
        "from": ["von", "aus"],
        "filler": ["ein", "eine", "einen", "einem", "der", "die", "das", "den", "dem", "des", "noch",
                   "mir", "uns", "mein", "meine", "meinen", "heutige", "heutigen", "bitte", "andere",
                   "erzählen", "vorlesen"],
        "latest": ["neueste", "neuesten", "letzte", "letzten"],
        "content_types": {"story": ["geschichte", "geschichten", "märchen", "gutenachtgeschichte",
                                    "gutenachtgeschichten"]},
    },
    "es-es": {
        "verbs": ["cuéntame", "cuéntanos", "léeme", "léenos", "cuenta", "lee",
                  "puedes contarme", "puedes contarnos", "puedes leerme", "puedes leernos",
                  "podrías contarme", "podrías contarnos", "podrías leerme", "podrías leernos", "busca"],
        "suffixes": ["por favor"],
        "about": ["sobre", "acerca de", "llamado", "llamada"],
        "from": ["de", "por"],
        "filler": ["un", "una", "unos", "unas", "el", "la", "los", "las", "otro", "otra", "mi", "me",
                   "de hoy"],
        "latest": ["último", "última", "más reciente"],
        "content_types": {"story": ["cuento", "cuentos", "historia", "historias", "cuento para dormir"]},
    },
    "fr-fr": {
        "verbs": ["raconte moi", "raconte nous", "raconte", "lis moi", "lis nous", "lis",
                  "racontez moi", "racontez nous", "lisez moi", "lisez nous",
                  "tu peux me", "tu peux nous", "tu pourrais me", "tu pourrais nous",
                  "peux tu me", "peux tu nous", "pourrais tu me", "pourrais tu nous",
                  "vous pouvez me", "pouvez vous me", "pouvez vous nous",
                  "pourriez vous me", "pourriez vous nous", "trouve"],
        "suffixes": ["s il te plait", "s il vous plait", "raconter", "lire"],
        "about": ["sur", "a propos de", "intitule", "intitulee"],
        "from": ["de", "par"],
        "filler": ["un", "une", "le", "la", "les", "l", "des", "du", "d", "autre", "mon", "ma", "mes",
                   "moi", "nous", "d aujourd hui", "raconter", "lire"],
        "latest": ["dernier", "derniere", "plus recent", "plus recente"],
        "content_types": {"story": ["histoire", "histoires", "conte", "contes", "conte de fees",
                                    "contes de fees", "histoire pour dormir"]},
    },
    "it-it": {
        "verbs": ["raccontami", "raccontaci", "leggimi", "leggici", "racconta", "leggi",
                  "puoi raccontarmi", "puoi raccontarci", "puoi leggermi", "puoi leggerci",
                  "potresti raccontarmi", "potresti raccontarci", "potresti leggermi", "potresti leggerci",
                  "trova"],
        "suffixes": ["per favore"],
        "about": ["su", "sul", "sulla", "sullo", "sui", "sugli", "sulle", "intitolato", "intitolata"],
        "from": ["di", "da", "dei", "dei fratelli"],
        "filler": ["un", "una", "uno", "il", "lo", "la", "i", "gli", "le", "l", "un", "altra", "altro",
                   "mia", "mio", "di oggi"],
        "latest": ["ultimo", "ultima", "piu recente"],
        "content_types": {"story": ["storia", "storie", "fiaba", "fiabe", "favola", "favole",
                                    "storia della buonanotte"]},
    },
    "nl-nl": {
        "verbs": ["vertel me", "vertel mij", "vertel ons", "vertel", "lees me", "lees mij", "lees ons",
                  "lees", "lees voor",
                  "kun je me", "kun je mij", "kun je ons", "kan je me", "kan je mij", "kan je ons",
                  "wil je me", "wil je mij", "wil je ons", "zoek"],
        "suffixes": ["voor", "vertellen", "voorlezen", "alsjeblieft", "alstublieft"],
        "about": ["over", "genaamd"],
        "from": ["van", "uit"],
        "filler": ["een", "het", "de", "nog", "mijn", "ons", "van vandaag", "vertellen", "voorlezen"],
        "latest": ["nieuwste", "laatste"],
        "content_types": {"story": ["verhaal", "verhaaltje", "verhalen", "sprookje", "sprookjes"]},
    },
    "pt-pt": {
        "verbs": ["conta me", "conta nos", "le me", "le nos", "conta", "le",
                  "podes contar me", "podes contar nos", "podes ler me", "podes ler nos",
                  "podias contar me", "podias ler me", "encontra"],
        "suffixes": ["por favor"],
        "about": ["sobre", "chamado", "chamada"],
        "from": ["de", "por"],
        "filler": ["um", "uma", "o", "a", "os", "as", "outra", "outro", "minha", "meu", "de hoje"],
        "latest": ["ultimo", "ultima", "mais recente"],
        "content_types": {"story": ["historia", "historias", "conto", "contos", "historia para dormir"]},
    },
}

for lang, words in WORDS.items():
    path = ROOT / lang / "reading.json"
    path.write_text(json.dumps(words, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote reading.json for {', '.join(WORDS)}")
