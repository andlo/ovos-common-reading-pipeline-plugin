# <img src='story-512.png' card_color='#40DBB0' width='50' height='50' style='vertical-align:bottom'/> Common Tales

Orchestrates "tell me a story" across storyteller *provider* skills - the
same way [OCP](https://openvoiceos.github.io/ovos-technical-manual/ocp/)
(ovos-common-play) orchestrates "play X" across media skills.

_"If you want your children to be intelligent, read them fairy tales. If
you want them to be more intelligent, read them more fairy tales."_
— Albert Einstein

> **What this is:** an orchestrator for **narrating text-based stories
> and fairy tales via TTS** - providers deliver plain text (scraped or
> sourced from places like andersenstories.com, grimmstories.com, or
> Project Gutenberg), and this skill reads it aloud, sentence by
> sentence, with bookmarking and "continue" support.
>
> **What this is *not*:** an audiobook or audio-file player. If you're
> looking for pre-recorded audiobooks, radio dramas, or narrated
> readings as *audio files*, that's already well covered by existing
> **OCP** (ovos-common-play) media skills - e.g. `ovos-skill-librivox`,
> or JarbasSkills' `skill-golden-audiobooks` / `skill-hppodcraft` /
> `skill-epic-horror-theatre`. This skill doesn't compete with those; it
> solves a different problem (arbitrating between multiple *text*
> storyteller skills that would otherwise fight over the same voice
> commands - see "Why does this exist?" below).

[![Tests](https://github.com/andlo/ovos-skill-common-tales/actions/workflows/test.yml/badge.svg)](https://github.com/andlo/ovos-skill-common-tales/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/ovos-skill-common-tales.svg)](https://pypi.org/project/ovos-skill-common-tales/)

## Install
```bash
pip install ovos-skill-common-tales
```

You'll also want at least one *provider* skill installed, otherwise this
skill has nothing to tell:

- [ovos-skill-andersen-tales](https://github.com/andlo/ovos-skill-andersen-tales)
- [ovos-skill-grimm-tales](https://github.com/andlo/ovos-skill-grimm-tales)
- [ovos-skill-andrew-lang-tales](https://github.com/andlo/ovos-skill-andrew-lang-tales)

## Why does this exist?

`ovos-skill-fairytales` and `ovos-skill-worldtales` both register nearly
identical `Tales.intent`/`continue.intent` patterns. Installed together,
Padatious has to pick a winner per utterance based on model confidence -
not on which skill actually *has* the story, or which one has a story in
progress. A bare "continue" is especially bad: it could easily land on
whichever skill *doesn't* have anything to continue.

This skill (plus a family of "provider" skills that own no intents of
their own) fixes that properly:

- **One skill owns the conversation.** Only `ovos-skill-common-tales`
  registers `Tales.intent`/`continue.intent` - provider skills never
  compete with each other or with this skill for an utterance.
- **One skill owns 'continue'.** Bookmark/progress state lives here, in
  one place, keyed by `{provider_skill_id}::{story_id}` - so "continue"
  always resumes the right story, regardless of which provider told it.
- **Consistent announcements.** Before narrating, this skill always
  announces title, author, collection and source (when a provider
  supplies them) in one consistent phrasing, instead of each provider
  skill having its own slightly different wording.

## The `ovos.common_tales.*` bus protocol

Provider skills implement this to be usable by `ovos-skill-common-tales`.
It's a plain messagebus convention (like `ovos.common_play.*`) - no shared
package dependency needed.

### 1. Search

This skill broadcasts, on `Tales.intent` or `TalesByCollection.intent`:

```
ovos.common_tales.search
{
  "phrase": "<what the user asked for, or null for 'surprise me'>",
  "collection_hint": "<raw text like 'grimm' or 'h c andersen', or null>",
  "requester": "<this skill's id>"
}
```

`collection_hint` is set when the user names a specific storyteller/collection
("tell me a story **from Grimm**", "find Cinderella **by Andersen**"). It's
raw, unvalidated text - each provider fuzzy-matches it against its own
known friendly names (see "Friendly names" below) and should only respond
if it's a match, or if `collection_hint` is null (in which case every
provider competes as usual). `phrase` can also be null on its own - "tell
me a story from Grimm" with no specific tale named is a valid request for
the hinted provider to offer something of its own choosing.

Every provider skill that thinks it can help replies (within ~2s):

```
ovos.common_tales.search.response
{
  "skill_id": "<provider skill id>",
  "story_id": "<opaque id the provider will recognize later - e.g. its own title>",
  "title": "<human-readable title>",
  "author": "<author, optional>",
  "collection": "<book/collection name, optional>",
  "source": "<where the text comes from, e.g. 'grimmstories.com'>",
  "confidence": 0.0-1.0
}
```

This skill picks the highest-confidence response (and, if it's below 0.8,
confirms with the user before continuing - same "is it that one?" flow
`ovos-skill-fairytales` already had).

### 2. Fetch

Once a story is chosen (or resumed via "continue"), this skill sends a
*targeted* request to just that provider:

```
ovos.common_tales.fetch_story.<provider_skill_id>
{"story_id": "<from the search response>", "requester": "<this skill's id>"}
```

The provider replies once with the full text, split into paragraphs:

```
ovos.common_tales.fetch_story.response
{"paragraphs": ["First paragraph...", "Second paragraph...", ...]}
```

This skill handles all narration pacing, sentence splitting, and bookmark
tracking itself - providers just deliver text.

### Friendly names

Each provider skill should keep a small list of names it's willing to
answer to as `collection_hint` - not just its `skill_id`, but the natural
things a person might call it: `ovos-skill-grimm-tales` might match
`"grimm"`, `"the brothers grimm"`, `"grimm brothers"`;
`ovos-skill-andersen-tales` might match `"andersen"`, `"hans christian
andersen"`, `"h c andersen"`, `"h.c. andersen"`;
`ovos-skill-andrew-lang-tales` might match `"andrew lang"`, `"lang"`,
`"the fairy books"`. Matching should be fuzzy (e.g. via
`ovos_utils.parse.match_one` against the provider's own alias list) rather
than exact string equality, since STT transcription is never perfectly
consistent.

If `collection_hint` doesn't clearly match a provider's own aliases, that
provider should simply not respond to the search at all (rather than
responding with a low confidence) - this skill only ever considers
providers that actually answered.

**Tune your match threshold carefully.** `ovos-skill-andersen-tales`
initially used `ovos_utils.parse.match_one(hint, aliases) >= 0.6` and
found a real false positive: "andrew lang" scored 0.63 against
"andersen" (plain character-overlap similarity on short strings, nothing
to do with meaning). Exact/near-exact alias matches score 1.0, so a
threshold around 0.85 is safe without losing legitimate fuzzy matches -
verify empirically for your own alias list rather than assuming 0.6-ish
is safe.

## Reusing this pattern elsewhere

Nothing about the `ovos.common_tales.*` protocol mechanics (broadcast
search + collect responses, targeted fetch + `wait_for_response`,
confidence-based arbitration) is actually fairy-tale-specific - only the
intents (`Tales.intent`, `TalesByCollection.intent`, `continue.intent`)
and the "tell me a story" framing are. If a future need for e.g. poems or
short science articles ever comes up, the right move is probably a
sibling orchestrator with its own intents/phrasing, reusing this same
protocol shape rather than overloading this skill's intents with
unrelated content types.

## Category
**Entertainment**

## Tags
#stories #fairytales #orchestrator
