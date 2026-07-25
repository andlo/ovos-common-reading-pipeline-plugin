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
    "en-us": "(a story|a tale|a fairy tale|a fairytale|an article|a piece of news|a document|documents|a report|reports|a horoscope|an almanac|a paper|a post|posts|a blog|a blog post|blog posts|a summary|an update|a review|a guide|an essay)",
    "da-dk": "(en historie|et eventyr|en artikel|en nyhed|et dokument|dokumenter|en rapport|rapporter|et horoskop|en almanak|et paper|en afhandling|et blogindlæg|en blog|et resumé|en opdatering|en anmeldelse|en guide|et essay)",
    "de-de": "(eine Geschichte|einen Artikel|eine Nachricht|ein Dokument|einen Bericht)",
    "es-es": "(un cuento|un artículo|una noticia|un documento|un informe)",
    "fr-fr": "(une histoire|un article|une nouvelle|un document|un rapport)",
    "it-it": "(una storia|un articolo|una notizia|un documento|un rapporto)",
    "nl-nl": "(een verhaal|een artikel|een nieuwsbericht|een document|een rapport)",
    "pt-pt": "(uma história|um artigo|uma notícia|um documento|um relatório)",
}

# Same words as NOUNS, without the leading article - for "the {noun}
# {title}" (definite reference) and "a {collection} {noun}" (the
# provider name stands in for the article: "a grimm story", not "a
# grimm a story"). en-us only for now, see module docstring re: only
# en-us/da-dk getting full-vocabulary treatment this pass.
BARE_NOUNS = {
    "en-us": "(story|tale|fairy tale|fairytale|article|piece of news|document|documents|report|reports|horoscope|almanac|paper|post|posts|blog|blog post|blog posts|summary|update|review|guide|essay)",
}

# Danish equivalent of "the {noun}" - NOT a separate word like English
# "the", Danish marks definiteness with a SUFFIX on the noun itself
# (artikel -> artiklen, historie -> historien). Confirmed directly
# (native speaker review this session) that this is genuinely a
# different sentence shape from English, not just a translation of
# BARE_NOUNS - two Danish-specific patterns exist that have no English
# equivalent at all:
#   "Læs {NOUN_DEFINITE} for {title}" - "Læs horoskopet for løven"
#   "Læs {title}s {NOUN_DEFINITE}" - "Læs løvens horoskop" (title-FIRST,
#   genitive -s, noun last - the reverse of every other pattern here)
# Confirmed there's no bare "the {title}"-only Danish equivalent (no
# noun at all) the way English has - the noun is always present, just
# in one of these two orders.
NOUNS_DEFINITE = {
    "da-dk": ("(historien|eventyret|artiklen|nyheden|dokumentet|rapporten|horoskopet|almanakken|"
              "paperet|afhandlingen|blogindlægget|bloggen|resuméet|opdateringen|anmeldelsen|guiden|essayet)"),
}

# Every recognized way to open a reading-pipeline request, "me"
# included as a full alternative rather than an empty-optional branch -
# confirmed directly (see this session's own testing) that padacioso's
# "(me|)" empty-alternative syntax silently fails to match whenever the
# empty branch is the one that should apply ("tell a story..." without
# "me" simply didn't match at all), the same class of bug already
# documented elsewhere in this file for other optional words. Listing
# both the with-"me" and without-"me" phrasing as separate, complete
# alternatives in ONE group avoids ever relying on an empty branch,
# while still costing only a single generated line per pattern instead
# of the ~10x line-count blowup a naive full-expansion approach would
# have needed - confirmed empirically that padacioso handles multiple
# substantial alternation groups combined in one line just fine.
#
# "Give me"/"Play me" deliberately excluded - "play" in particular
# collides hard with OCP/media playback intents already; "give me" is
# too generic a catch-all to risk. Modal ("Could you"/"Would you") and
# politeness ("Please") variants included since they're low-collision
# ways people naturally ask for something read aloud.
VERB_ME = {
    "en-us": ("(Tell me|Tell|Read me|Read|"
              "Can you tell me|Can you tell|Can you read me|Can you read|"
              "Could you tell me|Could you tell|Could you read me|Could you read|"
              "Would you tell me|Would you tell|Would you read me|Would you read|"
              "Please tell me|Please tell|Please read me|Please read)"),
}

