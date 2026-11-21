# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the comparison behind the diff report. No network."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.diff_cases import BASE_FILE, dataset, group, interacting, oral, substance
from zadrya_data.diff import (
    Change,
    DiffInputError,
    DiffRefusedError,
    Risk,
    Row,
    compare,
    load_base_dataset,
    load_dataset,
)


def _cells(rows: list[Row]) -> list[tuple[str, ...]]:
    return [row.cells for row in rows]


# Substances


def test_identical_datasets_have_no_difference() -> None:
    document = dataset(substance("A"), substance("B", summary="x"))
    result = compare(document, copy.deepcopy(document))
    assert result.added == result.removed == []
    assert result.renamed == []
    assert result.numbers == result.groups == result.flags == []
    assert all(not rows for rows in result.interactions.values())
    assert result.unflagged == 2
    assert result.risks() == {}


def test_added_and_removed_substances_are_sorted_by_name() -> None:
    result = compare(
        dataset(substance("B"), substance("A")), dataset(substance("D"), substance("C"))
    )
    assert result.removed == ["A", "B"]
    assert result.added == ["C", "D"]
    assert result.risks() == {Risk.REMOVED_SUBSTANCE: 2}


def test_the_same_address_makes_a_rename() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    result = compare(
        dataset(substance("Old", url=url)), dataset(substance("New", url=url, aliases=["Old"]))
    )
    assert [(r.old, r.new, r.reason) for r in result.renamed] == [
        ("Old", "New", "New lists Old as an alias")
    ]
    assert result.added == result.removed == []
    assert result.risks() == {Risk.RENAMED_SUBSTANCE: 1}


def test_a_rename_by_address_alone_says_so() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    result = compare(dataset(substance("Old", url=url)), dataset(substance("New", url=url)))
    assert [r.reason for r in result.renamed] == ["same address"]


def test_an_alias_at_another_address_is_only_a_hint() -> None:
    result = compare(dataset(substance("A")), dataset(substance("C", aliases=["A"])))
    assert result.renamed == []
    assert result.removed == ["A"]
    assert result.added == ["C"]
    assert result.hints == {"A": "possible rename: C lists A as an alias, at another address"}


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (substance("Lsd"), substance("LSD"), "same name but for case"),
        (substance("Molly"), substance("MDMA", aliases=["molly"]), "MDMA lists Molly as an alias"),
        (substance("MDMA", aliases=["Molly"]), substance("Molly"), "MDMA listed Molly as an alias"),
    ],
)
def test_without_an_address_a_name_or_alias_match_is_a_rename(
    old: dict[str, Any], new: dict[str, Any], reason: str
) -> None:
    del old["url"], new["url"]
    result = compare({"substances": [old]} | _top(), {"substances": [new]} | _top())
    assert [(r.old, r.new, r.reason) for r in result.renamed] == [
        (old["name"], new["name"], reason)
    ]


def _top() -> dict[str, Any]:
    return {key: value for key, value in dataset().items() if key != "substances"}


def test_an_ambiguous_rename_stays_added_and_removed() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    old = dataset(substance("Molly", url=url))
    new = dataset(substance("MDMA", url=url), substance("MDA", url=url))
    result = compare(old, new)
    assert result.renamed == []
    assert result.removed == ["Molly"]
    assert result.added == ["MDA", "MDMA"]


def test_a_renamed_substance_is_compared_with_its_old_self() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    old = dataset(substance("Old", url=url, roas=[oral(dose={"units": "mg", "lightMin": 1})]))
    new = dataset(substance("New", url=url, roas=[oral(dose={"units": "mg", "lightMin": 2})]))
    result = compare(old, new)
    assert _cells(result.numbers) == [("New", "oral", "dose lightMin", "1 mg", "2 mg", "higher")]
    assert result.unflagged == 1


# Doses


def _numbers(old_route: dict[str, Any], new_route: dict[str, Any]) -> list[Row]:
    return compare(
        dataset(substance("A", roas=[old_route])), dataset(substance("A", roas=[new_route]))
    ).numbers


def _summary(rows: list[Row]) -> list[tuple[str, str, Risk | None, bool]]:
    return [(row.cells[2], row.cells[5], row.risk, row.added) for row in rows]


