# SPDX-License-Identifier: GPL-3.0-or-later
"""Every constraint of the schemas is pinned by a fixture: changing one changes a result.

Each mutant is a schema with one constraint loosened: one keyword of ``KEYWORDS``
removed, one entry of a ``required`` list or of a ``dependentRequired`` map removed,
or one entry of an ``enum`` removed or added. A mutant survives when every fixture,
valid and invalid, still gives the same violations. No mutant may survive, so a rule
cannot be dropped or loosened without a fixture noticing. Because every ``enum``
entry must be used by a valid fixture, an entry added to a schema without a fixture
fails here as well.

A schema may only use the keywords this test knows (``KEYWORDS`` and ``STRUCTURE``):
a new keyword such as ``minLength`` or ``uniqueItems`` fails until it is added here,
which is the moment to decide how it is mutated.

Not covered: a pattern that is widened instead of removed (no generic mutation exists
for that; the fixtures of each pattern are the only guard), and removing a
``properties`` entry or a ``oneOf`` branch, which makes documents invalid instead of
loosening a rule.
"""

import copy
import re
from collections.abc import Iterator
from typing import Any

import pytest

from tests.schema_cases import INVALID, VALID
from zadrya_data.schema import SchemaName, build_validator, load_schema, violations

KEYWORDS = (
    "$ref",
    "additionalProperties",
    "const",
    "enum",
    "format",
    "items",
    "maximum",
    "minItems",
    "minProperties",
    "minimum",
    "not",
    "oneOf",
    "pattern",
    "type",
)

# Keywords that hold structure or annotations and are not removed as a whole. The
# entries of required and dependentRequired are mutated one by one.
STRUCTURE = (
    "$comment",
    "$defs",
    "$id",
    "$schema",
    "dependentRequired",
    "description",
    "properties",
    "required",
    "title",
)

type Pointer = tuple[str | int, ...]


def _subschemas(schema: dict[str, Any], pointer: Pointer = ()) -> Iterator[Pointer]:
    yield pointer
    for group in ("properties", "$defs"):
        for name, child in schema.get(group, {}).items():
            yield from _subschemas(child, (*pointer, group, name))
    for keyword in ("items", "not"):
        if keyword in schema:
            yield from _subschemas(schema[keyword], (*pointer, keyword))
    for index, child in enumerate(schema.get("oneOf", [])):
        yield from _subschemas(child, (*pointer, "oneOf", index))


def _at(schema: Any, pointer: Pointer) -> Any:
    for step in pointer:
        schema = schema[step]
    return schema


def _value_at(document: Any, json_path: str) -> Any:
    """Return the value at a JSON path such as ``$.substances[0].roas[0].route``."""
    for key, index in re.findall(r"\.([A-Za-z0-9]+)|\[([0-9]+)\]", json_path):
        document = document[key] if key else document[int(index)]
    return document


def _mutants(
    schema: dict[str, Any], enum_additions: list[Any]
) -> Iterator[tuple[str, dict[str, Any]]]:
    for pointer in _subschemas(schema):
        where = "/".join(str(step) for step in pointer) or "(top level)"
        node = _at(schema, pointer)
        for keyword in KEYWORDS:
            if keyword in node:
                mutant = copy.deepcopy(schema)
                del _at(mutant, pointer)[keyword]
                yield f"{where}: without {keyword}", mutant
        for keyword in ("required", "dependentRequired"):
            for entry in node.get(keyword, []):
                mutant = copy.deepcopy(schema)
                target = _at(mutant, pointer)[keyword]
                if isinstance(target, list):
                    target.remove(entry)
                else:
                    del target[entry]
                yield f"{where}: {keyword} without {entry}", mutant
        for entry in node.get("enum", []):
            mutant = copy.deepcopy(schema)
            _at(mutant, pointer)["enum"].remove(entry)
            yield f"{where}: enum without {entry}", mutant
        for entry in enum_additions if "enum" in node else []:
            mutant = copy.deepcopy(schema)
            _at(mutant, pointer)["enum"].append(entry)
            yield f"{where}: enum with {entry} added", mutant


def _results(schema: dict[str, Any], documents: list[Any]) -> Iterator[list[tuple[str, str]]]:
    validator = build_validator(schema)
    for document in documents:
        yield [(violation.path, violation.rule) for violation in violations(validator, document)]


@pytest.mark.parametrize("name", list(SchemaName))
def test_schema_uses_only_keywords_this_test_knows(name: SchemaName) -> None:
    schema = load_schema(name)
    unknown = sorted(
        {
            f"{'/'.join(str(step) for step in pointer) or '(top level)'}: {keyword}"
            for pointer in _subschemas(schema)
            for keyword in _at(schema, pointer)
            if keyword not in KEYWORDS and keyword not in STRUCTURE
        }
    )

    assert unknown == []


@pytest.mark.parametrize("name", list(SchemaName))
def test_no_constraint_can_be_loosened_without_a_fixture_noticing(name: SchemaName) -> None:
    schema = load_schema(name)
    invalid = INVALID[name.value]()
    documents = [*VALID[name.value]().values()]
    documents += [case.document for case in invalid]
    expected = list(_results(schema, documents))
    # An enum is widened with the values that fixtures use to break an enum.
    enum_additions = [
        _value_at(case.document, case.path) for case in invalid if case.rule == "enum"
    ]
    has_enum = any("enum" in _at(schema, pointer) for pointer in _subschemas(schema))

    mutants = list(_mutants(schema, enum_additions))
    survivors = [
        label
        for label, mutant in mutants
        if all(found == wanted for found, wanted in zip(_results(mutant, documents), expected))
    ]

    assert len(mutants) > 20
    assert bool(enum_additions) == has_enum
    assert survivors == []


def test_the_keyword_check_and_the_enum_mutations_bite() -> None:
    """The guards themselves are tested on a small schema, so they cannot rot silently."""
    schema = {
        "type": "object",
        "properties": {"route": {"enum": ["oral", "smoked"], "minLength": 1}},
    }

    labels = [label for label, _ in _mutants(schema, ["vaped"])]

    assert "properties/route: enum without oral" in labels
    assert "properties/route: enum without smoked" in labels
    assert "properties/route: enum with vaped added" in labels
    assert "minLength" not in KEYWORDS and "minLength" not in STRUCTURE
    assert "uniqueItems" not in KEYWORDS and "uniqueItems" not in STRUCTURE
