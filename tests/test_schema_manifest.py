# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the structure of the manifest schema. The fixtures run in test_schema_fixtures."""

from zadrya_data.schema import SchemaName, load_schema


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
