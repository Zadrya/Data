# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for schema loading and validation that apply to every schema."""

import pytest
from jsonschema import Draft202012Validator

from zadrya_data.schema import SCHEMA_VERSION, SchemaName, SchemaViolation, load_schema, validate


@pytest.mark.parametrize("name", list(SchemaName))
def test_schema_is_a_valid_draft_2020_12_schema(name: SchemaName) -> None:
    schema = load_schema(name)

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("name", list(SchemaName))
def test_schema_states_its_version(name: SchemaName) -> None:
    assert f"Schema version {SCHEMA_VERSION}." in load_schema(name)["$comment"]


def test_violations_are_ordered_by_path() -> None:
    violations = validate({"schemaVersion": 1, "datasetVersion": 1}, SchemaName.SUBSTANCES)

    paths = [violation.path for violation in violations]
    assert paths == sorted(paths)
    assert "$.datasetVersion" in paths and "$.schemaVersion" in paths


def test_violation_reads_as_path_message_and_rule() -> None:
    violation = SchemaViolation(path="$.name", rule="minLength", message="'' is too short")

    assert str(violation) == "$.name: '' is too short (minLength)"