def test_dose_boundaries_report_direction_risk_and_notes() -> None:
    old = oral(dose={"units": "mg", "thresholdMin": 1, "commonMin": 5, "strongMin": 10})
    new = oral(dose={"units": "mg", "lightMin": 2, "commonMin": 6, "heavyMin": 20})
    assert _summary(_numbers(old, new)) == [
        ("dose thresholdMin", "removed", None, False),
        ("dose lightMin", "added", None, True),
        (
            "dose commonMin",
            "higher (note: doses from 5 to 6 mg now show in the class below)",
            None,
            False,
        ),
        (
            "dose strongMin",
            "removed (risky: higher doses now show in a lower class)",
            Risk.RISKY_DOSE,
            False,
        ),
        ("dose heavyMin", "added", None, True),
    ]


@pytest.mark.parametrize("boundary", ["strongMin", "heavyMin"])
def test_a_higher_strong_or_heavy_boundary_is_risky(boundary: str) -> None:
    rows = _numbers(
        oral(dose={"units": "mg", boundary: 30}), oral(dose={"units": "mg", boundary: 35})
    )
    assert _summary(rows) == [
        (
            f"dose {boundary}",
            "higher (risky: doses from 30 to 35 mg now show in the class below)",
            Risk.RISKY_DOSE,
            False,
        )
    ]


def test_lower_boundaries_are_not_marked() -> None:
    old = oral(dose={"units": "mg", "thresholdMin": 2, "lightMin": 3, "strongMin": 9})
    new = oral(dose={"units": "mg", "thresholdMin": 1, "lightMin": 2, "strongMin": 8})
    assert [row.cells[5] for row in _numbers(old, new)] == ["lower"] * 3
    assert all(row.risk is None for row in _numbers(old, new))


def test_changed_units_are_one_row_with_both_blocks() -> None:
    rows = _numbers(
        oral(dose={"units": "mg", "commonMin": 5, "strongMin": 10}),
        oral(dose={"units": "g", "commonMin": 0.005}),
    )
    assert [(row.cells, row.risk) for row in rows] == [
        (
            (
                "A",
                "oral",
                "dose",
                "units mg; commonMin 5; strongMin 10",
                "units g; commonMin 0.005",
                "units differ",
            ),
            Risk.CHANGED_UNITS,
        )
    ]


def test_a_dose_block_that_appears_or_disappears_is_reported() -> None:
    with_dose = oral(dose={"units": "mg", "strongMin": 3})
    assert _summary(_numbers(oral(), with_dose)) == [
        ("dose units", "added", None, True),
        ("dose strongMin", "added", None, True),
    ]
    assert _summary(_numbers(with_dose, oral())) == [
        ("dose units", "removed", None, False),
        (
            "dose strongMin",
            "removed (risky: higher doses now show in a lower class)",
            Risk.RISKY_DOSE,
            False,
        ),
    ]


# Durations, bioavailability, routes, tolerance


@pytest.mark.parametrize("phase", ["onset", "comeup", "peak", "offset", "total", "afterglow"])
def test_a_lower_or_removed_duration_bound_is_risky(phase: str) -> None:
    old = oral(duration={phase: {"min": 30, "max": 60}})
    new = oral(duration={phase: {"min": 20}})
    assert _summary(_numbers(old, new)) == [
        (
            f"duration {phase} min",
            "lower (risky: the app shows a shorter timeline)",
            Risk.RISKY_DURATION,
            False,
        ),
        (
            f"duration {phase} max",
            "removed (risky: the app shows a shorter timeline)",
            Risk.RISKY_DURATION,
            False,
        ),
    ]


def test_a_longer_or_added_duration_bound_is_not_risky() -> None:
    old = oral(duration={"total": {"min": 30}})
    new = oral(duration={"total": {"min": 40, "max": 90}})
    assert _summary(_numbers(old, new)) == [
        ("duration total min", "higher", None, False),
        ("duration total max", "added", None, True),
    ]


def test_bioavailability_is_never_risky() -> None:
    rows = _numbers(oral(bioavailability={"max": 50}), oral(bioavailability={"min": 5}))
    assert [(row.cells[3:], row.risk) for row in rows] == [
        (("none", "5 %", "added"), None),
        (("50 %", "none", "removed"), None),
    ]


