# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the structure of the substances schema. The fixtures run in test_schema_fixtures."""

from collections.abc import Iterator
from typing import Any

from zadrya_data.schema import SchemaName, load_schema

# Required keys of the top level ("") and of every definition, pinned here so
# that a key cannot become optional without a test changing.
REQUIRED = {
    "": [
        "schemaVersion",
        "datasetVersion",
        "attribution",
        "categories",
        "interactionGroups",
        "crossToleranceGroups",
        "substances",
    ],
    "attribution": ["name", "url", "license"],
    "category": ["id", "name", "description"],
    "substanceGroup": ["id", "name", "members"],
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
    "toleranceTime": ["text"],
    "interactions": ["dangerous", "unsafe", "uncertain"],
    "interactionTarget": ["kind", "name"],
    "roa": ["route"],
    "dose": ["units"],
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
