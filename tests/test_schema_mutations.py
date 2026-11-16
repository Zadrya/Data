# SPDX-License-Identifier: GPL-3.0-or-later
"""Every constraint of the schemas is pinned by a fixture: removing one changes a result.

Each mutant is a schema with one constraint taken out: one keyword of ``KEYWORDS``, one
entry of a ``required`` list or one entry of a ``dependentRequired`` map. A mutant
survives when every fixture, valid and invalid, still gives the same violations. No
mutant may survive, so a rule cannot be dropped or loosened without a fixture noticing.

Not covered, because removing them cannot loosen a rule: ``properties`` entries and
``oneOf`` branches (documents become invalid, which the valid fixtures catch only
where they use them), and annotations such as ``description``.
"""

import copy
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


def _mutants(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
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


def _results(schema: dict[str, Any], documents: list[Any]) -> Iterator[list[tuple[str, str]]]:
    validator = build_validator(schema)
    for document in documents:
        yield [(violation.path, violation.rule) for violation in violations(validator, document)]


@pytest.mark.parametrize("name", list(SchemaName))
def test_no_constraint_can_be_removed_without_a_fixture_noticing(name: SchemaName) -> None:
    schema = load_schema(name)
    documents = [*VALID[name.value]().values()]
    documents += [case.document for case in INVALID[name.value]()]
    expected = list(_results(schema, documents))

    mutants = list(_mutants(schema))
    survivors = [
        label
        for label, mutant in mutants
        if all(found == wanted for found, wanted in zip(_results(mutant, documents), expected))
    ]

    assert len(mutants) > 20
    assert survivors == []