def test_routes_that_appear_or_disappear_are_reported_in_schema_order() -> None:
    result = compare(
        dataset(substance("A", roas=[{"route": "smoked"}, {"route": "oral"}])),
        dataset(substance("A", roas=[{"route": "insufflated"}])),
    )
    assert [(row.cells[1], row.cells[5], row.risk) for row in result.numbers] == [
        ("oral", "removed", Risk.REMOVED_ROUTE),
        ("insufflated", "added", None),
        ("smoked", "removed", Risk.REMOVED_ROUTE),
    ]


def test_a_removed_tolerance_value_is_never_left_out() -> None:
    old = substance(
        "A", tolerance={"full": "soon", "zero": {"text": "1 day", "min": 1440, "max": 1440}}
    )
    new = substance(
        "A", tolerance={"full": "later", "half": {"text": "2 days", "min": 2880, "max": 2880}}
    )
    rows = compare(dataset(old), dataset(new)).numbers
    assert [(row.cells[2:], row.risk) for row in rows] == [
        (("tolerance full", "soon", "later", "changed"), None),
        (("tolerance half", "none", "2 days", "added"), None),
        (("tolerance half min", "none", "2880 min", "added"), None),
        (("tolerance half max", "none", "2880 min", "added"), None),
        (("tolerance zero", "1 day", "none", "removed"), Risk.REMOVED_TOLERANCE),
        (("tolerance zero min", "1440 min", "none", "removed"), Risk.REMOVED_TOLERANCE),
        (("tolerance zero max", "1440 min", "none", "removed"), Risk.REMOVED_TOLERANCE),
    ]
    assert all(row.cells[1] == "all routes" for row in rows)


def test_an_integer_and_the_same_float_are_not_a_change() -> None:
    assert _numbers(oral(bioavailability={"min": 5}), oral(bioavailability={"min": 5.0})) == []


def test_floats_are_written_in_their_shortest_exact_form() -> None:
    rows = _numbers(oral(bioavailability={"min": 0.1}), oral(bioavailability={"min": 2.5e-7}))
    assert rows[0].cells[3:5] == ("0.1 %", "2.5e-07 %")


def test_rows_of_one_kind_share_a_group() -> None:
    old = dataset(*(substance(n, roas=[oral(dose={"units": "mg"})]) for n in "AB"))
    new = dataset(*(substance(n, roas=[oral(dose={"units": "mg", "lightMin": 1})]) for n in "AB"))
    assert {row.group for row in compare(old, new).numbers} == {"dose lightMin added"}


def test_both_bounds_of_a_range_share_a_group() -> None:
    rows = _numbers(oral(), oral(duration={"peak": {"min": 1, "max": 2}}))
    assert [row.group for row in rows] == ["duration peak added", "duration peak added"]


# Interactions


def test_interaction_changes_are_classified() -> None:
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
    rows = compare(old, new).interactions
    assert {change: [(r.cells, r.risk) for r in rows[change]] for change in Change} == {
        Change.LOWERED: [(("A", "B", "dangerous", "unsafe"), Risk.LOWERED_INTERACTION)],
        Change.REMOVED: [(("C", "D", "unsafe", "none"), Risk.REMOVED_INTERACTION)],
        Change.RAISED: [(("B", "C", "uncertain", "dangerous"), None)],
        Change.ADDED: [(("A", "D", "none", "uncertain"), None)],
    }


def test_a_pair_takes_the_higher_severity_of_both_directions() -> None:
    old = dataset(interacting("A", "dangerous", "B"), interacting("B", "uncertain", "A"))
    new = dataset(substance("A"), interacting("B", "uncertain", "A"))
    rows = compare(old, new).interactions
    assert _cells(rows[Change.LOWERED]) == [("A", "B", "dangerous", "uncertain")]
    assert not rows[Change.REMOVED] and not rows[Change.RAISED] and not rows[Change.ADDED]


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
    assert _cells(rows) == [
        ("A", "group opioids", "dangerous", "none"),
        ("A", "other: Grapefruit", "unsafe", "none"),
    ]


