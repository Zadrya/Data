# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point: ``zadrya-data <command>``."""

import argparse
import datetime as dt
import os
import re
import sys
from datetime import UTC, datetime
from collections.abc import Sequence
from pathlib import Path

from zadrya_data import __version__
from zadrya_data.base import BaseFormatError, load_base
from zadrya_data.graphql import ApiFormatError, ApiQueryError
from zadrya_data.errors import ReleaseRejectedError
from zadrya_data.http import FetchError, PoliteClient
from zadrya_data.manifest import build_manifest, parse_substances, serialize_manifest, sha256_hex
from zadrya_data.mediawiki import WikiFormatError
from zadrya_data.release_check import VerifiedRelease, verify_release
from zadrya_data.release_download import (
    LATEST,
    RELEASES_URL,
    check_tag,
    download_release,
    resolve_tag,
)
from zadrya_data.schema import SchemaName, validate
from zadrya_data.signing import (
    PinnedKey,
    decode_signature,
    encode_signature,
    load_private_key,
    load_public_keys,
    private_key_path_from_env,
    sign,
    verify,
)
from zadrya_data.snapshot import SnapshotError, check_destination, fetch_raw, write_snapshot
from zadrya_data.strict_json import loads

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2
EXIT_FETCH_FAILED = 1

DEFAULT_BASE = Path("sources/base/Substances.json")
DEFAULT_KEYS = Path("keys")
RELEASE_FILES = ("substances.json", "substances.json.sig", "manifest.json")

_SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


