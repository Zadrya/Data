# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the manifest schema: one invalid fixture per rule, named after the rule."""

import pytest

from tests.schema_fixtures import fixture_names, load_fixture
from zadrya_data.schema import SchemaName, load_schema, validate

# Fixture name: (JSON path of the violation, schema keyword that rejects it).
INVALID_FIXTURES = {
    "missing-sha256": ("$", "required"),
    "unknown-property": ("$", "additionalProperties"),
    "dataset-version-not-semver": ("$.datasetVersion", "pattern"),
    "schema-version-not-semver": ("$.schemaVersion", "pattern"),
    "min-app-version-not-semver": ("$.minAppVersion", "pattern"),
    "sha256-uppercase": ("$.sha256", "pattern"),
    "sha256-too-short": ("$.sha256", "pattern"),
    "sha256-not-a-string": ("$.sha256", "type"),
    "date-not-iso-8601": ("$.date", "format"),
    "date-with-time": ("$.date", "format"),
    "date-not-a-calendar-day": ("$.date", "format"),
    "attribution-empty": ("$.attribution", "minItems"),
    "attribution-missing-license": ("$.attribution[0]", "required"),
    "attribution-unknown-property": ("$.attribution[0]", "additionalProperties"),
    "attribution-url-not-https": ("$.attribution[0].url", "pattern"),
    "attribution-license-empty": ("$.attribution[0].license", "minLength"),
}


@pytest.mark.parametrize("name", fixture_names("manifest", "valid"))
def test_valid_fixture_has_no_violations(name: str) -> None:
    assert validate(load_fixture("manifest", "valid", name), SchemaName.MANIFEST) == []


@pytest.mark.parametrize("name", sorted(INVALID_FIXTURES))
def test_invalid_fixture_breaks_exactly_its_rule(name: str) -> None:
    violations = validate(load_fixture("manifest", "invalid", name), SchemaName.MANIFEST)

    assert [(violation.path, violation.rule) for violation in violations] == [
        INVALID_FIXTURES[name]
    ]


def test_every_invalid_fixture_is_listed() -> None:
    assert fixture_names("manifest", "invalid") == sorted(INVALID_FIXTURES)


def test_every_key_is_required_and_described() -> None:
    schema = load_schema(SchemaName.MANIFEST)

    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    assert all(child.get("description") for child in schema["properties"].values())


def test_attribution_has_the_same_shape_as_in_the_substances_schema() -> None:
    manifest = load_schema(SchemaName.MANIFEST)["$defs"]
    substances = load_schema(SchemaName.SUBSTANCES)["$defs"]

    for definition in ("attribution", "semver", "text"):
        assert manifest[definition] == substances[definition]
