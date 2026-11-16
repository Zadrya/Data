# SPDX-License-Identifier: GPL-3.0-or-later
"""Load the dataset JSON Schemas and validate documents against them.

The schemas live in ``schema/`` at the repository root, where the app reads them.
They are linked into this package (``zadrya_data/schemas``), so the build copies
them into the wheel and an installed package finds them without the repository.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

SCHEMA_VERSION = "1.0.0"


class SchemaName(StrEnum):
    """The documents this package has a schema for."""

    SUBSTANCES = "substances"
    MANIFEST = "manifest"


class SchemaLoadError(RuntimeError):
    """A schema file of this package cannot be used."""

    def __init__(self, name: SchemaName, reason: str) -> None:
        super().__init__(
            f"cannot load the {name.value} schema: {reason}. In a checkout the files in "
            "src/zadrya_data/schemas are symbolic links to schema/: a clone without "
            "symbolic link support (git config core.symlinks) leaves them as plain text."
        )


@dataclass(frozen=True)
class SchemaViolation:
    """One place where a document breaks its schema."""

    path: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message} ({self.rule})"


def load_schema(name: SchemaName) -> dict[str, Any]:
    """Return the schema of the given document as parsed JSON."""
    resource = files("zadrya_data").joinpath("schemas", f"{name.value}.schema.json")
    try:
        schema = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SchemaLoadError(name, str(error)) from error
    if not isinstance(schema, dict):
        raise SchemaLoadError(name, f"expected a JSON object, found {type(schema).__name__}")
    return schema


def build_validator(schema: dict[str, Any]) -> Draft202012Validator:
    """Return a Draft 2020-12 validator of the schema with format assertions on."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


@cache
def _validator(name: SchemaName) -> Draft202012Validator:
    return build_validator(load_schema(name))


def _expand(error: ValidationError) -> Iterator[ValidationError]:
    """Replace a ``oneOf`` failure by the failures of the branch the document chose.

    The branches of a ``oneOf`` in these schemas differ by a constant (``kind``). When
    exactly one branch has no failed constant, the document meant that branch, and its
    failures say what is wrong. Otherwise the ``oneOf`` failure itself is reported.
    """
    if error.validator == "oneOf" and error.context:
        branches: dict[object, list[ValidationError]] = {}
        for inner in error.context:
            branches.setdefault(inner.relative_schema_path[0], []).append(inner)
        chosen = [
            inners
            for inners in branches.values()
            if all(inner.validator != "const" for inner in inners)
        ]
        if len(chosen) == 1:
            for inner in chosen[0]:
                yield from _expand(inner)
            return
    yield error


def violations(validator: Draft202012Validator, document: object) -> list[SchemaViolation]:
    """Return every violation the validator finds in the document, ordered by path."""
    found = [
        SchemaViolation(path=error.json_path, rule=str(error.validator), message=error.message)
        for top in validator.iter_errors(document)
        for error in _expand(top)
    ]
    return sorted(found, key=lambda violation: (violation.path, violation.rule))


def validate(document: object, name: SchemaName) -> list[SchemaViolation]:
    """Return every violation of the schema, ordered by path. An empty list means valid."""
    return violations(_validator(name), document)