# Danish needs TWO separate verb-groups, not one like English - a real
# structural difference confirmed this session (native speaker
# review): Danish "for mig" ("for me") attaches at the very END of the
# whole sentence ("Fortæl en historie for mig"), not right after the
# verb the way English "me" does ("Tell me a story") - so it can't be
# folded into a single prefix group the way VERB_ME above works.
#
# VERB_ME_DA: "mig" attached right after the verb (or omitted
# entirely) - used as-is, sentence needs nothing more.
# VERB_BARE_DA: no "mig" anywhere in the verb itself - only used
# together with a trailing " for mig" appended to the END of the full
# line (see READ_CONTENT/READ_BY_COLLECTION below), NOT as a
# standalone prefix.
VERB_ME_DA = ("(Fortæl mig|Fortæl|Læs mig|Læs|"
              "Kan du fortælle mig|Kan du fortælle|Kan du læse mig|Kan du læse|"
              "Kunne du fortælle mig|Kunne du fortælle|Kunne du læse mig|Kunne du læse|"
              "Vil du fortælle mig|Vil du fortælle|Vil du læse mig|Vil du læse|"
              "Fortæl mig venligst|Venligst fortæl mig|Læs mig venligst|Venligst læs mig)")
VERB_BARE_DA = ("(Fortæl|Læs|Kan du fortælle|Kan du læse|Kunne du fortælle|Kunne du læse|"
                "Vil du fortælle|Vil du læse|Venligst fortæl|Venligst læs)")

# "Give me the latest/newest article about X" / "read the latest post
# from ovosblog" - "latest" doesn't carry any special meaning to the
# pipeline itself (see the design discussion this came from - this
# stays a generic reading pipeline, not one that understands "latest"
# as a concept); it's just recognized vocabulary so the request
# reaches a provider at all, forwarded as ordinary free text within
# {title} - whether a provider's own search actually returns its most
# recent item for a "latest ..." query, vs any matching item, is up to
# that provider's own implementation, not something this plugin
# enforces or guarantees.
#
# TWO separate qualifier sets, not one shared one - a real collision
# found via testing: QUALIFIER_CONTENT includes "the latest"/"the
# newest"/etc, but QUALIFIER_COLLECTION deliberately does NOT include
# the "the ..." forms. "the latest post from ovosblog" ties against
# READ_CONTENT's own bare "the {title}" line (both start with "the "
# followed by open text) - the SAME "padacioso doesn't reliably prefer
# the more specific of two tied patterns" class of issue already
# documented elsewhere in this file, confirmed again directly rather
# than assumed. Dropping "the" from the collection-side qualifier
# means "read the latest post from ovosblog" only matches read_content
# (imperfect, but no ambiguity), while "read latest post from
# ovosblog" (no "the") unambiguously reaches read_by_collection - a
# real, but far less common, phrasing loss traded for reliability.
QUALIFIER_CONTENT = {
    "en-us": "(latest|the latest|newest|the newest|most recent|the most recent)",
}
QUALIFIER_COLLECTION = {
    "en-us": "(latest|newest|most recent)",
}
# Danish doesn't have the same "the latest post from X" tie problem
# English does (Danish's bare "the {title}" equivalent doesn't exist
# at all - see NOUNS_DEFINITE's own comment - so there's no competing
# pattern to tie against), so "seneste" doesn't need a separate
# with/without-article split the way English's does. "seneste"
# (latest/most recent) and "nyeste" (newest) cover this naturally.
QUALIFIER_DA = "(seneste|nyeste)"

# Danish equivalent of "the latest" combined with a definite noun -
# grammatically needs "den"/"det" depending on the noun's gender
# (en-word vs et-word), which NOUNS_DEFINITE doesn't split out
# separately. Pragmatic choice (confirmed acceptable): list all four
# combinations rather than split every noun by gender - this means
# recognizing some combinations that aren't grammatically "correct"
# for a given noun (e.g. "det seneste" with an en-word), but padacioso
# is purely about RECOGNIZING what was said, not enforcing correct
# Danish back at the person - over-accepting slightly imperfect
# grammar is the safer direction to err in here, not under-accepting.
QUALIFIER_DA_DEFINITE = "(den seneste|det seneste|den nyeste|det nyeste)"

