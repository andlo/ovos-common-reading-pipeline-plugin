# <img src='book-512.png' card_color='#40DBB0' width='50' height='50' style='vertical-align:bottom'/> Common Reading

An OVOS pipeline plugin that reads things aloud - fairy tales, articles,
news, documents, reports, and whatever else a *provider* skill wants to
offer - by orchestrating "read me something" across those provider
skills, the same way [OCP](https://openvoiceos.github.io/ovos-technical-manual/ocp/)
(ovos-common-play) orchestrates "play X" across media skills.

_"If you want your children to be intelligent, read them fairy tales. If
you want them to be more intelligent, read them more fairy tales."_
— Albert Einstein

[![Tests](https://github.com/andlo/ovos-common-reading-pipeline-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/andlo/ovos-common-reading-pipeline-plugin/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/ovos-common-reading-pipeline-plugin.svg)](https://pypi.org/project/ovos-common-reading-pipeline-plugin/)

> **What this is:** a pipeline plugin for **narrating text-based content
> via TTS** - providers deliver plain text, and this plugin reads it
> aloud, sentence by sentence, with bookmarking and "continue" support.
>
> **What this is *not*:** an audiobook or audio-file player. If you're
> looking for pre-recorded audiobooks, radio dramas, or narrated
> readings as *audio files*, that's already well covered by existing
> **OCP** media skills (e.g. `ovos-skill-librivox`, or JarbasSkills'
> `skill-golden-audiobooks` / `skill-hppodcraft` /
> `skill-epic-horror-theatre`). This plugin solves a different problem:
> letting several *text* content providers coexist and be searched
> together, without any of them registering competing voice intents.

## Install
```bash
pip install ovos-common-reading-pipeline-plugin
```

Add it to your pipeline in `mycroft.conf`:

```json
{
  "intents": {
    "pipeline": [
      "stop_high",
      "ovos-common-reading-pipeline-plugin",
      "converse",
      "ocp_high",
      "padatious_high",
      "adapt_high",
      "..."
    ]
  }
}
```

You'll also want at least one *provider* skill installed, otherwise
there's nothing to read:

- [ovos-skill-andersen-tales](https://github.com/andlo/ovos-skill-andersen-tales) - Hans Christian Andersen fairy tales
- [ovos-skill-grimm-tales](https://github.com/andlo/ovos-skill-grimm-tales) - Brothers Grimm fairy tales
- [ovos-skill-ovosblog](https://github.com/andlo/ovos-skill-ovosblog) - the OpenVoiceOS blog, with machine-translation support
- [ovos-skill-arxiv-papers](https://github.com/andlo/ovos-skill-arxiv-papers) - arXiv paper abstracts (`content_type: "paper"`)
- ovos-skill-andrew-lang-tales (planned)

## Building your own provider

See [ovos-skill-common-reading-example](https://github.com/andlo/ovos-skill-common-reading-example) -
a template walking through two working patterns (RSS feeds and
static-page scraping), the bus protocol, caching, and the judgment calls
every provider has to make for itself (translate or not, what a human
calls the source, what's worth reading aloud).

## The `ovos.common_reading.*` bus protocol

Provider skills implement this to be usable by this plugin. It's a plain
messagebus convention (like `ovos.common_play.*`) - no shared package
dependency needed.

### 1. Search

Broadcast on a matched utterance:

```
ovos.common_reading.search
{
  "phrase": "<what the user asked for, or null for 'surprise me'>",
  "collection_hint": "<raw text like 'grimm' or 'h c andersen', or null>",
  "content_type": "<raw hint like 'story', 'book', 'article', 'poem', or null>",
  "requester": "<this plugin's id>"
}
```

`collection_hint` is set when the user names a specific source/collection
("read me a story **from Grimm**", "find Cinderella **by Andersen**"). It's
raw, unvalidated text - each provider fuzzy-matches it against its own
known friendly names and should only respond if it's a match, or if
`collection_hint` is null (in which case every provider competes as usual).

`content_type` is a similarly raw, optional hint. A provider that only
offers one kind of content can use it to stay silent when it clearly
doesn't apply, but should treat a null/missing `content_type` as "anyone
can compete".

`phrase` can also be null on its own - "read me a story from Grimm" with
no specific title named is a valid request for the hinted provider to
offer something of its own choosing.

Every provider that thinks it can help replies (within ~2s):

```
ovos.common_reading.search.response
{
  "skill_id": "<provider skill id>",
  "content_id": "<opaque id the provider will recognize later>",
  "title": "<human-readable title>",
  "author": "<author, optional>",
  "collection": "<book/collection name, optional>",
  "source": "<where the text comes from, e.g. 'grimmstories.com'>",
  "confidence": 0.0-1.0,
  "machine_translated": true/false (optional, defaults falsy)
}
```

The highest-confidence response wins (and, if it's below 0.8, this
plugin confirms with the user before continuing). If a provider sets
`"machine_translated": true`, that's disclosed as part of the
announcement right before reading starts.

### 2. Fetch

Once something is chosen (or resumed via "continue"), a *targeted*
request goes to just that provider:

```
ovos.common_reading.fetch_content.<provider_skill_id>
{"content_id": "<from the search response>", "requester": "<this plugin's id>"}
```

The provider replies once with the full text, split into paragraphs:

```
ovos.common_reading.fetch_content.response
{"paragraphs": ["First paragraph...", "Second paragraph...", ...]}
```

Reading pacing, sentence splitting, and bookmark tracking all happen
here - providers just deliver text.

### Friendly names

Each provider should keep a small list of names it's willing to answer
to as `collection_hint` - not just its `skill_id`, but the natural
things a person might call it: `ovos-skill-grimm-tales` might match
`"grimm"`, `"the brothers grimm"`; `ovos-skill-andersen-tales` matches
`"andersen"`, `"hans christian andersen"`, `"h c andersen"`. Matching
should be fuzzy (e.g. via `ovos_utils.parse.match_one` against the
provider's own alias list) rather than exact string equality, since STT
transcription is never perfectly consistent.

If `collection_hint` doesn't clearly match a provider's own aliases,
that provider should simply not respond to the search at all - only
providers that actually answered are considered.

**Tune your match threshold carefully.** A threshold around 0.6 can
produce false positives on short strings (e.g. "andrew lang" scoring
0.63 against "andersen" on plain character overlap, nothing to do with
meaning) - 0.85 is a safer default. Verify empirically for your own
alias list.

## Category
**Entertainment**

## Tags
#reading #stories #articles #news #orchestrator #pipeline
