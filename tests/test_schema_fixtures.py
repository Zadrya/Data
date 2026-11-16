# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests that run every schema fixture, and keep the files in step with their definition."""

import pytest

from tests.schema_cases import FIXTURES, INVALID, VALID, InvalidCase, render
from zadrya_data.schema import SchemaName, validate
from zadrya_data.strict_json import loads

VALID_FIXTURES = [(schema, name) for schema, cases in VALID.items() for name in cases()]
INVALID_FIXTURES = [(schema, case) for schema, cases in INVALID.items() for case in cases()]


def _load(schema: str, kind: str, name: str) -> object:
    return loads((FIXTURES / schema / kind / f"{name}.json").read_text(encoding="utf-8"))


def test_committed_fixtures_are_up_to_date() -> None:
    """If this fails, run ``uv run python -m tests.schema_cases`` and commit the result."""
    committed = {
        path.relative_to(FIXTURES).as_posix(): path.read_text(encoding="utf-8")
        for path in FIXTURES.rglob("*.json")
    }

    assert sorted(committed) == sorted(render())
    assert committed == render()


def test_fixture_names_are_unique() -> None:
    names = [(schema, case.name) for schema, case in INVALID_FIXTURES]

    assert len(names) == len(set(names))


@pytest.mark.parametrize(("schema", "name"), VALID_FIXTURES, ids=lambda value: str(value))
def test_valid_fixture_has_no_violations(schema: str, name: str) -> None:
    assert validate(_load(schema, "valid", name), SchemaName(schema)) == []


@pytest.mark.parametrize(
    ("schema", "case"),
    INVALID_FIXTURES,
    ids=[f"{schema}-{case.name}" for schema, case in INVALID_FIXTURES],
)
def test_invalid_fixture_breaks_exactly_its_rule(schema: str, case: InvalidCase) -> None:
    violations = validate(_load(schema, "invalid", case.name), SchemaName(schema))

    assert [(violation.path, violation.rule) for violation in violations] == [
        (case.path, case.rule)
    ]
