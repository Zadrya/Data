# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the dataset diff report. No network.

The golden report ``tests/fixtures/diff/report.md`` is the report of ``old.json``
against ``new.json``, which together touch every section. After a deliberate change
of the report, rewrite it with ``uv run python -m tests.test_diff`` and review the
diff of the file.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from zadrya_data import diff
from zadrya_data.cli import main
from zadrya_data.normalize import NormalizationError
from zadrya_data.diff import Change, compare, escape, load_base_dataset, load_dataset, render

FIXTURES = Path(__file__).parent / "fixtures" / "diff"
GOLDEN = FIXTURES / "report.md"
BASE_FILE = Path(__file__).parents[1] / "sources" / "base" / "Substances.json"
EM_DASH = "\u2014"


def golden_report() -> str:
    """The report the golden file must hold."""
    return render(
        compare(load_dataset(FIXTURES / "old.json"), load_dataset(FIXTURES / "new.json")),
        old_label="old.json",
        new_label="new.json",
    )


def substance(name: str, **extra: Any) -> dict[str, Any]:
    """A valid substance with nothing but a name, and the keys given."""
    return {
        "name": name,
        "aliases": [],
        "url": f"https://psychonautwiki.org/wiki/{quote(name)}",
        "categories": [],
        "classes": {"psychoactive": [], "chemical": []},
        "roas": [],
        "crossTolerances": [],
        "interactions": {"dangerous": [], "unsafe": [], "uncertain": []},
        "toxicities": [],
    } | extra


