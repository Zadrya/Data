# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Markdown of the diff report. No network.

The golden report ``tests/fixtures/diff/report.md`` is the report of ``old.json``
against ``new.json``, which together touch every section and every risk but one.
After a deliberate change of the report, rewrite it with
``uv run python -m tests.test_diff_report`` and review the diff of the file.
"""

import os
import subprocess
import sys
from typing import Any

import pytest

from tests.diff_cases import FIXTURES, dataset, group, interacting, oral, substance
from zadrya_data.diff import Risk, compare, load_dataset
from zadrya_data.diff_report import Report, escape, render

GOLDEN = FIXTURES / "report.md"
EM_DASH = "\u2014"
_RENDER = (
    "import sys; from zadrya_data.diff import compare, load_dataset; "
    "from zadrya_data.diff_report import render; "
    "old, new = (load_dataset(__import__('pathlib').Path(p)) for p in sys.argv[1:3]); "
    "sys.stdout.write(render(compare(old, new), old_label='old.json', new_label='new.json').text)"
)


def golden_report() -> str:
    """The report the golden file must hold."""
    old, new = load_dataset(FIXTURES / "old.json"), load_dataset(FIXTURES / "new.json")
    return render(compare(old, new), old_label="old.json", new_label="new.json").text


def report(old: dict[str, Any], new: dict[str, Any], max_rows: int = 100) -> Report:
    return render(compare(old, new), old_label="old", new_label="new", max_rows=max_rows)


def section(text: str, heading: str) -> str:
    """The text under a heading, up to the next heading of any level."""
    start = text.index(f"{heading}\n")
    end = text.find("\n#", start + len(heading))
    return text[start : end if end != -1 else len(text)]


# Golden file and determinism


def test_the_report_matches_the_golden_file() -> None:
    assert golden_report() == GOLDEN.read_text(encoding="utf-8")


def test_the_golden_report_has_no_em_dash_although_a_name_has_one() -> None:
    names = [s["name"] for s in load_dataset(FIXTURES / "new.json")["substances"]]
    assert any(EM_DASH in name for name in names)
    assert EM_DASH not in golden_report()
    assert "&#8212;" in golden_report()


def test_the_report_is_the_same_under_any_hash_seed() -> None:
    outputs = {
        subprocess.run(
            [sys.executable, "-c", _RENDER, str(FIXTURES / "old.json"), str(FIXTURES / "new.json")],
            check=True,
            env=os.environ | {"PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
        ).stdout
        for seed in ("0", "1", "12345", "random")
    }
    assert outputs == {GOLDEN.read_text(encoding="utf-8")}


# Head: warning and summary


def test_the_head_holds_the_warning_and_the_summary_and_the_body_the_rest() -> None:
    result = render(
        compare(load_dataset(FIXTURES / "old.json"), load_dataset(FIXTURES / "new.json")),
        old_label="o",
        new_label="n",
    )
    assert "> **Review these first:**" in result.head
    assert "## Summary" in result.head
    assert "## Substances" not in result.head
    assert result.body.startswith("## Substances\n")
    assert result.text == f"{result.head}\n{result.body}"


def test_the_warning_counts_every_risk_and_lists_renames() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    old = dataset(interacting("A", "dangerous", "B"), substance("B"), substance("Old|1", url=url))
    new = dataset(interacting("A", "unsafe", "B"), substance("B"), substance("New|1", url=url))
    head = report(old, new).head
    assert "> - Interactions lowered: 1\n" in head
    assert "> - Substances renamed: 1 (Old\\|1 -> New\\|1)\n" in head


def test_the_warning_names_each_kind_with_its_count() -> None:
    old = dataset(
        substance("A", roas=[oral(dose={"units": "mg", "strongMin": 30})]),
        interactionGroups=[group("stimulants", "A", "B")],
    )
    new = dataset(
        substance("A", roas=[oral(dose={"units": "mg", "strongMin": 35})]),
        interactionGroups=[group("stimulants", "A")],
    )
    lines = [line for line in report(old, new).head.splitlines() if line.startswith("> - ")]
    assert lines == [
        f"> - {Risk.REMOVED_INTERACTION_MEMBER.value}: 1",
        f"> - {Risk.RISKY_DOSE.value}: 1",
    ]


def test_there_is_no_warning_without_a_risk() -> None:
    old = dataset(substance("A"))
    new = dataset(substance("A", roas=[oral(dose={"units": "mg", "lightMin": 1})]))
    assert ">" not in report(old, new).head


def test_changed_paths_outside_the_dataset_head_the_report() -> None:
    result = render(
        compare(dataset(), dataset()),
        old_label="o",
        new_label="n",
        changed_paths=["src/zadrya_data/diff.py", "a|b"],
    )
    assert "touches 2 file(s) outside dataset/" in result.head
    assert "> - src/zadrya\\_data/diff\\.py\n> - a\\|b\n" in result.head
    assert result.head.index("touches") < result.head.index("## Summary")


def test_versions_are_escaped_in_the_summary() -> None:
    head = report(dataset(), dataset(datasetVersion="1.1.0")).head
    assert "- datasetVersion\\: 1\\.0\\.0 \\-\\> 1\\.1\\.0\n" in head


def test_identical_datasets_give_a_report_of_none() -> None:
    document = dataset(substance("A"))
    text = report(document, document).text
    assert text.count("None.") == 10
    assert "<details>" not in text


# Sections


def test_removed_substances_are_never_truncated_and_show_hints() -> None:
    old = dataset(*(substance(f"S{n:02}") for n in range(10)))
    new = dataset(substance("C", aliases=["S00"]))
    removed = section(report(old, new, max_rows=2).body, "### Removed (never truncated)")
    assert removed.count("\n- **S") == 10
    assert "- **S00** (possible rename\\: C lists S00 as an alias, at another address)" in removed


def test_added_substances_are_capped_with_a_count() -> None:
    new = dataset(*(substance(f"S{n:02}") for n in range(10)))
    added = section(report(dataset(), new, max_rows=3).body, "### Added")
    assert added.count("\n- S") == 3
    assert "7 more row(s) not shown." in added


def test_protected_rows_lead_and_alike_rows_fold() -> None:
    old = dataset(
        *(substance(f"S{n}", roas=[oral(dose={"units": "mg", "strongMin": 9})]) for n in range(3))
    )
    new = dataset(
        *(
            substance(f"S{n}", roas=[oral(dose={"units": "mg", "strongMin": 9 + n, "lightMin": 1})])
            for n in range(3)
        )
    )
    body = section(report(old, new).body, "## Doses, durations, tolerance and bioavailability")
    lines = body.splitlines()
    assert lines[2] == "| Substance | Route | Field | Old | New | Note |"
    assert lines[4].startswith("| S1 | oral | dose strongMin | 9 mg | 10 mg | **higher")
    assert lines[5].startswith("| S2 |")
    assert "<summary>dose lightMin added: 3 row(s)</summary>" in body
    assert body.index("**higher") < body.index("<details>")


def test_changes_fold_before_additions() -> None:
    old = dataset(substance("A", roas=[oral(dose={"units": "mg", "lightMin": 2})]))
    new = dataset(
        substance("A", roas=[oral(dose={"units": "mg", "thresholdMin": 1, "lightMin": 1})])
    )
    body = report(old, new).body
    assert body.index("dose lightMin lower") < body.index("dose thresholdMin added")


def test_a_capped_group_says_how_many_it_shows() -> None:
    old = dataset(*(substance(f"S{n}", roas=[oral(dose={"units": "mg"})]) for n in range(5)))
    new = dataset(
        *(substance(f"S{n}", roas=[oral(dose={"units": "mg", "lightMin": 1})]) for n in range(5))
    )
    body = report(old, new, max_rows=2).body
    assert "<summary>dose lightMin added: 2 of 5 row(s)</summary>" in body
    assert "3 more row(s) not shown." in body


def test_risky_rows_are_never_truncated() -> None:
    old = dataset(
        *(substance(f"S{n}", roas=[oral(duration={"total": {"max": 60}})]) for n in range(5))
    )
    new = dataset(
        *(substance(f"S{n}", roas=[oral(duration={"total": {"max": 30}})]) for n in range(5))
    )
    body = report(old, new, max_rows=1).body
    assert body.count("shorter timeline\\)**") == 5
    assert "not shown" not in body


def test_lowered_and_removed_interactions_are_never_truncated() -> None:
    names = [f"S{n:02}" for n in range(12)]
    old = dataset(interacting("A", "dangerous", *names), *(substance(n) for n in names))
    new = dataset(interacting("A", "unsafe", *names[:6]), *(substance(n) for n in names))
    body = report(old, new, max_rows=2).body
    lowered = section(body, "### **LOWERED** interactions (never truncated)")
    removed = section(body, "### **REMOVED** interactions (never truncated)")
    assert lowered.count("| dangerous | **unsafe** |") == 6
    assert removed.count("| dangerous | **none** |") == 6
    assert "not shown" not in lowered + removed


def test_raised_and_added_interactions_are_capped() -> None:
    names = [f"S{n:02}" for n in range(5)]
    old = dataset(substance("A"), *(substance(n) for n in names))
    new = dataset(interacting("A", "uncertain", *names), *(substance(n) for n in names))
    added = section(report(old, new, max_rows=2).body, "### Added interactions")
    assert added.count("| none | uncertain |") == 2
    assert "3 more row(s) not shown." in added


def test_group_rows_put_the_protected_ones_first_in_bold() -> None:
    old = dataset(interactionGroups=[group("a", "X"), group("b", "Y")])
    new = dataset(interactionGroups=[group("a", "X", "Z"), group("b")])
    body = section(report(old, new).body, "## Groups and cross tolerance")
    rows = [line for line in body.splitlines() if line.startswith("| interaction")]
    assert rows == [
        "| interaction group b | **members removed** | Y |",
        "| interaction group a | members added | Z |",
    ]


def test_texts_fold_by_field_and_are_never_printed() -> None:
    old = dataset(substance("A", summary="Secret old words."), substance("B", summary="x"))
    new = dataset(substance("A", saferUse=["Secret new words."]), substance("B", summary="y"))
    body = section(report(old, new).body, "## Categories and texts")
    assert "<summary>summary removed: 1</summary>" in body
    assert "<summary>saferUse added: 1</summary>" in body
    assert "<summary>summary changed: 1</summary>" in body
    assert "Secret" not in body


# Escaping


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ("A|B", "A\\|B"),
        ("*x* _y_ `z`", "\\*x\\* \\_y\\_ \\`z\\`"),
        ("[a](b) <c> !d", "\\[a\\]\\(b\\) \\<c\\> \\!d"),
        ("1.5-MeO, it's", "1\\.5\\-MeO, it's"),
        ("$x$ ~y~ a&amp;b", "\\$x\\$ \\~y\\~ a\\&amp;b"),
        ("@octocat #12", "\\@&#8203;octocat \\#&#8203;12"),
        ("a\nb\tc\u2028d\u202ee\u200bf", "a b c d e f"),
        (f"x {EM_DASH} y", "x &#8212; y"),
        ("µg 4-HO-MET", "µg 4\\-HO\\-MET"),
        ("back\\slash", "back\\\\slash"),
        ("https://e.x", "https\\:&#8203;//e\\.x"),
        ("see www.evil.x", "see www&#8203;\\.evil\\.x"),
        ("GH-12 gh-3", "GH&#8203;\\-12 gh&#8203;\\-3"),
        ("abc1234567", "abc123&#8203;4567"),
        ("deadbeefcafe1234", "deadbe&#8203;efcafe&#8203;1234"),
        ("abc123 7654321", "abc123 765432&#8203;1"),
        (":smile:", "\\:smile\\:"),
    ],
)
def test_escape_keeps_text_literal_in_markdown(text: str, escaped: str) -> None:
    assert escape(text) == escaped


def test_a_name_with_a_pipe_keeps_the_table_shape() -> None:
    old = dataset(substance("A|B", roas=[oral(dose={"units": "m|g", "strongMin": 1})]))
    new = dataset(substance("A|B", roas=[oral(dose={"units": "m|g", "strongMin": 2})]))
    row = next(line for line in report(old, new).body.splitlines() if line.startswith("| A"))
    assert row.startswith("| A\\|B | oral | dose strongMin | 1 m\\|g | 2 m\\|g | **higher")
    assert row.replace("\\|", "").count("|") == 7


def test_labels_are_escaped() -> None:
    head = render(compare(dataset(), dataset()), old_label="a|b", new_label="@x").head
    assert "Old: a\\|b\n" in head
    assert "New: \\@&#8203;x\n" in head


if __name__ == "__main__":
    GOLDEN.write_text(golden_report(), encoding="utf-8")