def test_a_rename_does_not_change_the_interactions_of_the_substance() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    old = dataset(
        interacting("Old", "dangerous", "B") | {"url": url}, interacting("B", "dangerous", "Old")
    )
    new = dataset(
        interacting("New", "dangerous", "B") | {"url": url}, interacting("B", "dangerous", "New")
    )
    assert all(not rows for rows in compare(old, new).interactions.values())


# Groups and cross tolerance


def test_group_membership_changes_carry_their_risk() -> None:
    old = dataset(
        interactionGroups=[group("gone", "A"), group("kept", "A", "B")],
        crossToleranceGroups=[group("ct", "A", "B", name="Old"), group("old-ct", "A")],
    )
    new = dataset(
        interactionGroups=[group("kept", "A", "C"), group("new", "B")],
        crossToleranceGroups=[group("ct", "A", name="New")],
    )
    assert [(row.cells, row.risk) for row in compare(old, new).groups] == [
        (("interaction group gone", "group removed", "A"), Risk.REMOVED_GROUP),
        (("interaction group kept", "members removed", "B"), Risk.REMOVED_INTERACTION_MEMBER),
        (("interaction group kept", "members added", "C"), None),
        (("interaction group new", "group added", "B"), None),
        (("cross tolerance group ct", "name changed", "n/a"), None),
        (("cross tolerance group ct", "members removed", "B"), Risk.REMOVED_CROSS_TOLERANCE),
        (("cross tolerance group old-ct", "group removed", "A"), Risk.REMOVED_GROUP),
    ]


def test_an_empty_group_lists_none() -> None:
    rows = compare(dataset(), dataset(interactionGroups=[group("empty")])).groups
    assert rows[0].cells == ("interaction group empty", "group added", "none")


def test_a_renamed_member_is_not_a_membership_change() -> None:
    url = "https://psychonautwiki.org/wiki/X"
    old = dataset(substance("Old", url=url), interactionGroups=[group("g", "Old")])
    new = dataset(substance("New", url=url), interactionGroups=[group("g", "New")])
    assert compare(old, new).groups == []


def test_cross_tolerances_of_a_substance_are_compared() -> None:
    old = dataset(substance("A", crossTolerances=["x", "y"]))
    new = dataset(substance("A", crossTolerances=["y", "z"]))
    assert [(row.cells, row.risk) for row in compare(old, new).groups] == [
        (("substance A", "cross tolerance removed", "x"), Risk.REMOVED_CROSS_TOLERANCE),
        (("substance A", "cross tolerance added", "z"), None),
    ]


# Categories and texts


def test_texts_are_flagged_by_field() -> None:
    old = dataset(substance("A", summary="old", toxicities=["x"]))
    new = dataset(substance("A", toxicities=["y"], saferUse=["new"], categories=["c"]))
    rows = compare(old, new).flags
    assert [(row.cells, row.group) for row in rows] == [
        (("substance A", "categories changed"), "categories changed"),
        (("substance A", "summary removed"), "summary removed"),
        (("substance A", "toxicities changed"), "toxicities changed"),
        (("substance A", "saferUse added"), "saferUse added"),
    ]


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
    assert _cells(compare(old, new).flags) == [
        ("category a", "category removed"),
        ("category b", "description changed"),
        ("category c", "category added"),
    ]


def test_versions_and_attribution_are_compared_unless_asked_not_to() -> None:
    new = dataset(
        datasetVersion="1.1.0",
        attribution=[{"name": "Other", "url": "https://example.org", "license": "CC0"}],
    )
    assert compare(dataset(), new).versions == [
        "datasetVersion: 1.0.0 -> 1.1.0",
        "attribution: changed",
    ]
    assert compare(dataset(), new, versions=False).versions == []


# Risk counts


