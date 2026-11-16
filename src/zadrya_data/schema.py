# SPDX-License-Identifier: GPL-3.0-or-later
"""Load the dataset JSON Schemas and validate documents against them.

The schemas live in ``schema/`` at the repository root, where the app reads them.
They are linked into this package (``zadrya_data/schemas``), so the build copies
them into the wheel and an installed package finds them without the repository.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "1.0.0"


class SchemaName(StrEnum):
    """The documents this package has a schema for."""

    SUBSTANCES = "substances"
    MANIFEST = "manifest"


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
    schema: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    return schema


@cache
def _validator(name: SchemaName) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate(document: object, name: SchemaName) -> list[SchemaViolation]:
    """Return every violation of the schema, ordered by path. An empty list means valid."""
    violations = [
        SchemaViolation(path=error.json_path, rule=str(error.validator), message=error.message)
        for error in _validator(name).iter_errors(document)
    ]
    return sorted(violations, key=lambda violation: (violation.path, violation.rule))