class _Refused(Exception):
    """A command stops with this exit code and message."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _version_argument(value: str) -> str:
    if _SEMVER.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a version of the form MAJOR.MINOR.PATCH"
        )
    return value


def _date_argument(value: str) -> dt.date:
    try:
        if _DATE.fullmatch(value) is None:
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a date of the form YYYY-MM-DD"
        ) from None


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise _Refused(EXIT_UNREADABLE, f"cannot read {path}: {error.strerror}") from None


def _write(path: Path, content: bytes, *, source: Path) -> None:
    """Write the file whole or not at all, and never over the file it was made from."""
    if path.resolve() == source.resolve():
        raise _Refused(EXIT_INVALID, f"{path} is the input file: choose another output")
    temporary = path.with_name(f".{path.name}.partial")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise _Refused(EXIT_UNREADABLE, f"cannot write {path}: {error.strerror}") from None


def _release_dataset(path: Path, dataset_version: str | None) -> bytes:
    """Return the exact bytes of a dataset that is fit to be released.

    It must be strict JSON, valid against the substances schema and, when a version
    is expected, state that ``datasetVersion``. Refusals raise ``_Refused`` or a
    ``ReleaseRejectedError``.
    """
    data = _read(path)
    document = parse_substances(data)
    violations = validate(document, SchemaName.SUBSTANCES)
    if violations:
        shown = "; ".join(str(violation) for violation in violations[:5])
        raise _Refused(
            EXIT_INVALID,
            f"{path} is not valid against the substances schema ({len(violations)} "
            f"violation(s)): {shown}",
        )
    stated = document["datasetVersion"]
    if dataset_version is not None and stated != dataset_version:
        raise _Refused(
            EXIT_INVALID,
            f"{path} states datasetVersion {stated}, and {dataset_version} was expected",
        )
    return data


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

    manifest_parser = commands.add_parser(
        "manifest",
        help="write the manifest.json of a release",
        description="Write the manifest.json of a release of the exact bytes of a dataset. The "
        "versions and the attribution are copied from the dataset, the SHA-256 is computed over "
        "its bytes. The same inputs always give the same bytes: nothing reads the clock. "
        "Exit code 0: written, 1: the dataset or an argument is refused, 2: a file cannot be "
        "read or written.",
    )
    manifest_parser.add_argument("substances", type=Path, help="the substances.json to release")
    manifest_parser.add_argument(
        "--min-app-version",
        type=_version_argument,
        required=True,
        help="lowest app version that can use the dataset (MAJOR.MINOR.PATCH)",
    )
    manifest_parser.add_argument(
        "--date", type=_date_argument, required=True, help="release date (YYYY-MM-DD)"
    )
    manifest_parser.add_argument(
        "--dataset-version",
        type=_version_argument,
        help="refuse a dataset that does not state this datasetVersion",
    )
    manifest_parser.add_argument(
        "--output", type=Path, required=True, help="where to write manifest.json"
    )

    sign_parser = commands.add_parser(
        "sign",
        help="write the substances.json.sig of a release",
        description="Sign the exact bytes of a dataset with the private key in the file that "
        "ZADRYA_SIGNING_KEY_FILE names (its password, if any, in ZADRYA_SIGNING_KEY_PASSWORD), "
        "and write substances.json.sig. The signature is written only if a pinned public key "
        "verifies it, so signing with a key that is not pinned fails. Exit code 0: written, "
        "1: the dataset, the key or the signature is refused, 2: a file cannot be read or "
        "written.",
    )
    sign_parser.add_argument("substances", type=Path, help="the substances.json to sign")
    sign_parser.add_argument(
        "--output", type=Path, required=True, help="where to write substances.json.sig"
    )
    sign_parser.add_argument(
        "--dataset-version",
        type=_version_argument,
        help="refuse a dataset that does not state this datasetVersion",
    )
    sign_parser.add_argument(
        "--keys",
        type=Path,
        default=DEFAULT_KEYS,
        help="directory of the pinned public keys (default: %(default)s)",
    )

    verify_parser = commands.add_parser(
        "verify",
        help="check a release as the app does: signature, hash, schemas, consistency",
        description="Check the three files of a release (substances.json, substances.json.sig "
        "and manifest.json) against the pinned public keys, as the app does: from a directory, "
        "or downloaded from a GitHub Release of Zadrya/Data with --release (the only network "
        "use besides fetch; the tag must name the signed datasetVersion). Exit code 0: "
        "accepted, 1: rejected, 2: a file cannot be read or downloaded.",
    )
    verify_source = verify_parser.add_mutually_exclusive_group(required=True)
    verify_source.add_argument(
        "directory",
        type=Path,
        nargs="?",
        help="directory that holds the three files of the release",
    )
    verify_source.add_argument(
        "--release",
        metavar="TAG",
        help=f"download the release with this tag (dataset-vX.Y.Z) or {LATEST!r} instead",
    )
    verify_parser.add_argument(
        "--dataset-version",
        type=_version_argument,
        help="also reject a release whose signed datasetVersion is not this one",
    )
    verify_parser.add_argument(
        "--keys",
        type=Path,
        default=DEFAULT_KEYS,
        help="directory of the pinned public keys (default: %(default)s)",
    )
    return parser


def _verify_files(
    files: dict[str, bytes], pinned: Sequence[PinnedKey], dataset_version: str | None
) -> VerifiedRelease:
    verified = verify_release(
        substances=files["substances.json"],
        signature_file=files["substances.json.sig"],
        manifest=files["manifest.json"],
        public_keys=pinned,
    )
    if dataset_version is not None and verified.dataset_version != dataset_version:
        raise _Refused(
            EXIT_INVALID,
            f"the signed datasetVersion is {verified.dataset_version}, and "
            f"{dataset_version} was expected",
        )
    return verified


def _report(verified: VerifiedRelease, where: str) -> None:
    print(
        f"{where}: accepted\n"
        f"  signed by the pinned key {verified.key.name} ({verified.key.base64})\n"
        f"  datasetVersion {verified.dataset_version}, schemaVersion {verified.schema_version} "
        "(signed)\n"
        f"  sha256 {verified.sha256}\n"
        f"  minAppVersion {verified.unsigned_min_app_version} (unsigned, from the manifest)"
    )


def run_verify(directory: Path, dataset_version: str | None, keys: Path) -> int:
    """Verify the release files in a directory and return the exit code.

    Only refusals (``ReleaseRejectedError``) and unreadable files are caught: any
    other exception is a bug and is not hidden.
    """
    try:
        files = {name: _read(directory / name) for name in RELEASE_FILES}
        verified = _verify_files(files, load_public_keys(keys), dataset_version)
    except _Refused as refusal:
        outcome = "rejected" if refusal.code == EXIT_INVALID else "not verified"
        print(f"error: {directory}: {outcome}: {refusal}", file=sys.stderr)
        return refusal.code
    except ReleaseRejectedError as error:
        print(f"error: {directory}: rejected: {error}", file=sys.stderr)
        return EXIT_INVALID
    _report(verified, str(directory))
    return EXIT_OK


def run_verify_release(requested: str, dataset_version: str | None, keys: Path) -> int:
    """Download a published release, verify it as the app does, and return the exit code.

    The pinned keys are read first, so nothing is downloaded when none is pinned.
    Besides the checks of ``run_verify``, the tag must name the signed
    ``datasetVersion``. As there, only refusals and failed downloads are caught.
    """
    where = f"release {requested}"
    try:
        pinned = load_public_keys(keys)
        with make_client() as client:
            tag = resolve_tag(client, requested)
            where = f"{RELEASES_URL}/tag/{tag}"
            files = download_release(client, tag)
        verified = _verify_files(files, pinned, dataset_version)
        check_tag(tag, verified.dataset_version)
    except FetchError as error:
        print(f"error: {where}: not verified: download failed: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except _Refused as refusal:
        print(f"error: {where}: rejected: {refusal}", file=sys.stderr)
        return refusal.code
    except ReleaseRejectedError as error:
        print(f"error: {where}: rejected: {error}", file=sys.stderr)
        return EXIT_INVALID
    _report(verified, where)
    return EXIT_OK


def run_sign(substances: Path, output: Path, dataset_version: str | None, keys: Path) -> int:
    """Sign a dataset, check the signature against the pinned keys, write it, return the exit code.

    The private key never reaches a message: the errors of ``zadrya_data.signing``
    name the reason only, and this function prints nothing about the key but the
    name of the pinned key that matched.
    """
    try:
        data = _release_dataset(substances, dataset_version)
        pinned = load_public_keys(keys)
        signature_file = encode_signature(sign(data, load_private_key(private_key_path_from_env())))
        matched = verify(data, decode_signature(signature_file), pinned)
        _write(output, signature_file, source=substances)
    except _Refused as refusal:
        print(f"error: signature not written: {refusal}", file=sys.stderr)
        return refusal.code
    except ReleaseRejectedError as error:
        print(f"error: signature not written: {error}", file=sys.stderr)
        return EXIT_INVALID
    print(
        f"{output}: signature of {substances} (sha256 {sha256_hex(data)}), "
        f"verified with the pinned key {matched.name}"
    )
    return EXIT_OK


def run_manifest(
    substances: Path,
    min_app_version: str,
    date: dt.date,
    dataset_version: str | None,
    output: Path,
) -> int:
    """Build and write the manifest of a release, and return the exit code."""
    try:
        data = _release_dataset(substances, dataset_version)
        manifest = build_manifest(data, min_app_version=min_app_version, date=date)
        _write(output, serialize_manifest(manifest), source=substances)
    except _Refused as refusal:
        print(f"error: manifest not written: {refusal}", file=sys.stderr)
        return refusal.code
    except ReleaseRejectedError as error:
        print(f"error: manifest not written: {error}", file=sys.stderr)
        return EXIT_INVALID
    print(
        f"{output}: manifest of dataset {manifest['datasetVersion']} (schema "
        f"{manifest['schemaVersion']}), minAppVersion {min_app_version}, date {date}, "
        f"sha256 {manifest['sha256']}"
    )
    return EXIT_OK


def make_client() -> PoliteClient:
    """Return the client of ``fetch`` and ``verify --release``. Tests replace it with a replay."""
    return PoliteClient()


def run_fetch(output: Path, base: Path) -> int:
    """Fetch a snapshot into the output directory and return the exit code.

    Nothing is written unless every request succeeded and every answer was understood.
    """
    try:
        check_destination(output)
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
    if arguments.command == "verify" and arguments.release is not None:
        return run_verify_release(arguments.release, arguments.dataset_version, arguments.keys)
    if arguments.command == "verify":
        return run_verify(arguments.directory, arguments.dataset_version, arguments.keys)
    if arguments.command == "sign":
        return run_sign(
            arguments.substances, arguments.output, arguments.dataset_version, arguments.keys
        )
    if arguments.command == "manifest":
        return run_manifest(
            arguments.substances,
            arguments.min_app_version,
            arguments.date,
            arguments.dataset_version,
            arguments.output,
        )
    parser.print_help()
    return EXIT_OK