def test_risks_count_every_protected_kind_in_order() -> None:
    url = "https://psychonautwiki.org/wiki/R"
    old = dataset(
        interacting("A", "dangerous", "B", "C"),
        substance(
            "B",
            roas=[oral(dose={"units": "mg", "strongMin": 5}), {"route": "smoked"}],
            tolerance={"full": "x"},
            crossTolerances=["ct"],
        ),
        substance("C", roas=[oral(dose={"units": "mg"}, duration={"total": {"max": 60}})]),
        substance("Gone"),
        substance("Old", url=url),
        interactionGroups=[group("g", "B", "C"), group("lost")],
    )
    new = dataset(
        interacting("A", "unsafe", "B"),
        substance("B", roas=[oral(dose={"units": "mg", "strongMin": 6})]),
        substance("C", roas=[oral(dose={"units": "g"}, duration={"total": {"max": 50}})]),
        substance("New", url=url),
        interactionGroups=[group("g", "B")],
    )
    risks = compare(old, new).risks()
    assert list(risks.items()) == [
        (Risk.LOWERED_INTERACTION, 1),
        (Risk.REMOVED_INTERACTION, 1),
        (Risk.REMOVED_INTERACTION_MEMBER, 1),
        (Risk.REMOVED_GROUP, 1),
        (Risk.REMOVED_SUBSTANCE, 1),
        (Risk.RENAMED_SUBSTANCE, 1),
        (Risk.REMOVED_ROUTE, 1),
        (Risk.CHANGED_UNITS, 1),
        (Risk.RISKY_DOSE, 1),
        (Risk.RISKY_DURATION, 1),
        (Risk.REMOVED_TOLERANCE, 1),
        (Risk.REMOVED_CROSS_TOLERANCE, 1),
    ]


def test_a_single_group_member_removal_is_counted() -> None:
    old = dataset(interactionGroups=[group("stimulants", "A", "B")])
    new = dataset(interactionGroups=[group("stimulants", "A")])
    assert compare(old, new).risks() == {Risk.REMOVED_INTERACTION_MEMBER: 1}


def test_a_single_strong_boundary_rise_is_counted() -> None:
    old = dataset(substance("A", roas=[oral(dose={"units": "mg", "strongMin": 30})]))
    new = dataset(substance("A", roas=[oral(dose={"units": "mg", "strongMin": 35})]))
    assert compare(old, new).risks() == {Risk.RISKY_DOSE: 1}


# Loading


def test_load_dataset_refuses_an_invalid_document(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(dataset() | {"extra": 1}), encoding="utf-8")
    with pytest.raises(DiffRefusedError, match="1 violation"):
        load_dataset(path)


@pytest.mark.parametrize(
    ("key", "entry", "name"),
    [
        ("substances", substance("A"), "A"),
        ("interactionGroups", group("a"), "a"),
        ("categories", {"id": "a", "name": "A", "description": "a"}, "a"),
    ],
)
def test_load_dataset_refuses_a_repeated_name_or_id(
    tmp_path: Path, key: str, entry: dict[str, Any], name: str
) -> None:
    path = tmp_path / "twice.json"
    path.write_text(json.dumps(dataset(**{key: [entry, entry]})), encoding="utf-8")
    with pytest.raises(DiffRefusedError, match=f"{key} has '{name}' twice"):
        load_dataset(path)


@pytest.mark.parametrize("content", ["{", '{"a": NaN}', '{"a": 1, "a": 2}'])
def test_load_dataset_refuses_text_that_is_not_strict_json(tmp_path: Path, content: str) -> None:
    path = tmp_path / "broken.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DiffInputError, match="strict JSON"):
        load_dataset(path)


def test_the_base_file_normalizes_to_a_valid_dataset() -> None:
    document = load_base_dataset(BASE_FILE)
    assert len(document["substances"]) == 289
    assert compare(document, copy.deepcopy(document)).numbers == []


def test_load_base_dataset_refuses_a_file_that_is_not_the_base_format(tmp_path: Path) -> None:
    path = tmp_path / "base.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(DiffInputError, match="cannot read the base file"):
        load_base_dataset(path)


def test_unrelated_substances_without_an_address_are_not_a_rename() -> None:
    old, new = substance("A"), substance("B")
    del old["url"], new["url"]
    result = compare({"substances": [old]} | _top(), {"substances": [new]} | _top())
    assert (result.renamed, result.removed, result.added, result.hints) == ([], ["A"], ["B"], {})


def test_a_row_is_protected_exactly_when_it_has_a_risk() -> None:
    assert Row(("a",), Risk.RISKY_DOSE).protected
    assert not Row(("a",)).protected
