# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the substances schema: one invalid fixture per rule, named after the rule."""

from collections.abc import Iterator
from typing import Any

import pytest

from tests.schema_fixtures import fixture_names, load_fixture
from zadrya_data.schema import SchemaName, load_schema, validate

# Fixture name: (JSON path of the violation, schema keyword that rejects it).
INVALID_FIXTURES = {
    "top-level-missing-substances": ("$", "required"),
    "top-level-unknown-property": ("$", "additionalProperties"),
    "top-level-not-an-object": ("$", "type"),
    "schema-version-not-semver": ("$.schemaVersion", "pattern"),
    "schema-version-major-not-1": ("$.schemaVersion", "pattern"),
    "dataset-version-not-semver": ("$.datasetVersion", "pattern"),
    "dataset-version-with-pre-release": ("$.datasetVersion", "pattern"),
    "attribution-empty": ("$.attribution", "minItems"),
    "attribution-missing-license": ("$.attribution[0]", "required"),
    "attribution-unknown-property": ("$.attribution[0]", "additionalProperties"),
    "attribution-url-not-https": ("$.attribution[0].url", "pattern"),
    "attribution-name-empty": ("$.attribution[0].name", "minLength"),
    "category-missing-description": ("$.categories[0]", "required"),
    "category-unknown-property-color": ("$.categories[0]", "additionalProperties"),
    "category-id-not-a-slug": ("$.categories[0].id", "pattern"),
    "substance-missing-name": ("$.substances[0]", "required"),
    "substance-unknown-property-is-approved": ("$.substances[0]", "additionalProperties"),
    "substance-name-empty": ("$.substances[0].name", "minLength"),
    "substance-aliases-not-a-list": ("$.substances[0].aliases", "type"),
    "substance-url-not-https": ("$.substances[0].url", "pattern"),
    "substance-url-not-a-psychonautwiki-article": ("$.substances[0].url", "pattern"),
    "substance-summary-not-a-string": ("$.substances[0].summary", "type"),
    "substance-category-not-a-slug": ("$.substances[0].categories[0]", "pattern"),
    "classes-missing-chemical": ("$.substances[0].classes", "required"),
    "classes-unknown-property": ("$.substances[0].classes", "additionalProperties"),
    "tolerance-empty": ("$.substances[0].tolerance", "minProperties"),
    "tolerance-unknown-property": ("$.substances[0].tolerance", "additionalProperties"),
    "tolerance-zero-not-a-string": ("$.substances[0].tolerance.zero", "type"),
    "cross-tolerance-not-a-lowercase-token": ("$.substances[0].crossTolerances[0]", "pattern"),
    "toxicities-not-a-list": ("$.substances[0].toxicities", "type"),
    "safer-use-not-a-list": ("$.substances[0].saferUse", "type"),
    "safer-use-empty": ("$.substances[0].saferUse", "minItems"),
    "roa-missing-route": ("$.substances[0].roas[0]", "required"),
    "roa-unknown-property": ("$.substances[0].roas[0]", "additionalProperties"),
    "roa-route-not-in-the-list": ("$.substances[0].roas[0].route", "enum"),
    "dose-missing-units": ("$.substances[0].roas[0].dose", "required"),
    "dose-unknown-property-light-min": ("$.substances[0].roas[0].dose", "additionalProperties"),
    "dose-units-empty": ("$.substances[0].roas[0].dose.units", "minLength"),
    "dose-threshold-negative": ("$.substances[0].roas[0].dose.threshold", "minimum"),
    "dose-heavy-not-a-number": ("$.substances[0].roas[0].dose.heavy", "type"),
    "dose-heavy-negative": ("$.substances[0].roas[0].dose.heavy", "minimum"),
    "dose-range-missing-max": ("$.substances[0].roas[0].dose.light", "required"),
    "dose-range-unknown-property": ("$.substances[0].roas[0].dose.light", "additionalProperties"),
    "dose-range-min-negative": ("$.substances[0].roas[0].dose.light.min", "minimum"),
    "dose-range-max-not-a-number": ("$.substances[0].roas[0].dose.light.max", "type"),
    "duration-empty": ("$.substances[0].roas[0].duration", "minProperties"),
    "duration-unknown-phase": ("$.substances[0].roas[0].duration", "additionalProperties"),
    "duration-range-empty": ("$.substances[0].roas[0].duration.onset", "minProperties"),
    "duration-range-unknown-property-units": (
        "$.substances[0].roas[0].duration.onset",
        "additionalProperties",
    ),
    "duration-range-min-negative": ("$.substances[0].roas[0].duration.onset.min", "minimum"),
    "duration-range-max-not-a-number": ("$.substances[0].roas[0].duration.onset.max", "type"),
    "bioavailability-empty": ("$.substances[0].roas[0].bioavailability", "minProperties"),
    "bioavailability-unknown-property": (
        "$.substances[0].roas[0].bioavailability",
        "additionalProperties",
    ),
    "bioavailability-min-negative": ("$.substances[0].roas[0].bioavailability.min", "minimum"),
    "bioavailability-max-above-100": ("$.substances[0].roas[0].bioavailability.max", "maximum"),
    "interaction-group-missing-members": ("$.interactionGroups[0]", "required"),
    "interaction-group-unknown-property": ("$.interactionGroups[0]", "additionalProperties"),
    "interaction-group-id-not-a-slug": ("$.interactionGroups[0].id", "pattern"),
    "interaction-group-members-not-a-list": ("$.interactionGroups[0].members", "type"),
    "interactions-missing-uncertain": ("$.substances[0].interactions", "required"),
    "interactions-unknown-severity": ("$.substances[0].interactions", "additionalProperties"),
    "interaction-target-not-an-object": ("$.substances[0].interactions.unsafe[0]", "type"),
    "interaction-target-missing-kind": ("$.substances[0].interactions.unsafe[0]", "required"),
    "interaction-target-unknown-property": (
        "$.substances[0].interactions.unsafe[0]",
        "additionalProperties",
    ),
    "interaction-target-kind-not-in-the-list": (
        "$.substances[0].interactions.unsafe[0].kind",
        "enum",
    ),
    "interaction-target-name-empty": ("$.substances[0].interactions.unsafe[0].name", "minLength"),
}
# Required keys of the top level ("") and of every definition, pinned here so
# that a key cannot become optional without a test changing.
REQUIRED = {
    "": [
        "schemaVersion",
        "datasetVersion",
        "attribution",
        "categories",
        "interactionGroups",
        "substances",
    ],
    "attribution": ["name", "url", "license"],
    "category": ["id", "name", "description"],
    "interactionGroup": ["id", "name", "members"],
    "substance": [
        "name",
        "aliases",
        "url",
        "categories",
        "classes",
        "roas",
        "crossTolerances",
        "interactions",
        "toxicities",
    ],
    "classes": ["psychoactive", "chemical"],
    "interactions": ["dangerous", "unsafe", "uncertain"],
    "interactionTarget": ["kind", "name"],
    "roa": ["route"],
    "dose": ["units"],
    "doseRange": ["min", "max"],
}


