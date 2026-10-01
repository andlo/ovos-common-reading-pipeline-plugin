#!/usr/bin/env python3
"""Write test/end2end/golden_utterances_<Lang>.jsonl and
negative_utterances_<Lang>.jsonl from the sentence lists below.

Golden rows are sentences the plugin must claim, with the intent it claims
them as. Negative rows are sentences it must leave to other skills. Both
assume the provider vocabulary of tests/conftest.announce_typical_providers
(grimm and andersen collections with a few titles, a horoscope, an almanac,
a blog and an archive), which mirrors the real provider skills.

The negative rows are kept in their own files on purpose: tools that read
golden_utterances*.jsonl (ovoscope, Klondike) treat a row without an intent
differently, so a "must not claim" row never goes in a golden file.

Run from the repo root after editing the lists; tests/test_golden.py checks
every row.
"""
import json
from pathlib import Path

SKILL_ID = "ovos-common-reading-pipeline-plugin.andlo"
OUT = Path(__file__).resolve().parents[1] / "test" / "end2end"

# lang -> [(utterance, intent)]
GOLDEN = {
    "en-US": [
        ("tell me a story", "read_any_story"),
        ("tell me a fairy tale", "read_any_story"),
        ("read me a bedtime story", "read_any_story"),
        ("can you tell me another story", "read_any_story"),
        ("tell me a story please", "read_any_story"),
        ("tell me a story from grimm", "read_by_collection"),
        ("read me a grimm story", "read_by_collection"),
        ("read me a story by hans christian andersen", "read_by_collection"),
        ("read latest post from ovosblog", "read_by_collection"),
        ("find cinderella from archive", "read_by_collection"),
        ("tell me the story about the little mermaid from andersen", "read_by_collection"),
        ("tell me a story about cinderella", "read_content"),
        ("tell me the story about the little mermaid", "read_content"),
        ("tell me a fairytale about the ugly duckling", "read_content"),
        ("can you read me an article about boiling an egg", "read_content"),
        ("tell me my leo horoscope", "read_content"),
        ("tell me the little mermaid", "read_content"),
        ("read the snow queen", "read_content"),
        ("read me my horoscope", "read_by_type"),
        ("read me today's horoscope", "read_by_type"),
        ("read me my almanac", "read_by_type"),
        ("read me an article", "read_by_type"),
    ],
    "da-DK": [
        ("fortæl mig et eventyr", "read_any_story"),
        ("læs et eventyr op for mig", "read_any_story"),
        ("fortæl en historie for mig", "read_any_story"),
        ("fortæl mig en historie fra grimm", "read_by_collection"),
        ("læs mig en grimm-historie", "read_by_collection"),
        ("læs et eventyr af h c andersen", "read_by_collection"),
        ("fortæl mig en historie om askepot", "read_content"),
        ("fortæl mig historien om den lille havfrue", "read_content"),
        ("kan du læse mig en historie om askepot", "read_content"),
        ("læs løvens horoskop", "read_content"),
        ("læs den grimme ælling", "read_content"),
        ("læs mit horoskop", "read_by_type"),
    ],
    "de-DE": [
        ("erzähl mir eine Geschichte", "read_any_story"),
        ("lies mir ein Märchen vor", "read_any_story"),
        ("kannst du mir eine Geschichte vorlesen", "read_any_story"),
        ("erzähl uns bitte eine Geschichte", "read_any_story"),
        ("erzähl mir eine geschichte von grimm", "read_by_collection"),
        ("lies mir eine grimm-Geschichte", "read_by_collection"),
        ("erzähl mir eine geschichte über aschenputtel", "read_content"),
    ],
    "es-ES": [
        ("cuéntame un cuento", "read_any_story"),
        ("cuéntame un cuento de grimm", "read_by_collection"),
        ("léeme un cuento de grimm", "read_by_collection"),
        ("cuéntame un cuento sobre cenicienta", "read_content"),
    ],
    "fr-FR": [
        ("raconte-moi une histoire", "read_any_story"),
        ("raconte moi une histoire", "read_any_story"),
        ("lis-moi un conte", "read_any_story"),
        ("peux-tu me raconter une histoire", "read_any_story"),
        ("raconte-moi une histoire de grimm", "read_by_collection"),
        ("raconte-moi une histoire de cosquin", "read_by_collection"),
        ("raconte-moi une histoire sur cendrillon", "read_content"),
        ("lis-moi une nouvelle sur la mer", "read_content"),
    ],
    "it-IT": [
        ("raccontami una fiaba", "read_any_story"),
        ("raccontami una storia di grimm", "read_by_collection"),
        ("leggimi una storia di grimm", "read_by_collection"),
        ("raccontami una storia su cenerentola", "read_content"),
    ],
    "nl-NL": [
        ("lees me een sprookje voor", "read_any_story"),
        ("vertel me een verhaal van grimm", "read_by_collection"),
        ("lees me een grimm-verhaal", "read_by_collection"),
        ("vertel me een verhaal over assepoester", "read_content"),
    ],
    "pt-PT": [
        ("conta-me uma história", "read_any_story"),
        ("conta-me uma história de grimm", "read_by_collection"),
        ("lê-me uma história de grimm", "read_by_collection"),
        ("conta-me uma história sobre cinderela", "read_content"),
    ],
}

# lang -> [utterance] the plugin must leave alone
NEGATIVE = {
    "en-US": [
        "tell me a joke", "tell me about abraham lincoln", "what is my horoscope",
        "tell me the weather", "can you tell me the weather right now", "tell me the time",
        "tell me the current year", "can you tell me the day of the month",
        "tell me today's weather report", "read my messages", "read the shopping list",
        "read me my emails", "read me the news",
    ],
    "da-DK": ["fortæl mig en vittighed", "hvad er dagens horoskop", "hvad er klokken", "læs nyhederne op"],
    "de-DE": ["erzähl mir einen Witz", "lies mir die Nachrichten vor", "wie spät ist es"],
    "es-ES": ["cuéntame un chiste", "qué hora es"],
    "fr-FR": ["raconte-moi une blague", "lis-moi les nouvelles", "quelle heure est-il"],
    "it-IT": ["raccontami una barzelletta", "che ore sono"],
    "nl-NL": ["vertel me een mop", "hoe laat is het"],
    "pt-PT": ["conta-me uma piada", "que horas são"],
}


def write(name, rows):
    path = OUT / name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{path.relative_to(OUT.parents[1])}: {len(rows)} rows")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, rows in GOLDEN.items():
        write(f"golden_utterances_{lang}.jsonl",
              [{"utterance": u, "lang": lang, "skill_id": SKILL_ID, "intent_label": i} for u, i in rows])
    for lang, rows in NEGATIVE.items():
        write(f"negative_utterances_{lang}.jsonl",
              [{"utterance": u, "lang": lang, "skill_id": SKILL_ID, "intent_label": None} for u in rows])


if __name__ == "__main__":
    main()
