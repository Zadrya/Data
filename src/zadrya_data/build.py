# SPDX-License-Identifier: GPL-3.0-or-later
"""Build ``substances.json`` from the base file and a snapshot, offline and deterministically.

``build_dataset`` normalizes, adds the versions and the attribution, validates the
schema, checks the invariants, and returns the bytes: sorted keys, two-space indent,
UTF-8 without escapes, ``allow_nan=False``, line feeds, one final newline, and no date
or anything else that depends on the clock, the machine or the hash seed. The same
inputs give the same bytes.

``write_outputs`` writes each file to a new hidden sibling, flushes it to disk, reads
it back and checks it (for the dataset: ``strict_json``, schema and invariants of what
is on disk, not of the object in memory, since the hash and the signature cover the
bytes), and renames the siblings over their targets only when every one passed. See ``docs/adr/0007-invariants-and-build.md``.
"""

import os
import tempfile
from collections.abc import Callable, Sequence
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


@dataclass(frozen=True, slots=True)
class Output:
    """One file to write: where, the exact bytes, and the check the bytes on disk must pass."""

    path: Path
    data: bytes
    verify: Callable[[bytes], object]


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view) :]


def _read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(descriptor, 1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _make_parents(directory: Path) -> list[Path]:
    """Create the directory and its missing parents; return those created, deepest first."""
    missing = [path for path in (directory, *directory.parents) if not path.exists()]
    directory.mkdir(parents=True, exist_ok=True)
    return missing


def _stage(output: Output) -> Path:
    """Write the bytes to a new hidden file next to the target, durably, and check them.

    The file is created by ``tempfile.mkstemp`` in the target's directory: a new name,
    opened with ``O_EXCL``, so an existing file or symbolic link is never followed or
    reused. The bytes are flushed to disk, read back through the same descriptor, must
    equal what was written and must pass ``output.verify``. On any failure the file is
    removed.
    """
    descriptor, name = tempfile.mkstemp(
        dir=output.path.parent, prefix=f".{output.path.name}.", suffix=".partial"
    )
    temporary = Path(name)
    try:
        try:
            os.fchmod(descriptor, 0o666 & ~_umask())
            _write_all(descriptor, output.data)
            os.fsync(descriptor)
            written = _read_all(descriptor)
        finally:
            os.close(descriptor)
        if written != output.data:
            raise BuildError(f"{temporary} does not hold the bytes that were written")
        output.verify(written)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def write_outputs(outputs: Sequence[Output]) -> None:
    """Write every output whole, or leave every target as it was.

    Each output is staged first (``_stage``: written, flushed, read back and checked).
    Only when all of them passed are they renamed over their targets, in the order
    given, each rename followed by a flush of its directory. On a failure before the
    renames, the staged files and any directory created for them are removed, and no
    target changes. A rename itself can fail only if the directory changes under the
    command; callers pass the dataset last so that it is never the one left behind.
    """
    staged: list[tuple[Path, Path]] = []
    created: list[Path] = []
    try:
        for output in outputs:
            created.extend(_make_parents(output.path.parent))
            staged.append((_stage(output), output.path))
    except BaseException:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        for directory in created:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    for temporary, path in staged:
        os.replace(temporary, path)
        _fsync_directory(path.parent)


def write_verified(path: Path, data: bytes, verify: Callable[[bytes], object]) -> None:
    """Write one file as ``write_outputs`` does."""
    write_outputs([Output(path, data, verify)])