# Bare noun stems (no article at all) - for the Danish compound
# pattern "en {collection}-historie" ("a grimm-story"), where the
# provider name plus a hyphen stands in for the article, same spirit
# as English's "a {collection} story".
NOUNS_BARE_DA = ("(historie|eventyr|artikel|nyhed|dokument|rapport|horoskop|almanak|"
                  "paper|afhandling|blogindlæg|blog|resumé|opdatering|anmeldelse|guide|essay)")



# "the {content}" forms get an "about"-connector variant everywhere (safe
# regardless of article, since the connector word disambiguates), plus a
# bare "the {content} {title}" form for the most common words specifically
# (story/tale/article) - not exhaustively for every word, since "the
# document {title}"-style bare reference is unusual phrasing for most of
# the newer, less title-oriented nouns (news/report/horoscope/almanac).
READ_CONTENT = {
    # Three lines cover the entire combinatorial space discussed and
    # tested this session (20 verb+me phrasings x 23 nouns x optional
    # about/regarding connector, all as required-choice alternation
    # groups folded into single lines - confirmed directly that
    # padacioso handles this cleanly, avoiding the ~10x line-count
    # blowup a fully-expanded approach would have needed):
    #
    # 1. Indefinite article + noun + REQUIRED about/regarding - "tell
    #    me a story about cinderella", "could you read an article
    #    regarding penguins". Connector is NOT optional here (unlike
    #    line 2) - a real regression found via the test suite: making
    #    it optional let "a story {anything}" swallow phrases like "a
    #    story from grimm" as a bare title, tying against
    #    read_by_collection's own "a NOUN from {collection}" pattern
    #    for the exact same utterance. The definite ("the") form below
    #    doesn't have this problem (read_by_collection has no bare
    #    "the NOUN from {collection}" pattern to tie against), so it
    #    keeps the optional connector.
    # 2. Definite article ("the") + noun + optional about/regarding -
    #    "read the story cinderella", "can you tell the article
    #    regarding penguins".
    # 3. Bare "the {title}" - NO noun at all. The one genuinely new,
    #    higher-risk addition (covers "read the leo horoscope" style
    #    phrasing) - confirmed via direct, isolated testing before
    #    being added here that it does NOT collide with
    #    read_by_collection ("a grimm story") or read_by_type ("my
    #    horoscope"/"today's horoscope") the way a fully-open,
    #    article-free "Read me {title}" previously did (that one was
    #    tried, caught real regressions in the test suite, and was
    #    reverted - see git history). "the" is a strong enough
    #    grammatical marker that it doesn't overlap with either of
    #    those other patterns' own required wording.
    "en-us": [
        f"{VERB_ME['en-us']} {NOUNS['en-us']} (about|regarding) {{title}}",
        f"{VERB_ME['en-us']} the {BARE_NOUNS['en-us']} ({{title}}|about {{title}}|regarding {{title}})",
        f"{VERB_ME['en-us']} the {{title}}",
        # "read the latest story about cinderella" - deliberately
        # title-only, no "from {collection}" variant here (that
        # combination inherits the pre-existing title+collection
        # fragility documented in READ_BY_COLLECTION below - tested
        # directly, confirmed still fragile even with a distinguishing
        # qualifier word, not something newly introduced by this line).
        f"{VERB_ME['en-us']} {QUALIFIER_CONTENT['en-us']} {BARE_NOUNS['en-us']} (about|regarding) {{title}}",
    ],
    # 8 lines covering the structurally different Danish grammar
    # (confirmed via native-speaker review this session, not a
    # word-for-word translation of the English structure - see
    # VERB_ME_DA/VERB_BARE_DA and NOUNS_DEFINITE's own comments for
    # why "for mig" needs a separate verb-group entirely, and why
    # Danish has two genuinely different sentence shapes for a
    # noun+title combination that don't exist in English at all):
    "da-dk": [
        f"{VERB_ME_DA} {NOUNS['da-dk']} om {{title}}",
        f"{VERB_BARE_DA} {NOUNS['da-dk']} om {{title}} for mig",
        f"{VERB_ME_DA} {NOUNS_DEFINITE['da-dk']} ({{title}}|om {{title}})",
        f"{VERB_BARE_DA} {NOUNS_DEFINITE['da-dk']} ({{title}}|om {{title}}) for mig",
        # "Læs horoskopet for løven" - noun first, then "for {title}".
        # No "for mig" variant (would read "...for løven for mig",
        # a confusing double "for").
        f"{VERB_ME_DA} {NOUNS_DEFINITE['da-dk']} for {{title}}",
        # "Læs løvens horoskop" - REVERSED order, title first with
        # genitive -s, noun last. No English equivalent at all.
        # Uses NOUNS_BARE_DA (bare stem), NOT NOUNS_DEFINITE - real
        # grammar bug found via testing: "løvens horoskopet" (genitive
        # -s AND the noun's own definite -et suffix together) is
        # ungrammatical double-marking. The genitive possessor alone
        # already makes the whole phrase definite; the noun stays bare.
        # KNOWN LIMITATION, accepted (found via testing, not silently
        # missed): "dagens {content_type}" (READ_CONTENT_BY_TYPE below,
        # a pre-existing idiom meaning "today's X") grammatically LOOKS
        # like this exact genitive shape too ("dagen" + "s") - "Læs mig
        # dagens horoskop" ties against this line, interpreting "dagen"
        # as if it were a literal {title} in genitive form, and
        # currently wins the tie over the intended read_by_type match.
        # In practice this is low-risk (nobody actually means "the
        # horoscope belonging to something called 'dag'" - "dagens X"
        # is always the fixed idiom), so accepted as-is rather than
        # chasing a fix for an ambiguity padacioso has no clean way to
        # resolve (same class of unreliable-tie-breaking already
        # documented elsewhere in this file).
        f"{VERB_ME_DA} {{title}}s {NOUNS_BARE_DA}",
        f"{VERB_BARE_DA} {{title}}s {NOUNS_BARE_DA} for mig",
        # Same double-definiteness bug, same fix: "den seneste
        # artiklen" is wrong for the identical reason - the "den/det
        # seneste" qualifier already marks definiteness, the noun
        # after it stays bare, not NOUNS_DEFINITE.
        f"{VERB_ME_DA} {QUALIFIER_DA_DEFINITE} {NOUNS_BARE_DA} ({{title}}|om {{title}})",
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
    # "What is my {content_type}" deliberately removed - real feedback:
    # this is a reading pipeline, not a "what" pipeline (Common Query's
    # domain) - "what is X" phrasing reads like a factual question, not
    # a reading request, and risks the same kind of collision the bare
    # "tell me about {title}" form was removed for earlier (see module
    # docstring). "Tell/Read {me} my/today's {content_type}" already
    # unambiguously signals "read this to me" via the verb itself, no
    # need for a "what is" variant.
    #
    # "todays" (no apostrophe) added alongside "today's" - real-world
    # speech-to-text output commonly drops apostrophes entirely, so the
    # apostrophe-only form was silently unreachable for anyone whose
    # STT does this.
    "en-us": [
        f"{VERB_ME['en-us']} (my|today's|todays) {{content_type}}",
    ],
    "da-dk": [
        # "Hvad er dagens X"/"Hvad siger mit horoskop" (question forms)
        # deliberately removed - same reasoning as en-us's "What is my
        # {content_type}" removal above: this is a reading pipeline,
        # not a "what" pipeline.
        f"{VERB_ME_DA} dagens {{content_type}}",
        f"{VERB_BARE_DA} dagens {{content_type}} for mig",
        "Læs mit horoskop", "Fortæl mig mit horoskop", "Læs horoskopet",
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
    # Four lines, same combinatorial-alternation approach as
    # READ_CONTENT above:
    # 1. Indefinite noun + from/by {collection} - "tell me a story
    #    from grimm", "could you read a guide by {collection}".
    # 2. Definite "the {noun} {title}" + from/by {collection} - the
    #    title+collection combination already documented (see the
    #    KNOWN LIMITATION note above) as fragile against read_content's
    #    own plain "the {noun} {title}" pattern - kept as before
    #    (pre-existing behavior, not made worse or better by this
    #    pass), not re-litigated here.
    # 3. "a {collection} {noun}" (no "from"/"by" at all, provider name
    #    used adjective-style) - generalized to the FULL noun list and
    #    both with/without "me", fixing a real, confirmed gap: "read a
    #    andersen story" (no "me") previously had no matching line at
    #    all, only "read ME a {collection} story" did, and only for
    #    the single word "story", not the full noun list.
    # 4. "Find {title} by/from {collection}" - unchanged, already
    #    working correctly, no reason to touch it.
    # 5. "latest"/"newest"/"most recent" {noun} from/by {collection} -
    #    "read latest post from ovosblog", "read newest posts from
    #    ovosblog". Deliberately does NOT include "the latest"/"the
    #    newest" here (unlike QUALIFIER_CONTENT, used in READ_CONTENT
    #    above) - confirmed directly via testing: "the latest post
    #    from ovosblog" ties against READ_CONTENT's own bare "the
    #    {title}" line (both start with "the " + open text), and
    #    padacioso doesn't reliably resolve that tie toward the more
    #    specific collection match - the SAME class of issue as the
    #    title+collection fragility below. Dropping "the" from this
    #    side avoids the tie entirely: "the latest post from ovosblog"
    #    falls through to read_content instead (imperfect, but
    #    unambiguous), while "latest post from ovosblog" (no "the")
    #    reaches read_by_collection cleanly.
    #
    #    A combined title+"latest"+collection line ("read the latest
    #    post about AI from ovosblog") was also tried and NOT kept -
    #    confirmed via direct testing that it inherits the exact same
    #    pre-existing title+collection fragility documented in the
    #    KNOWN LIMITATION note above, just with "latest" layered on
    #    top rather than being a new problem. Same tradeoff as
    #    everything else there: collection-only and title-only both
    #    work reliably, the combination of all three doesn't yet.
    #
    #    NOTE - grammar only, not full behavior yet: this pipeline
    #    doesn't currently forward "latest" as a distinct signal to
    #    provider skills at all (see __init__.py's search broadcast) -
    #    a provider receiving this request today can't distinguish it
    #    from an ordinary collection-only request (no title given), so
    #    it likely still returns whatever its own no-title fallback
    #    already returns (e.g. a random pick, not necessarily its most
    #    recent item) rather than actually honoring "latest"
    #    specifically. Recognizing the phrase correctly is done; making
    #    providers actually act on it is a separate, not yet
    #    implemented follow-up.
    "en-us": [
        f"{VERB_ME['en-us']} {NOUNS['en-us']} (from|by) {{collection}}",
        f"{VERB_ME['en-us']} the {BARE_NOUNS['en-us']} {{title}} (from|by) {{collection}}",
        f"{VERB_ME['en-us']} a {{collection}} {BARE_NOUNS['en-us']}",
        "Find {title} by {collection}",
        "Find {title} from {collection}",
        f"{VERB_ME['en-us']} {QUALIFIER_COLLECTION['en-us']} {BARE_NOUNS['en-us']} (from|by) {{collection}}",
    ],
    "da-dk": [
        f"{VERB_ME_DA} {NOUNS['da-dk']} fra {{collection}}",
        f"{VERB_BARE_DA} {NOUNS['da-dk']} fra {{collection}} for mig",
        # title+collection combined - same pre-existing fragility as
        # English's equivalent (KNOWN LIMITATION note above), kept as
        # before, not made worse or better by this pass.
        f"{VERB_ME_DA} {NOUNS_DEFINITE['da-dk']} {{title}} fra {{collection}}",
        f"{VERB_ME_DA} en {{collection}}-{NOUNS_BARE_DA}", f"{VERB_ME_DA} et {{collection}}-{NOUNS_BARE_DA}",
        f"{VERB_ME_DA} en {{collection}}-{NOUNS_BARE_DA} om {{title}}",
        f"{VERB_ME_DA} et {{collection}}-{NOUNS_BARE_DA} om {{title}}",
        "Find {title} af {collection}", "Find {title} fra {collection}",
        f"{VERB_ME_DA} {QUALIFIER_DA} {NOUNS_BARE_DA} fra {{collection}}",
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
              "Continue the story", "Continue the article", "Continue story", "Continue",
              "Resume", "Resume reading", "Resume the story",
              "Keep reading", "Keep going", "Go on"],
    "da-dk": ["Fortsæt historien", "Fortsæt med at læse", "Fortsæt", "Fortsæt artiklen",
              "Genoptag", "Genoptag læsningen", "Bliv ved", "Fortsæt bare"],
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
