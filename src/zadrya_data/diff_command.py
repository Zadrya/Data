# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``diff`` command: read two datasets, write the diff report.

Exit codes: 0 written, 1 an input is not a valid dataset (schema, repeated name or id,
invariants), 2 a file cannot be read or written (including an output that would
replace an input).
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from zadrya_data.diff import (
    DiffInputError,
    DiffRefusedError,
    compare,
    load_base_dataset,
    load_dataset,
)
from zadrya_data.diff_report import DEFAULT_MAX_ROWS, render
from zadrya_data.normalize import NormalizationError

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_UNREADABLE = 2


class _CannotWrite(OSError):
    """An output file cannot be written."""


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise ValueError(value)
    return number


def register(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``diff`` command to the command line."""
    parser = commands.add_parser(
        "diff",
        help="write the readable report of what changed between two datasets",
        description="Compare two datasets and write a Markdown report: a warning that counts "
        "every change a reviewer must not miss, a summary, substances added, removed and "
        "renamed, changed doses, durations, tolerance, bioavailability and units, interaction "
        "changes (lowered first), group membership changes, and which categories and texts "
        "changed. With --old-format base, OLD is the base file, normalized without API data. "
        "Both inputs must pass the schema and the invariants. Exit code 0: written, 1: an "
        "input is not a valid dataset, 2: a file cannot be read or written.",
    )
    parser.add_argument("old", type=Path, help="the dataset before the change")
    parser.add_argument("new", type=Path, help="the dataset after the change")
    parser.add_argument(
        "--old-format",
        choices=("dataset", "base"),
        default="dataset",
        help="read OLD as a dataset or as the base file (default: %(default)s)",
    )
    parser.add_argument("--output", type=Path, help="write the report here instead of stdout")
    parser.add_argument(
        "--head-output",
        type=Path,
        help="also write the head of the report (warning and summary) to this file",
    )
    parser.add_argument(
        "--changed-paths",
        type=Path,
        help="a file of paths outside dataset/ that the change touches, one per line, listed "
        "at the top of the report",
    )
    parser.add_argument("--old-label", help="how the report names OLD (default: its path)")
    parser.add_argument("--new-label", help="how the report names NEW (default: its path)")
    parser.add_argument(
        "--max-rows",
        type=_positive,
        default=DEFAULT_MAX_ROWS,
        help="other rows per section before the rest is counted, not shown; rows a reviewer "
        "must see are always shown (default: %(default)s)",
    )


def _write(path: Path, text: str, inputs: tuple[Path, ...]) -> None:
    """Write the file whole or not at all, never over an input."""
    if path.resolve() in {source.resolve() for source in inputs}:
        raise _CannotWrite(f"cannot write {path}: it is an input file")
    try:
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except OSError as error:
        raise _CannotWrite(f"cannot write {path}: {error.strerror}") from None
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except OSError as error:
        Path(temporary).unlink(missing_ok=True)
        raise _CannotWrite(f"cannot write {path}: {error.strerror}") from None


def _changed_paths(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as error:
        raise DiffInputError(f"cannot read {path}: {error}") from None
    return [line for line in lines if line.strip()]


def run(arguments: argparse.Namespace) -> int:
    """Run the ``diff`` command and return its exit code."""
    old_path: Path = arguments.old
    new_path: Path = arguments.new
    base = arguments.old_format == "base"
    default_old = f"{old_path} (base file, normalized)" if base else str(old_path)
    old_label: str = arguments.old_label or default_old
    new_label: str = arguments.new_label or str(new_path)
    try:
        old = load_base_dataset(old_path) if base else load_dataset(old_path)
        new = load_dataset(new_path)
        changed = _changed_paths(arguments.changed_paths)
    except DiffInputError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except (DiffRefusedError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_REFUSED
    report = render(
        compare(old, new, versions=not base),
        old_label=old_label,
        new_label=new_label,
        max_rows=arguments.max_rows,
        changed_paths=changed,
    )
    inputs = (old_path, new_path)
    try:
        if arguments.head_output is not None:
            _write(arguments.head_output, report.head, inputs)
        if arguments.output is None:
            sys.stdout.write(report.text)
            return EXIT_OK
        _write(arguments.output, report.text, inputs)
    except _CannotWrite as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    print(f"{arguments.output}: diff report of {old_label} and {new_label}")
    return EXIT_OK
