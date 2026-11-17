# SPDX-License-Identifier: GPL-3.0-or-later
"""Tolerance, cross tolerance and interactions of the real base file with a recorded API answer.

No network. ``graphql-relations.json`` holds the whole real entries (snapshot of
2026-11-16) of the substances whose relations normalization does something worth
pinning: 3-FMA (the API has no tolerance, no cross tolerance and no interactions),
Morphine (a token only the API has), N-Methylbisfluoromodafinil (``modafanil`` and
``analog``), Metizolam and Tianeptine (misspelled tokens), Acetylfentanyl and
2-Aminoindane (a target under two severities), Cannabis ("Mushrooms"), Caffeine (a
target only the API has), Dextromethorphan ("Antihistamine" and "Antihistamines"),
Modafinil and Alcohol (groups without members), Mirtazapine (its own group), Myristicin
("DPH") and Pregabalin ("SSRI").
"""

from typing import Any

import pytest

from tests.test_normalize_real import BASE_FILE, _snapshot
from zadrya_data.base import load_base
from zadrya_data.normalize import Kind, Normalized, Report, normalize
from zadrya_data.normalize.cross_tolerance import (
    CROSS_TOLERANCE_GROUPS,
    DROPPED_TOKENS,
    TOKEN_TO_GROUP,
    cross_tolerance_groups,
)
from zadrya_data.normalize.tolerance import minutes
from zadrya_data.snapshot import dump_json


@pytest.fixture(scope="module")
def relations() -> Normalized:
    base = load_base(BASE_FILE)
    return normalize(base, _snapshot(base, "graphql-relations.json"))


def _substance(result: Normalized, name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(s for s in result.document["substances"] if s["name"] == name)
    return found


def _details(result: Normalized, kind: Kind) -> list[tuple[str | None, str]]:
    return [(finding.substance, finding.detail) for finding in result.report.of(kind)]


def test_the_relations_are_deterministic() -> None:
    base = load_base(BASE_FILE)
    one = normalize(base, _snapshot(base, "graphql-relations.json"))
    two = normalize(base, _snapshot(base, "graphql-relations.json"))

    assert dump_json(one.document) == dump_json(two.document)
    assert one.report.findings == two.report.findings


def test_every_real_tolerance_wording_reads_as_a_time(relations: Normalized) -> None:
    times = [
        substance["tolerance"][field]
        for substance in relations.document["substances"]
        for field in ("half", "zero")
        if field in substance.get("tolerance", {})
    ]

    assert len(times) > 400
    assert all({"min", "max"} <= set(time) for time in times)
    assert relations.report.of(Kind.TOLERANCE_NOT_PARSED) == []


def test_real_tolerances(relations: Normalized) -> None:
    assert _substance(relations, "Metizolam")["tolerance"] == {
        "full": "within a couple of days of repeated administration",
        "half": {"text": "3 - 7 days", "min": 4320, "max": 10080},
        "zero": {"text": "1 - 2 weeks", "min": 10080, "max": 20160},
    }
    assert _substance(relations, "3-FMA")["tolerance"] == {
        "full": "develops with prolonged and repeated use",
        "half": {"text": "3 - 7 days", "min": 4320, "max": 10080},
        "zero": {"text": "1 - 10 days", "min": 1440, "max": 14400},
    }
    assert ("3-FMA", "zero: the API has no usable text, the base text '1 - 10 days' is used") in (
        _details(relations, Kind.TOLERANCE_FROM_BASE)
    )
    assert relations.report.of(Kind.TOLERANCE_DIFFERS) == []


def test_real_cross_tolerances(relations: Normalized) -> None:
    assert _substance(relations, "3-FMA")["crossTolerances"] == [
        "dopaminergic",
        "serotonergic",
        "stimulants",
    ]
    assert _substance(relations, "Metizolam")["crossTolerances"] == [
        "benzodiazepines",
        "thienodiazepines",
    ]
    assert _substance(relations, "Tianeptine")["crossTolerances"] == [
        "opioids",
        "tricyclic-antidepressants",
    ]
    assert _substance(relations, "N-Methylbisfluoromodafinil")["crossTolerances"] == [
        "modafinil-analogs"
    ]
    assert _details(relations, Kind.CROSS_TOLERANCE_TOKEN_DROPPED) == [
        (
            "N-Methylbisfluoromodafinil",
            "the token 'analog' names no group: it only qualifies the token next to it",
        )
    ]
    assert ("Morphine", "the token 'opioids' is only in the API") in _details(
        relations, Kind.CROSS_TOLERANCE_SOURCES_DIFFER
    )


def test_real_cross_tolerance_groups(relations: Normalized) -> None:
    groups = {group["id"]: group for group in relations.document["crossToleranceGroups"]}

    assert list(groups) == sorted(CROSS_TOLERANCE_GROUPS)
    assert groups["modafinil-analogs"] == {
        "id": "modafinil-analogs",
        "name": "Modafinil and its benzhydryl analogs",
        "members": ["Adrafinil", "Armodafinil", "Modafinil", "N-Methylbisfluoromodafinil"],
    }
    assert groups["thienodiazepines"]["members"] == ["Deschloroetizolam", "Etizolam", "Metizolam"]
    for group in groups.values():
        assert group["members"] == sorted(group["members"])
        for member in group["members"]:
            assert group["id"] in _substance(relations, member)["crossTolerances"]
    assert len(relations.report.of(Kind.CROSS_TOLERANCE_GROUP)) == len(groups)


def test_the_token_table_is_lower_case_and_names_known_groups() -> None:
    for token, group in TOKEN_TO_GROUP.items():
        assert token == token.casefold()
        assert group in CROSS_TOLERANCE_GROUPS or (group is None and token in DROPPED_TOKENS)
    assert set(CROSS_TOLERANCE_GROUPS) == {g for g in TOKEN_TO_GROUP.values() if g is not None}


def test_group_members_are_sorted_whatever_the_order_of_the_substances() -> None:
    report = Report()
    substances = [
        {"name": "b", "crossTolerances": ["opioids"]},
        {"name": "a", "crossTolerances": ["opioids"]},
    ]

    groups = cross_tolerance_groups(substances, report)

    assert groups == [{"id": "opioids", "name": "Opioids", "members": ["a", "b"]}]
    assert [(f.substance, f.detail) for f in report.findings] == [(None, "opioids (2): a, b")]


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("5 days", (7200, 7200)),
        ("3 - 7 days", (4320, 10080)),
        ("1-1.5 months", (43200, 64800)),
        ("2 weeks", (20160, 20160)),
        ("1 HOUR", (60, 60)),
        ("90 minutes", (90, 90)),
        ("0.5 minute", (0.5, 0.5)),
        ("5days", (7200, 7200)),
        ("5 dayss", None),
        ("five days", None),
        ("5 days or more", None),
        ("٣ days", None),
        ("3 – 7 days", None),
        ("7 - 3 days", None),
        ("1 year", None),
    ],
)
def test_tolerance_wordings_in_minutes(
    wording: str, expected: tuple[int | float, int | float] | None
) -> None:
    assert minutes(wording) == expected
