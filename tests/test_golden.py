"""Every row of test/end2end/golden_utterances_*.jsonl is claimed as its
intent, and every row of negative_utterances_*.jsonl is left alone, with
the provider vocabulary of conftest.announce_typical_providers announced.
The files are written by scripts/build_golden.py."""
import json
from pathlib import Path

import pytest

from conftest import announce_typical_providers, session_message

END2END = Path(__file__).resolve().parents[1] / "test" / "end2end"


def _rows(pattern):
    rows = []
    for path in sorted(END2END.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows.append(pytest.param(row, id=f"{row['lang']}:{row['utterance']}"))
    return rows


@pytest.fixture
def plugin(plugin):
    announce_typical_providers(plugin)
    return plugin


def test_there_are_golden_files_for_every_language():
    langs = {p.stem.rsplit("_", 1)[-1] for p in END2END.glob("golden_utterances_*.jsonl")}
    assert langs == {"en-US", "da-DK", "de-DE", "es-ES", "fr-FR", "it-IT", "nl-NL", "pt-PT"}


@pytest.mark.parametrize("row", _rows("golden_utterances_*.jsonl"))
def test_golden_row_is_claimed_as_its_intent(plugin, row):
    result = plugin.match([row["utterance"]], row["lang"], session_message(lang=row["lang"]))
    assert result is not None, f"not claimed: {row['utterance']!r}"
    # the fixture runs the plugin as "<name>.test"; the files carry the real id
    assert result.skill_id.split(".")[0] == row["skill_id"].split(".")[0]
    assert result.match_type.split(":")[-1] == row["intent_label"]


@pytest.mark.parametrize("row", _rows("negative_utterances_*.jsonl"))
def test_negative_row_is_left_to_other_skills(plugin, row):
    result = plugin.match([row["utterance"]], row["lang"], session_message(lang=row["lang"]))
    assert result is None, f"claimed {row['utterance']!r} as {result.match_type}"
