# SPDX-License-Identifier: GPL-3.0-or-later
"""Tolerance of the real base file with a recorded API answer. No network.

``graphql-relations.json`` holds the whole real entries (snapshot of 2026-11-16) of the
substances whose relations normalization does something worth pinning: 3-FMA (the API
has no tolerance), Metizolam, Morphine, N-Methylbisfluoromodafinil and Tianeptine.
"""

from typing import Any

import pytest

from tests.test_normalize_real import BASE_FILE, _snapshot
from zadrya_data.base import load_base
from zadrya_data.normalize import Kind, Normalized, normalize
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
