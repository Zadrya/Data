# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactions of the real base file with the recorded ``graphql-relations.json``. No network.

The base file lists interactions for every one of its substances, so the whole graph
of targets, groups and symmetric pairs is real; the recording adds the API lists of the
entries named in ``tests/test_normalize_relations.py``.
"""

from collections import Counter
from typing import Any

import pytest

from tests.test_normalize_real import BASE_FILE, _snapshot
from zadrya_data.base import load_base
from zadrya_data.normalize import Kind, Normalized, normalize
from zadrya_data.normalize.interaction_groups import GROUPS, NAME_TO_GROUP, group_of
from zadrya_data.normalize.interactions import SEVERITIES

EMPTY_GROUPS = {"aldh2-inhibitors", "hepatotoxic-drugs", "protease-inhibitors", "snris", "ssris"}


@pytest.fixture(scope="module")
def relations() -> Normalized:
    base = load_base(BASE_FILE)
    return normalize(base, _snapshot(base, "graphql-relations.json"))


def _by_name(result: Normalized) -> dict[str, dict[str, Any]]:
    return {substance["name"]: substance for substance in result.document["substances"]}


def _severity_of(substance: dict[str, Any], target: dict[str, str]) -> str | None:
    for severity in SEVERITIES:
        if target in substance["interactions"][severity]:
            return severity
    return None


def test_every_target_refers_to_something_that_exists(relations: Normalized) -> None:
    substances = _by_name(relations)
    groups = {group["id"] for group in relations.document["interactionGroups"]}
    for name, substance in substances.items():
        seen = []
        for severity in SEVERITIES:
            for target in substance["interactions"][severity]:
                if target["kind"] == "substance":
                    assert target["name"] in substances and target["name"] != name
                elif target["kind"] == "group":
                    assert target["groupId"] in groups
                seen.append(target)
        assert len(seen) == len({tuple(sorted(t.items())) for t in seen})


def test_substance_pairs_are_symmetric(relations: Normalized) -> None:
    substances = _by_name(relations)
    pairs = 0
    for name, substance in substances.items():
        for severity in SEVERITIES:
            for target in substance["interactions"][severity]:
                if target["kind"] == "substance":
                    back = {"kind": "substance", "name": name}
                    assert _severity_of(substances[target["name"]], back) == severity
                    pairs += 1
    assert pairs > 1500


def test_targets_are_sorted_by_kind_then_name(relations: Normalized) -> None:
    order = {"substance": 0, "group": 1, "other": 2}
    for substance in relations.document["substances"]:
        for severity in SEVERITIES:
            targets = substance["interactions"][severity]
            keys = [(order[t["kind"]], t.get("name", t.get("groupId"))) for t in targets]
            assert keys == sorted(keys)


def test_the_real_groups(relations: Normalized) -> None:
    groups = {group["id"]: group["members"] for group in relations.document["interactionGroups"]}

    assert set(groups) == set(GROUPS)
    assert {group for group, members in groups.items() if not members} == EMPTY_GROUPS
    assert relations.report.of(Kind.INTERACTION_GROUP_NAME_MISSING) == []
    assert groups["25x-nbome"] == ["25B-NBOMe", "25C-NBOMe", "25D-NBOMe", "25I-NBOMe", "25N-NBOMe"]
    assert groups["25x-nboh"] == ["25C-NBOH", "25I-NBOH"]  # 25E-NBOH is API-only, not recorded
    assert groups["2c-t-x"] == ["2C-T", "2C-T-2", "2C-T-21", "2C-T-7"]
    assert groups["5-meo-xxt"] == ["5-MeO-DALT", "5-MeO-DMT", "5-MeO-DiPT", "5-MeO-MiPT"]
    assert groups["dox"] == ["DOB", "DOC", "DOI", "DOM"]
    assert groups["maois"] == ["Ayahuasca"]
    assert "Βk-2C-B" in groups["2c-x"] and "2C-B-FLY" in groups["2c-x"]
    assert {"Amphetamine", "Dextroamphetamine", "3-FMA"} <= set(groups["substituted-amphetamines"])
    assert {"3-FMA", "MCPP", "NM-2-AI"} <= set(groups["serotonin-releasers"])
    assert not {"2C-B", "Psilocin", "Ayahuasca"} & set(groups["serotonin-releasers"])
    assert {"Oxazepam", "Triazolam", "Etizolam"} <= set(groups["benzodiazepines"])
    assert "Desomorphine" in groups["depressants"]
    assert len(relations.report.of(Kind.INTERACTION_GROUP)) == len(groups)


@pytest.mark.parametrize(
    ("spelling", "group"),
    [
        ("2C-T-x", "2c-t-x"),
        ("2C-T-X", "2c-t-x"),
        ("2C-x", "2c-x"),
        ("2C-X", "2c-x"),
        ("5-MeO-xxT", "5-meo-xxt"),
        ("5-MeO-xxt", "5-meo-xxt"),
        ("MAOI", "maois"),
        ("MAOIs", "maois"),
        ("maois", "maois"),
        ("NBOMe", "25x-nbome"),
        ("NBOMes", "25x-nbome"),
        ("25x-NBOMe", "25x-nbome"),
        ("Amphetamines", "substituted-amphetamines"),
        ("Substituted amphetamines", "substituted-amphetamines"),
        ("Antihistamine", "antihistamines"),
        ("Deliriant", "deliriants"),
        ("Depressant", "depressants"),
        ("SSRI", "ssris"),
        ("Hormonal Birth Control", "hormonal-birth-control"),
        ("Lithium", None),
    ],
)
def test_spelling_variants_of_the_data_name_one_group(spelling: str, group: str | None) -> None:
    assert group_of(spelling) == group


def test_the_name_table_is_lower_case_and_names_known_groups() -> None:
    assert all(name == name.casefold() for name in NAME_TO_GROUP)
    assert set(NAME_TO_GROUP.values()) == set(GROUPS)


def test_real_resolutions(relations: Normalized) -> None:
    substances = _by_name(relations)
    dxm = substances["Dextromethorphan"]["interactions"]
    cannabis = substances["Cannabis"]["interactions"]
    pregabalin = substances["Pregabalin"]["interactions"]

    assert {"kind": "group", "groupId": "antihistamines"} in dxm["dangerous"]
    assert {"kind": "other", "name": "Bupropion"} in dxm["unsafe"]
    assert {"kind": "substance", "name": "Psilocybin mushrooms"} in cannabis["uncertain"]
    assert {"kind": "other", "name": "Mushrooms"} in cannabis["uncertain"]
    assert {"kind": "group", "groupId": "ssris"} in pregabalin["uncertain"]
    assert {"kind": "substance", "name": "Diphenhydramine"} in (
        substances["Myristicin"]["interactions"]["dangerous"]
    )
    others = {
        target["name"]
        for substance in substances.values()
        for severity in SEVERITIES
        for target in substance["interactions"][severity]
        if target["kind"] == "other"
    }
    assert others == {"Bupropion", "Grapefruit", "Lithium", "Mushrooms", "Ritonavir", "Trazodone"}
    assert relations.report.of(Kind.INTERACTION_TARGET_DROPPED) == []


def test_real_findings(relations: Normalized) -> None:
    counts = Counter(finding.kind for finding in relations.report.findings)
    details = {(f.substance, f.detail) for f in relations.report.findings}

    assert counts[Kind.INTERACTION_SEVERITY_CONFLICT] == 14
    assert counts[Kind.INTERACTION_SYMMETRY_RAISED] == 3
    assert counts[Kind.INTERACTION_TARGET_OTHER] == 6
    assert (
        "Acetylfentanyl",
        "'maois' is listed as dangerous in base 'MAOI', API 'MAOIs'; "
        "uncertain in base 'MAOI', API 'MAOIs': dangerous is kept",
    ) in details
    assert ("3-FMA", "the API lists no interactions: every target (19) is from the base") in details
    assert ("Caffeine", "'Lithium' (uncertain) is only in the API") in details
    assert (
        "Tramadol",
        "'Alcohol' raised from uncertain to dangerous: 'Alcohol' lists 'Tramadol' as dangerous",
    ) in details
    assert (
        "Mirtazapine",
        "lists its own group 'antidepressants' (Antidepressants) as uncertain: kept, "
        "it may mean another substance of the same class",
    ) in details
    assert (
        None,
        "'Mushrooms' is neither a catalog substance nor a group: kept as other "
        "(listed by 1 substance)",
    ) in details
