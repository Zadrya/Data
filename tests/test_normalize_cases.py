# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the reference cases of ``tests/fixtures/normalize``.

Each case is a small JSON file that documents one rule: ``rule`` states it, ``base``
and ``api`` give only the keys the rule is about (``tests/normalize_cases.py`` fills
in the rest), ``pages`` overrides wiki page records, ``expected`` lists the substances
of the result with the keys named in ``compare``, and ``report`` lists the findings of
the kinds named in ``reportKinds``, in order. The files are maintained by hand.
"""

from dataclasses import asdict

import pytest

from tests.normalize_cases import build, case_names, load_case
from zadrya_data.normalize import Kind, normalize


@pytest.mark.parametrize("name", case_names())
def test_reference_case(name: str) -> None:
    case = load_case(name)
    base, snapshot = build(case["base"], case["api"], case.get("pages"))

    result = normalize(base, snapshot)

    found = [
        {"name": substance["name"]}
        | {key: substance[key] for key in case["compare"] if key in substance}
        for substance in result.document["substances"]
    ]
    assert found == case["expected"]
    kinds = {Kind(kind) for kind in case["reportKinds"]}
    findings = [asdict(finding) for finding in result.report.findings if finding.kind in kinds]
    assert findings == case["report"]


@pytest.mark.parametrize("name", case_names())
def test_reference_case_states_its_rule(name: str) -> None:
    case = load_case(name)

    assert len(case["rule"]) > 40
    assert set(case) <= {
        "rule",
        "base",
        "api",
        "pages",
        "compare",
        "reportKinds",
        "expected",
        "report",
    }


def test_there_are_reference_cases_for_every_concern() -> None:
    prefixes = {name.split("-")[0] for name in case_names()}

    assert {
        "catalog",
        "aliases",
        "text",
        "categories",
        "classes",
        "routes",
        "dose",
        "duration",
    } <= prefixes
    assert "bioavailability" in prefixes
