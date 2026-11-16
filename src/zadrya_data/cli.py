# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point: ``zadrya-data <command>``."""

import argparse
import sys
from datetime import UTC, datetime
from collections.abc import Sequence
from pathlib import Path

from zadrya_data import __version__
from zadrya_data.base import BaseFormatError, load_base
from zadrya_data.graphql import ApiFormatError, ApiQueryError
from zadrya_data.http import FetchError, PoliteClient
from zadrya_data.mediawiki import WikiFormatError
from zadrya_data.schema import SchemaName, validate
from zadrya_data.snapshot import SnapshotError, fetch_raw, write_snapshot
from zadrya_data.strict_json import loads

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2
EXIT_FETCH_FAILED = 1

DEFAULT_BASE = Path("sources/base/Substances.json")


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
        "1: schema violations, 2: the file cannot be read as strict JSON (no NaN or "
        "Infinity, no number out of range, no integer above 2**53 - 1, no repeated key).",
    )
    validate_parser.add_argument("path", type=Path, help="the JSON document to check")
    validate_parser.add_argument(
        "--schema",
        type=SchemaName,
        choices=list(SchemaName),
        default=SchemaName.SUBSTANCES,
        help="which schema to check against (default: %(default)s)",
    )

    fetch_parser = commands.add_parser(
        "fetch",
        help="download a raw snapshot of the PsychonautWiki data (the only network use)",
        description="Download a raw snapshot from the PsychonautWiki GraphQL API and the "
        "wiki into a directory: graphql.json, mediawiki.json and snapshot.json. This is "
        "the only command that uses the network: nine requests today, at most one per "
        "second. The directory is replaced only when the new snapshot is complete. "
        "Exit code 0: written, 1: the fetch failed and the directory is as it was.",
    )
    fetch_parser.add_argument(
        "--output", type=Path, required=True, help="directory to write the snapshot to"
    )
    fetch_parser.add_argument(
        "--base",
        type=Path,
        default=DEFAULT_BASE,
        help="the base file whose substance names are looked up too (default: %(default)s)",
    )
    return parser


def make_client() -> PoliteClient:
    """Return the client that ``fetch`` uses. Tests replace it with one that replays answers."""
    return PoliteClient()


def run_fetch(output: Path, base: Path) -> int:
    """Fetch a snapshot into the output directory and return the exit code.

    Nothing is written unless every request succeeded and every answer was understood.
    """
    try:
        base_names = [substance.name for substance in load_base(base).substances]
        with make_client() as client:
            data, pages = fetch_raw(client, base_names)
            requests = client.request_count
        snapshot = write_snapshot(output, data, pages, base_names, datetime.now(UTC).date())
    except (
        OSError,
        BaseFormatError,
        FetchError,
        ApiQueryError,
        ApiFormatError,
        WikiFormatError,
        SnapshotError,
    ) as error:
        print(f"error: fetch failed: {error}", file=sys.stderr)
        return EXIT_FETCH_FAILED

    counts = snapshot.counts
    print(
        f"{output}: {counts['substances']} API entries "
        f"({counts['substancesWithoutRoutes']} without routes, {counts['routes']} routes), "
        f"{counts['titles']} wiki titles ({counts['pagesMissing']} missing, "
        f"{counts['pagesRedirected']} redirected), {requests} requests"
    )
    return EXIT_OK


def run_validate(path: Path, schema: SchemaName) -> int:
    """Validate one file, report every violation on stderr and return the exit code."""
    try:
        document = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"error: cannot read {path} as strict JSON: {error}", file=sys.stderr)
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
    if arguments.command == "fetch":
        return run_fetch(arguments.output, arguments.base)
    parser.print_help()
    return EXIT_OK