def _object_schemas(
    schema: dict[str, Any], where: str = "$"
) -> Iterator[tuple[str, dict[str, Any]]]:
    if schema.get("type") == "object":
        yield where, schema
    for group in ("properties", "$defs"):
        for name, child in schema.get(group, {}).items():
            yield from _object_schemas(child, f"{where}.{name}")
    if "items" in schema:
        yield from _object_schemas(schema["items"], f"{where}[]")


@pytest.mark.parametrize("name", fixture_names("substances", "valid"))
def test_valid_fixture_has_no_violations(name: str) -> None:
    assert validate(load_fixture("substances", "valid", name), SchemaName.SUBSTANCES) == []


@pytest.mark.parametrize("name", sorted(INVALID_FIXTURES))
def test_invalid_fixture_breaks_exactly_its_rule(name: str) -> None:
    violations = validate(load_fixture("substances", "invalid", name), SchemaName.SUBSTANCES)

    assert [(violation.path, violation.rule) for violation in violations] == [
        INVALID_FIXTURES[name]
    ]


def test_every_invalid_fixture_is_listed() -> None:
    assert fixture_names("substances", "invalid") == sorted(INVALID_FIXTURES)


def test_required_keys_are_pinned() -> None:
    schema = load_schema(SchemaName.SUBSTANCES)
    required = {"": schema["required"]} | {
        name: definition["required"]
        for name, definition in schema["$defs"].items()
        if "required" in definition
    }

    assert required == REQUIRED


def test_every_object_rejects_unknown_properties() -> None:
    objects = list(_object_schemas(load_schema(SchemaName.SUBSTANCES)))

    assert objects
    assert [
        where for where, schema in objects if schema.get("additionalProperties") is not False
    ] == []


def test_every_property_and_definition_has_a_description() -> None:
    schema = load_schema(SchemaName.SUBSTANCES)
    described = [
        (f"{where}.{name}", child)
        for where, parent in _object_schemas(schema)
        for name, child in parent["properties"].items()
    ] + [(f"$defs.{name}", child) for name, child in schema["$defs"].items()]

    assert [where for where, child in described if not child.get("description")] == []
