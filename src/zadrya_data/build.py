# SPDX-License-Identifier: GPL-3.0-or-later
"""Build ``substances.json`` from the base file and a snapshot, offline and deterministically.

``build_dataset`` normalizes, adds the versions and the attribution, validates the
schema, checks the invariants, and returns the bytes: sorted keys, two-space indent,
UTF-8 without escapes, ``allow_nan=False``, line feeds, one final newline, and no date
or anything else that depends on the clock, the machine or the hash seed. The same
inputs give the same bytes.

``write_verified`` writes the bytes next to the target, reads them back through
``strict_json``, checks them again (schema and invariants of what is on disk, not of
the object in memory: the hash and the signature cover the bytes) and only then
renames them over the target. See ``docs/adr/0007-invariants-and-build.md``.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zadrya_data import invariants
from zadrya_data.base import BaseFile
from zadrya_data.manifest import parse_substances
from zadrya_data.normalize import Report, normalize
from zadrya_data.schema import SCHEMA_VERSION, SchemaName, SchemaViolation, validate
from zadrya_data.snapshot import Snapshot, dump_json

# The sources of the dataset and their licenses (DATA_LICENSES.md). The license of
# the dataset itself is the owner's decision; this list states where it comes from.
ATTRIBUTION: tuple[dict[str, str], ...] = (
    {
        "name": "PsychonautWiki contributors (text)",
        "url": "https://psychonautwiki.org/wiki/Copyrights",
        "license": "CC-BY-SA-4.0",
    },
    {
        "name": "PsychonautWiki contributors (semantic data)",
        "url": "https://psychonautwiki.org/wiki/Copyrights",
        "license": "CC-BY-4.0",
    },
    {
        "name": "PsychonautWiki Journal v11.11, Isaak Hanimann",
        "url": "https://github.com/isaakhanimann/psychonautwiki-journal-android",
        "license": "GPL-3.0-or-later",
    },
)


class BuildError(ValueError):
    """The built dataset is refused. The message says why."""


class DatasetInvalidError(BuildError):
    """The built dataset breaks the substances schema."""

    def __init__(self, violations: list[SchemaViolation]) -> None:
        self.violations = violations
        lines = "".join(f"\n  {violation}" for violation in violations)
        super().__init__(
            f"the dataset is not valid against the substances schema "
            f"({len(violations)} violation(s)):{lines}"
        )


@dataclass(frozen=True, slots=True)
class Built:
    """The bytes of a dataset that passed every check, its document and the report."""

    data: bytes
    document: dict[str, Any]
    report: Report


def assemble(fragment: dict[str, Any], dataset_version: str) -> dict[str, Any]:
    """Return the whole dataset: versions and attribution, then what normalization made."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "datasetVersion": dataset_version,
        "attribution": [dict(source) for source in ATTRIBUTION],
    } | fragment


def check_document(document: dict[str, Any]) -> None:
    """Raise unless the document is valid against the schema and keeps every invariant.

    The schema comes first: the invariants assume its shape.
    """
    violations = validate(document, SchemaName.SUBSTANCES)
    if violations:
        raise DatasetInvalidError(violations)
    invariants.require(document)


def check_bytes(data: bytes) -> dict[str, Any]:
    """Read the bytes as strict JSON, check them as ``check_document`` does, return the document.

    Unreadable bytes raise ``SubstancesDocumentError``, a ``ReleaseRejectedError``.
    """
    document = parse_substances(data)
    check_document(document)
    return document


def serialize(document: dict[str, Any]) -> bytes:
    """Return the one byte form of a dataset (``snapshot.dump_json``, in UTF-8)."""
    return dump_json(document).encode("utf-8")


def build_dataset(base: BaseFile, snapshot: Snapshot, dataset_version: str) -> Built:
    """Build and check the dataset. Refusals raise ``NormalizationError``, ``BuildError``,
    ``InvariantError`` or ``ReleaseRejectedError``."""
    normalized = normalize(base, snapshot)
    document = assemble(normalized.document, dataset_version)
    check_document(document)
    data = serialize(document)
    check_bytes(data)
    return Built(data, document, normalized.report)


def _escape(value: str | None) -> str:
    if value is None:
        return ""
    return (
        value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    )


def report_tsv(report: Report) -> bytes:
    """Return the report as tab-separated text: a header, then one finding per line.

    Backslash, tab, line feed and carriage return inside a value are written as
    ``\\\\``, ``\\t``, ``\\n`` and ``\\r``, so a line is always one finding.
    """
    lines = ["kind\tsubstance\troute\tdetail"]
    for finding in report.findings:
        fields = (finding.kind.value, finding.substance, finding.route, finding.detail)
        lines.append("\t".join(_escape(field) for field in fields))
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_verified(path: Path, data: bytes, verify: Callable[[bytes], object]) -> None:
    """Write the bytes to ``path`` whole or not at all, after checking what was written.

    The bytes go to a hidden sibling first, are read back, must equal ``data`` and pass
    ``verify``; only then the sibling is renamed over ``path``. On any failure the
    sibling is removed and ``path`` is left as it was. ``OSError`` and whatever
    ``verify`` raises reach the caller.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    try:
        temporary.write_bytes(data)
        written = temporary.read_bytes()
        if written != data:
            raise BuildError(f"{temporary} does not hold the bytes that were written")
        verify(written)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