def dataset(*substances: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A valid dataset of the substances, with the top-level keys given."""
    return {
        "schemaVersion": "1.0.0",
        "datasetVersion": "1.0.0",
        "attribution": [{"name": "PW", "url": "https://psychonautwiki.org", "license": "CC0"}],
        "categories": [],
        "interactionGroups": [],
        "crossToleranceGroups": [],
        "substances": list(substances),
    } | extra


def interacting(name: str, severity: str, *targets: str) -> dict[str, Any]:
    """A substance listing catalog substances under one severity."""
    interactions: dict[str, list[dict[str, str]]] = {"dangerous": [], "unsafe": [], "uncertain": []}
    interactions[severity] = [{"kind": "substance", "name": target} for target in targets]
    return substance(name, interactions=interactions)


def report(old: dict[str, Any], new: dict[str, Any], max_rows: int = 100) -> str:
    return render(compare(old, new), old_label="old", new_label="new", max_rows=max_rows)


def section(text: str, heading: str) -> str:
    """The text under a heading, up to the next heading."""
    start = text.index(f"{heading}\n")
    end = text.find("\n#", start + len(heading))
    return text[start : end if end != -1 else len(text)]


# Golden file


def test_the_report_matches_the_golden_file() -> None:
    assert golden_report() == GOLDEN.read_text(encoding="utf-8")


def test_the_golden_report_has_no_em_dash_although_a_name_has_one() -> None:
    names = [s["name"] for s in load_dataset(FIXTURES / "new.json")["substances"]]
    assert any(EM_DASH in name for name in names)
    assert EM_DASH not in golden_report()
    assert "&#8212;" in golden_report()


def test_the_report_is_the_same_under_any_hash_seed(tmp_path: Path) -> None:
    outputs = set()
    for seed in ("0", "1", "12345", "random"):
        output = tmp_path / f"report-{seed}.md"
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from zadrya_data.cli import main; sys.exit(main(sys.argv[1:]))",
                "diff",
                str(FIXTURES / "old.json"),
                str(FIXTURES / "new.json"),
                "--old-label",
                "old.json",
                "--new-label",
                "new.json",
                "--output",
                str(output),
            ],
            check=True,
            env=os.environ | {"PYTHONHASHSEED": seed},
            capture_output=True,
        )
        outputs.add(output.read_text(encoding="utf-8"))
    assert outputs == {GOLDEN.read_text(encoding="utf-8")}


# Substances


def test_identical_datasets_report_no_change() -> None:
    document = dataset(substance("A"), substance("B"))
    text = report(document, copy.deepcopy(document))
    assert "- Added: 0, removed: 0, renamed: 0" in text
    assert "Warning" not in text
    assert text.count("None.") == 10


def test_added_and_removed_substances_are_listed_by_name() -> None:
    text = report(dataset(substance("A"), substance("B")), dataset(substance("B"), substance("C")))
    assert section(text, "### Added").splitlines()[2] == "- C"
    assert section(text, "### Removed (never truncated)").splitlines()[2] == "- **A**"


def test_removed_substances_are_never_truncated() -> None:
    old = dataset(*(substance(f"S{number:02}") for number in range(10)))
    text = report(old, dataset(), max_rows=2)
    removed = section(text, "### Removed (never truncated)")
    assert removed.count("\n- ") == 10
    assert "not shown" not in removed


def test_added_substances_are_capped_with_a_count() -> None:
    new = dataset(*(substance(f"S{number:02}") for number in range(10)))
    added = section(report(dataset(), new, max_rows=3), "### Added")
    assert added.count("\n- ") == 3
    assert "7 more substance(s) not shown." in added


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (substance("Lsd"), substance("LSD"), "same name but for case"),
        (substance("Molly"), substance("MDMA", aliases=["molly"]), "the old name is an alias"),
        (substance("MDMA", aliases=["Molly"]), substance("Molly"), "the new name is an alias"),
    ],
)
def test_a_rename_is_found_by_name_and_alias(
    old: dict[str, Any], new: dict[str, Any], reason: str
) -> None:
    result = compare(dataset(old), dataset(new))
    assert [(r.old, r.new) for r in result.renamed] == [(old["name"], new["name"])]
    assert reason in result.renamed[0].reason
    assert result.added == [] and result.removed == []


def test_an_ambiguous_rename_stays_added_and_removed() -> None:
    old = dataset(substance("Molly"))
    new = dataset(substance("MDMA", aliases=["Molly"]), substance("MDA", aliases=["Molly"]))
    result = compare(old, new)
    assert result.renamed == []
    assert result.removed == ["Molly"]
    assert result.added == ["MDA", "MDMA"]


def test_a_renamed_substance_is_compared_with_its_old_self() -> None:
    old = dataset(
        substance("Old", roas=[{"route": "oral", "dose": {"units": "mg", "commonMin": 1}}])
    )
    new = dataset(
        substance(
            "New",
            aliases=["Old"],
            roas=[{"route": "oral", "dose": {"units": "mg", "commonMin": 2}}],
        )
    )
    result = compare(old, new)
    assert [row.cells[:5] for row in result.numbers] == [
        ("New", "oral", "dose commonMin", "1 mg", "2 mg")
    ]
    assert result.flags[0].cells == ("substance New", "aliases (changed), url (changed)")


# Numbers


def _route(**route: Any) -> dict[str, Any]:
    return {"route": "oral"} | route


def _numbers(old_route: dict[str, Any], new_route: dict[str, Any]) -> list[tuple[str, ...]]:
    result = compare(
        dataset(substance("A", roas=[old_route])), dataset(substance("A", roas=[new_route]))
    )
    return [row.cells[2:] for row in result.numbers]


def test_dose_boundaries_report_their_direction_and_risk() -> None:
    old = _route(dose={"units": "mg", "thresholdMin": 1, "commonMin": 5, "strongMin": 10})
    new = _route(dose={"units": "mg", "lightMin": 2, "commonMin": 4, "strongMin": 12})
    assert _numbers(old, new) == [
        ("dose thresholdMin", "1 mg", "none", "removed"),
        ("dose lightMin", "none", "2 mg", "added"),
        ("dose commonMin", "5 mg", "4 mg", "lower"),
        ("dose strongMin", "10 mg", "12 mg", "**higher (risky)**"),
    ]


def test_a_removed_upper_boundary_is_risky_and_never_truncated() -> None:
    old = dataset(
        *(
            substance(f"S{n}", roas=[_route(dose={"units": "mg", "heavyMin": 9, "lightMin": n})])
            for n in range(5)
        )
    )
    new = dataset(*(substance(f"S{n}", roas=[_route(dose={"units": "mg"})]) for n in range(5)))
    table = section(
        report(old, new, max_rows=1), "## Doses, durations, tolerance and bioavailability"
    )
    assert table.count("**removed (risky)**") == 5
    assert table.count("| removed |") == 0
    assert "5 more row(s) not shown." in table


def test_changed_units_make_the_numbers_incomparable() -> None:
    old = _route(dose={"units": "mg", "commonMin": 5})
    new = _route(dose={"units": "g", "commonMin": 0.005})
    assert _numbers(old, new) == [
        ("dose units", "mg", "g", "**units differ: the numbers cannot be compared**"),
        ("dose commonMin", "5 mg", "0.005 g", "units differ"),
    ]


def test_a_dose_block_that_appears_or_disappears_is_reported() -> None:
    with_dose = _route(dose={"units": "mg", "strongMin": 3})
    assert _numbers(_route(), with_dose) == [
        ("dose units", "none", "mg", "added"),
        ("dose strongMin", "none", "3 mg", "added"),
    ]
    assert _numbers(with_dose, _route()) == [
        ("dose units", "mg", "none", "removed"),
        ("dose strongMin", "3 mg", "none", "**removed (risky)**"),
    ]


def test_durations_and_bioavailability_report_each_bound() -> None:
    old = _route(duration={"onset": {"min": 10}}, bioavailability={"max": 50})
    new = _route(duration={"onset": {"min": 15}, "total": {"max": 60}}, bioavailability={"min": 5})
    assert _numbers(old, new) == [
        ("duration onset min", "10 min", "15 min", "higher"),
        ("duration total max", "none", "60 min", "added"),
        ("bioavailability min", "none", "5 %", "added"),
        ("bioavailability max", "50 %", "none", "removed"),
    ]


def test_routes_that_appear_or_disappear_are_reported_in_schema_order() -> None:
    result = compare(
        dataset(substance("A", roas=[{"route": "smoked"}, {"route": "oral"}])),
        dataset(substance("A", roas=[{"route": "insufflated"}])),
    )
    assert [(row.cells[1], row.cells[5], row.protected) for row in result.numbers] == [
        ("oral", "**removed**", True),
        ("insufflated", "added", False),
        ("smoked", "**removed**", True),
    ]


def test_tolerance_texts_and_times_are_compared() -> None:
    old = substance(
        "A", tolerance={"full": "soon", "zero": {"text": "1 day", "min": 1440, "max": 1440}}
    )
    new = substance("A", tolerance={"half": {"text": "2 days", "min": 2880, "max": 2880}})
    assert [row.cells[2:] for row in compare(dataset(old), dataset(new)).numbers] == [
        ("tolerance full", "soon", "none", "changed"),
        ("tolerance half", "none", "2 days", "changed"),
        ("tolerance half min", "none", "2880 min", "added"),
        ("tolerance half max", "none", "2880 min", "added"),
        ("tolerance zero", "1 day", "none", "changed"),
        ("tolerance zero min", "1440 min", "none", "removed"),
        ("tolerance zero max", "1440 min", "none", "removed"),
    ]


def test_an_integer_and_the_same_float_are_not_a_change() -> None:
    assert _numbers(_route(bioavailability={"min": 5}), _route(bioavailability={"min": 5.0})) == []


def test_floats_are_written_in_their_shortest_exact_form() -> None:
    old, new = _route(bioavailability={"min": 0.1}), _route(bioavailability={"min": 2.5e-7})
    assert _numbers(old, new) == [("bioavailability min", "0.1 %", "2.5e-07 %", "lower")]


# Interactions


def test_interaction_changes_are_classified_and_lowered_come_first() -> None:
    old = dataset(
        interacting("A", "dangerous", "B"),
        interacting("B", "uncertain", "C"),
        interacting("C", "unsafe", "D"),
        substance("D"),
    )
    new = dataset(
        interacting("A", "unsafe", "B"),
        interacting("B", "dangerous", "C"),
        interacting("D", "uncertain", "A"),
        substance("C"),
    )
    result = compare(old, new)
    cells = {change: [row.cells for row in rows] for change, rows in result.interactions.items()}
    assert cells == {
        Change.LOWERED: [("A", "B", "dangerous", "unsafe")],
        Change.REMOVED: [("C", "D", "unsafe", "none")],
        Change.RAISED: [("B", "C", "uncertain", "dangerous")],
        Change.ADDED: [("A", "D", "none", "uncertain")],
    }
    text = report(old, new)
    assert "> **Warning: 1 interaction(s) lowered and 1 removed." in text
    assert text.index("### **LOWERED**") < text.index("### **REMOVED**")
    assert text.index("### **REMOVED**") < text.index("### Raised interactions")


def test_a_pair_takes_the_higher_severity_of_both_directions() -> None:
    old = dataset(interacting("A", "dangerous", "B"), interacting("B", "uncertain", "A"))
    new = dataset(substance("A"), interacting("B", "uncertain", "A"))
    rows = compare(old, new).interactions
    assert [row.cells for row in rows[Change.LOWERED]] == [("A", "B", "dangerous", "uncertain")]
    assert all(not rows[change] for change in (Change.REMOVED, Change.RAISED, Change.ADDED))


def test_group_and_other_targets_are_pairs_of_the_listing_substance() -> None:
    old = substance(
        "A",
        interactions={
            "dangerous": [{"kind": "group", "groupId": "opioids"}],
            "unsafe": [{"kind": "other", "name": "Grapefruit"}],
            "uncertain": [],
        },
    )
    rows = compare(dataset(old), dataset(substance("A"))).interactions[Change.REMOVED]
    assert [row.cells for row in rows] == [
        ("A", "group opioids", "dangerous", "none"),
        ("A", "other: Grapefruit", "unsafe", "none"),
    ]


def test_a_rename_does_not_change_the_interactions_of_the_substance() -> None:
    old = dataset(interacting("Old", "dangerous", "B"), interacting("B", "dangerous", "Old"))
    new = dataset(
        interacting("New", "dangerous", "B") | {"aliases": ["Old"]},
        interacting("B", "dangerous", "New"),
    )
    assert all(not rows for rows in compare(old, new).interactions.values())


def test_lowered_and_removed_interactions_are_never_truncated() -> None:
    names = [f"S{number:02}" for number in range(12)]
    old = dataset(interacting("A", "dangerous", *names), *(substance(name) for name in names))
    new = dataset(
        interacting("A", "unsafe", *names[:6]),
        *(substance(name) for name in names),
    )
    text = report(old, new, max_rows=2)
    lowered = section(text, "### **LOWERED** interactions (never truncated)")
    removed = section(text, "### **REMOVED** interactions (never truncated)")
    assert lowered.count("| dangerous | unsafe |") == 6
    assert removed.count("| dangerous | none |") == 6
    assert "not shown" not in lowered + removed


def test_raised_and_added_interactions_are_capped() -> None:
    names = [f"S{number:02}" for number in range(5)]
    old = dataset(substance("A"), *(substance(name) for name in names))
    new = dataset(interacting("A", "uncertain", *names), *(substance(name) for name in names))
    added = section(report(old, new, max_rows=2), "### Added interactions")
    assert added.count("| none | uncertain |") == 2
    assert "3 more row(s) not shown." in added


# Groups and cross tolerance


def _group(group_id: str, *members: str, name: str = "Group") -> dict[str, Any]:
    return {"id": group_id, "name": name, "members": list(members)}


def test_group_membership_changes_are_listed() -> None:
    old = dataset(
        interactionGroups=[_group("gone", "A"), _group("kept", "A", "B")],
        crossToleranceGroups=[_group("ct", "A", "B", name="Old")],
    )
    new = dataset(
        interactionGroups=[_group("kept", "A", "C"), _group("new", "B")],
        crossToleranceGroups=[_group("ct", "A", name="New")],
    )
    rows = compare(old, new).groups
    assert [(row.cells, row.protected) for row in rows] == [
        (("interaction group gone", "**group removed**", "A"), True),
        (("interaction group kept", "**members removed**", "B"), True),
        (("interaction group kept", "members added", "C"), False),
        (("interaction group new", "group added", "B"), False),
        (("cross tolerance group ct", "name changed", "n/a"), False),
        (("cross tolerance group ct", "**members removed**", "B"), False),
    ]


def test_an_empty_added_group_says_so() -> None:
    rows = compare(dataset(), dataset(interactionGroups=[_group("empty")])).groups
    assert rows[0].cells == ("interaction group empty", "group added", "none")


def test_a_renamed_member_is_not_a_membership_change() -> None:
    old = dataset(substance("Old"), interactionGroups=[_group("g", "Old")])
    new = dataset(substance("New", aliases=["Old"]), interactionGroups=[_group("g", "New")])
    assert compare(old, new).groups == []


def test_cross_tolerances_of_a_substance_are_compared() -> None:
    old = dataset(substance("A", crossTolerances=["x", "y"]))
    new = dataset(substance("A", crossTolerances=["y", "z"]))
    assert [row.cells for row in compare(old, new).groups] == [
        ("substance A", "cross tolerance removed", "x"),
        ("substance A", "cross tolerance added", "z"),
    ]


# Categories and texts


def test_texts_are_flagged_and_never_printed() -> None:
    old = dataset(substance("A", summary="Secret old words.", toxicities=["x"]))
    new = dataset(
        substance("A", toxicities=["y"], saferUse=["Secret new words."], categories=["c"])
    )
    result = compare(old, new)
    assert [row.cells for row in result.flags] == [
        (
            "substance A",
            "categories (changed), summary (removed), toxicities (changed), " "saferUse (added)",
        ),
    ]
    text = report(old, new)
    assert "Secret" not in text


def test_the_category_list_is_compared_by_id() -> None:
    old = dataset(
        categories=[
            {"id": "a", "name": "A", "description": "a"},
            {"id": "b", "name": "B", "description": "b"},
        ]
    )
    new = dataset(
        categories=[
            {"id": "b", "name": "B", "description": "changed"},
            {"id": "c", "name": "C", "description": "c"},
        ]
    )
    assert [row.cells for row in compare(old, new).flags] == [
        ("category a", "category removed"),
        ("category b", "description (changed)"),
        ("category c", "category added"),
    ]


def test_unchanged_substances_are_counted() -> None:
    old = dataset(substance("A"), substance("B", summary="x"))
    new = dataset(substance("A"), substance("B", summary="y"))
    assert "(unchanged substances: 1)" in report(old, new)


def test_versions_and_attribution_are_in_the_summary() -> None:
    new = dataset(
        datasetVersion="1.1.0",
        attribution=[{"name": "Other", "url": "https://example.org", "license": "CC0"}],
    )
    summary = section(report(dataset(), new), "## Summary")
    assert "- datasetVersion: 1\\.0\\.0 -> 1\\.1\\.0" in summary
    assert "- attribution: changed" in summary
    assert "schemaVersion" not in summary


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
        ("a\nb\tc\u2028d", "a b c d"),
        (f"x {EM_DASH} y", "x &#8212; y"),
        ("µg 4-HO-MET", "µg 4\\-HO\\-MET"),
        ("back\\slash", "back\\\\slash"),
    ],
)
def test_escape_keeps_text_literal_in_markdown(text: str, escaped: str) -> None:
    assert escape(text) == escaped


def test_a_name_with_a_pipe_keeps_the_table_shape() -> None:
    old = dataset(substance("A|B", roas=[_route(dose={"units": "m|g", "commonMin": 1})]))
    new = dataset(substance("A|B", roas=[_route(dose={"units": "m|g", "commonMin": 2})]))
    table = section(report(old, new), "## Doses, durations, tolerance and bioavailability")
    row = next(line for line in table.splitlines() if line.startswith("| A"))
    assert row == "| A\\|B | oral | dose commonMin | 1 m\\|g | 2 m\\|g | higher |"
    assert row.replace("\\|", "").count("|") == 7


def test_labels_are_escaped() -> None:
    text = render(compare(dataset(), dataset()), old_label="a|b", new_label="@x")
    assert "Old: a\\|b\n" in text
    assert "New: \\@&#8203;x\n" in text


# Loading


def test_load_dataset_refuses_an_invalid_document(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(dataset() | {"extra": 1}), encoding="utf-8")
    with pytest.raises(diff.DiffRefusedError, match="1 violation"):
        load_dataset(path)


@pytest.mark.parametrize("key", ["substances", "interactionGroups", "categories"])
def test_load_dataset_refuses_a_repeated_name_or_id(tmp_path: Path, key: str) -> None:
    entry = (
        substance("A")
        if key == "substances"
        else {"id": "a", "name": "A", "description": "a"} if key == "categories" else _group("a")
    )
    path = tmp_path / "twice.json"
    path.write_text(json.dumps(dataset(**{key: [entry, entry]})), encoding="utf-8")
    with pytest.raises(diff.DiffRefusedError, match=f"{key} has 'a' twice|{key} has 'A' twice"):
        load_dataset(path)


@pytest.mark.parametrize("content", ["{", '{"a": NaN}', '{"a": 1, "a": 2}'])
def test_load_dataset_refuses_text_that_is_not_strict_json(tmp_path: Path, content: str) -> None:
    path = tmp_path / "broken.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(diff.DiffInputError, match="strict JSON"):
        load_dataset(path)


def test_the_base_file_normalizes_to_a_valid_dataset() -> None:
    document = load_base_dataset(BASE_FILE)
    assert len(document["substances"]) == 289
    assert compare(document, copy.deepcopy(document)).numbers == []


def test_load_base_dataset_refuses_a_file_that_is_not_the_base_format(tmp_path: Path) -> None:
    path = tmp_path / "base.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(diff.DiffInputError, match="cannot read the base file"):
        load_base_dataset(path)


# Command line


def test_diff_writes_the_report_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    arguments = [str(FIXTURES / "old.json"), str(FIXTURES / "new.json")]
    assert main(["diff", *arguments, "--old-label", "old.json", "--new-label", "new.json"]) == 0
    assert capsys.readouterr().out == GOLDEN.read_text(encoding="utf-8")


def test_diff_writes_the_report_to_a_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "report.md"
    old, new = FIXTURES / "old.json", FIXTURES / "new.json"
    assert main(["diff", str(old), str(new), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8").startswith(
        f"# Dataset diff report\n\nOld: {escape(str(old))}"
    )
    assert capsys.readouterr().out == f"{output}: diff report of {old} and {new}\n"
    assert not (tmp_path / ".report.md.partial").exists()


def test_diff_compares_with_the_normalized_base_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = load_base_dataset(BASE_FILE) | {"datasetVersion": "1.0.0"}
    new = tmp_path / "new.json"
    new.write_text(json.dumps(document), encoding="utf-8")
    assert main(["diff", str(BASE_FILE), str(new), "--old-format", "base"]) == 0
    text = capsys.readouterr().out
    assert f"Old: {escape(str(BASE_FILE))} \\(base file, normalized\\)" in text
    assert "- Substances: 289 old, 289 new" in text
    assert "- Changed numbers and units: 0" in text
    assert "datasetVersion" not in text
    assert "attribution" not in text


def test_diff_refuses_an_invalid_dataset(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    assert main(["diff", str(FIXTURES / "old.json"), str(path)]) == 1
    assert "is not valid against the substances schema" in capsys.readouterr().err


def test_diff_reports_an_unreadable_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["diff", str(tmp_path / "missing.json"), str(FIXTURES / "new.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_diff_refuses_a_base_file_that_normalization_rejects(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise NormalizationError("two substances end up with one name")

    monkeypatch.setattr(diff, "normalize", refuse)
    code = main(["diff", str(BASE_FILE), str(FIXTURES / "new.json"), "--old-format", "base"])
    assert code == 1
    assert "two substances end up with one name" in capsys.readouterr().err


def test_diff_never_writes_over_an_input(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    new = tmp_path / "new.json"
    new.write_bytes((FIXTURES / "new.json").read_bytes())
    assert main(["diff", str(FIXTURES / "old.json"), str(new), "--output", str(new)]) == 1
    assert "is an input file" in capsys.readouterr().err
    assert new.read_bytes() == (FIXTURES / "new.json").read_bytes()


def test_diff_reports_an_output_it_cannot_write(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = tmp_path / "missing" / "report.md"
    assert (
        main(
            [
                "diff",
                str(FIXTURES / "old.json"),
                str(FIXTURES / "new.json"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert f"cannot write {output}" in capsys.readouterr().err


def test_diff_caps_sections_at_max_rows(capsys: pytest.CaptureFixture[str]) -> None:
    arguments = [str(FIXTURES / "old.json"), str(FIXTURES / "new.json"), "--max-rows", "1"]
    assert main(["diff", *arguments]) == 0
    assert "more row(s) not shown." in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_diff_refuses_a_max_rows_below_one(value: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["diff", "a", "b", "--max-rows", value])
    assert exit_info.value.code == 2


if __name__ == "__main__":
    GOLDEN.write_text(golden_report(), encoding="utf-8")
