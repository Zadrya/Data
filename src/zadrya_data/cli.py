# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point: ``zadrya-data <command>``."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from zadrya_data import __version__
from zadrya_data.schema import SchemaName, validate

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser. Commands register themselves here as they are added."""
    parser = argparse.ArgumentParser(
        prog="zadrya-data",
        description="Build, validate and sign the Zadrya substance dataset.",
    )
    parser.add_argument("--version", action="version", version=f"zadrya-data {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    validate_parser = commands.add_parser(
        "validate",
        help="check a JSON document against its schema",
        description="Check a JSON document against its schema. Exit code 0: valid, "
        "1: schema violations, 2: the file cannot be read as JSON.",
    )
    validate_parser.add_argument("path", type=Path, help="the JSON document to check")
    validate_parser.add_argument(
        "--schema",
        type=SchemaName,
        choices=list(SchemaName),
        default=SchemaName.SUBSTANCES,
        help="which schema to check against (default: %(default)s)",
    )
    return parser


def run_validate(path: Path, schema: SchemaName) -> int:
    """Validate one file, report every violation on stderr and return the exit code."""
    try:
        document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"error: cannot read {path} as JSON: {error}", file=sys.stderr)
        return EXIT_UNREADABLE

    violations = validate(document, schema)
    for violation in violations:
        print(f"{path}: {violation}", file=sys.stderr)
    if violations:
        print(f"{path}: {len(violations)} violation(s) of the {schema} schema", file=sys.stderr)
        return EXIT_INVALID

    print(f"{path}: valid against the {schema} schema")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return the process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "validate":
        return run_validate(arguments.path, arguments.schema)
    parser.print_help()
    return EXIT_OK
