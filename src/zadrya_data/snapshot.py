# SPDX-License-Identifier: GPL-3.0-or-later
"""The raw snapshot: what ``fetch`` writes and every later command reads offline.

A snapshot is a directory with exactly three files:

- ``graphql.json``: the ``data`` member of the GraphQL answer, with every value as
  received and the substances ordered by name.
- ``mediawiki.json``: one record per looked up title (existence, canonical title,
  last revision), ordered by title.
- ``snapshot.json``: where and when the two were fetched, the exact query, the names
  of the base file that were looked up, counts, and the SHA-256 of the other two files.

The first two are written deterministically (sorted keys, two-space indent, UTF-8,
no ``NaN``), so two fetches of unchanged upstream data give the same bytes. Only
``snapshot.json`` carries the date.

A snapshot is written into a temporary directory next to its destination and moved
into place only when all three files are written and read back, so a failed write
never leaves a mix of two fetches. Reading goes through ``strict_json`` and checks
that the three files belong together and say nothing this module does not know.
"""

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from zadrya_data import graphql, mediawiki
from zadrya_data.graphql import ApiSubstance
from zadrya_data.http import USER_AGENT, PoliteClient
from zadrya_data.mediawiki import WikiPage, is_utc_timestamp
from zadrya_data.strict_json import StrictJsonError, loads

GRAPHQL_FILE = "graphql.json"
MEDIAWIKI_FILE = "mediawiki.json"
INFO_FILE = "snapshot.json"
FILES = (GRAPHQL_FILE, MEDIAWIKI_FILE, INFO_FILE)
FORMAT_VERSION = 1

_PAGE_KEYS = {"requested", "title", "exists", "pageId", "revisionId", "timestamp"}
_INFO_KEYS = {
    "formatVersion",
    "fetchedOn",
    "client",
    "graphql",
    "mediawiki",
    "baseNames",
    "counts",
}
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class SnapshotError(ValueError):
    """A snapshot directory cannot be read, or cannot be written safely."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A snapshot read back into typed objects."""

    substances: tuple[ApiSubstance, ...]
    pages: tuple[WikiPage, ...]
    base_names: tuple[str, ...]
    fetched_on: date
    counts: dict[str, int]


def dump_json(document: object) -> str:
    """Return the one text form of a document that the pipeline writes."""
    text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return text + "\n"


def sort_substances(data: dict[str, object]) -> dict[str, object]:
    """Return the data with its substances ordered by name, in code point order.

    The order of the API is an artefact of its backend. Code point order of the name
    (plain string comparison, no locale, no case folding) is the same everywhere:
    digits, then capitals, then lower case, then letters outside ASCII.
    """
    names = [substance.name for substance in graphql.parse_data(data)]
    entries = cast(list[object], data["substances"])  # parse_data accepts nothing else
    ordered = [entry for _, entry in sorted(zip(names, entries), key=lambda pair: pair[0])]
    return {**data, "substances": ordered}


def fetch_raw(
    client: PoliteClient, base_names: Iterable[str]
) -> tuple[dict[str, object], tuple[WikiPage, ...]]:
    """Fetch the GraphQL data, then look up every name of the base file and of the API."""
    data = graphql.fetch_data(client)
    names = {substance.name for substance in graphql.parse_data(data)} | set(base_names)
    return data, mediawiki.fetch_pages(client, names)


def write_snapshot(
    directory: Path,
    data: dict[str, object],
    pages: Iterable[WikiPage],
    base_names: Iterable[str],
    fetched_on: date,
) -> Snapshot:
    """Write a snapshot to the directory, replacing a previous one only when complete.

    The files are written into a temporary directory next to the destination, read back
    as a check, and only then moved into place. If anything fails before that, the
    destination is untouched. A destination that holds anything but snapshot files is
    refused, so a wrong path can never delete unrelated files.
    """
    pages = tuple(pages)
    data = sort_substances(data)
    graphql_text = dump_json(data)
    mediawiki_text = dump_json({"pages": [_page_document(page) for page in pages]})
    info = {
        "formatVersion": FORMAT_VERSION,
        "fetchedOn": fetched_on.isoformat(),
        "client": USER_AGENT,
        "graphql": {
            "endpoint": graphql.ENDPOINT,
            "query": graphql.QUERY,
            "sha256": _sha256(graphql_text.encode("utf-8")),
        },
        "mediawiki": {
            "endpoint": mediawiki.ENDPOINT,
            "titlesPerRequest": mediawiki.TITLES_PER_REQUEST,
            "sha256": _sha256(mediawiki_text.encode("utf-8")),
        },
        "baseNames": sorted(set(base_names)),
        "counts": _counts(graphql.parse_data(data), pages),
    }
    texts = {GRAPHQL_FILE: graphql_text, MEDIAWIKI_FILE: mediawiki_text, INFO_FILE: dump_json(info)}

    check_destination(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.with_name(f".{directory.name}.new-{os.getpid()}")
    previous = directory.with_name(f".{directory.name}.old-{os.getpid()}")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir()
        for name, text in texts.items():
            (staging / name).write_text(text, encoding="utf-8")
        snapshot = load_snapshot(staging)
        if directory.exists():
            directory.rename(previous)
        try:
            staging.rename(directory)
        except OSError:
            if previous.exists():
                previous.rename(directory)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(previous, ignore_errors=True)
    return snapshot


def load_snapshot(directory: Path) -> Snapshot:
    """Read a snapshot directory into typed objects, or raise ``SnapshotError``.

    Beyond the shape of each file, this checks that the three belong together: the
    hashes and counts in ``snapshot.json`` match the other two files, the endpoints
    and the query are the ones this code uses, and the looked up titles are exactly
    the substance names of the API and of the base file.
    """
    where = directory / INFO_FILE
    info = _info(loads_file(where), where)
    blobs = {name: _bytes(directory / name) for name in (GRAPHQL_FILE, MEDIAWIKI_FILE)}
    for name, key in ((GRAPHQL_FILE, "graphql"), (MEDIAWIKI_FILE, "mediawiki")):
        if _sha256(blobs[name]) != info[key]["sha256"]:
            raise SnapshotError(f"{directory / name}: the SHA-256 is not the one in {INFO_FILE}")

    try:
        substances = graphql.parse_data(_loads(blobs[GRAPHQL_FILE], directory / GRAPHQL_FILE))
    except graphql.ApiFormatError as error:
        raise SnapshotError(f"{directory / GRAPHQL_FILE}: {error}") from error
    names = [substance.name for substance in substances]
    if names != sorted(names):
        raise SnapshotError(f"{directory / GRAPHQL_FILE}: the substances are not ordered by name")

    pages = _pages(
        _loads(blobs[MEDIAWIKI_FILE], directory / MEDIAWIKI_FILE), directory / MEDIAWIKI_FILE
    )
    base_names: tuple[str, ...] = tuple(info["baseNames"])
    requested = {page.requested for page in pages}
    if requested != set(names) | set(base_names):
        raise SnapshotError(
            f"{directory / MEDIAWIKI_FILE}: the titles are not exactly the substance names "
            "of the API and of the base file"
        )
    counts = _counts(substances, pages)
    if not _same_integers(info["counts"], counts):
        raise SnapshotError(f"{where}: the counts do not match the other two files")
    return Snapshot(substances, pages, base_names, date.fromisoformat(info["fetchedOn"]), counts)


def loads_file(path: Path) -> object:
    """Read one file as strict JSON, or raise ``SnapshotError`` with its path."""
    return _loads(_bytes(path), path)


def _bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise SnapshotError(f"{path}: {error}") from error


def _loads(blob: bytes, path: Path) -> object:
    try:
        return loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, StrictJsonError) as error:
        raise SnapshotError(f"{path}: {error}") from error


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def check_destination(directory: Path) -> None:
    """Refuse a destination that ``write_snapshot`` must not replace.

    A symbolic link is refused, because replacing it would swap the link, not what it
    points to. An existing path must be a directory that holds snapshot files only.
    ``fetch`` calls this before its first request, so a wrong path costs no requests.
    """
    if directory.is_symlink():
        raise SnapshotError(f"{directory}: a symbolic link, refusing to replace it")
    if not directory.exists():
        return
    if not directory.is_dir():
        raise SnapshotError(f"{directory}: not a directory")
    foreign = sorted(path.name for path in directory.iterdir() if path.name not in FILES)
    if foreign:
        raise SnapshotError(
            f"{directory}: holds '{foreign[0]}', which is not a snapshot file: "
            "refusing to replace the directory"
        )


def _counts(substances: tuple[ApiSubstance, ...], pages: tuple[WikiPage, ...]) -> dict[str, int]:
    return {
        "substances": len(substances),
        "substancesWithoutRoutes": sum(not substance.roas for substance in substances),
        "routes": sum(len(substance.roas or ()) for substance in substances),
        "titles": len(pages),
        "pagesMissing": sum(not page.exists for page in pages),
        "pagesRedirected": sum(page.exists and page.title != page.requested for page in pages),
    }


def _same_integers(found: object, wanted: dict[str, int]) -> bool:
    """Tell whether found is the wanted mapping with real integers (not ``false``, not ``7.0``)."""
    return (
        isinstance(found, dict)
        and found == wanted
        and all(type(value) is int for value in found.values())
    )


def _page_document(page: WikiPage) -> dict[str, object]:
    return {
        "requested": page.requested,
        "title": page.title,
        "exists": page.exists,
        "pageId": page.page_id,
        "revisionId": page.revision_id,
        "timestamp": page.timestamp,
    }


def _info(document: object, where: Path) -> dict[str, Any]:
    """Check ``snapshot.json`` against everything that does not need the other two files."""

    def fail(reason: str) -> SnapshotError:
        return SnapshotError(f"{where}: {reason}")

    if not isinstance(document, dict) or set(document) != _INFO_KEYS:
        raise fail("expected exactly the keys " + ", ".join(sorted(_INFO_KEYS)))
    if type(document["formatVersion"]) is not int or document["formatVersion"] != FORMAT_VERSION:
        raise fail(f"expected a snapshot of format version {FORMAT_VERSION}")
    fetched_on = document["fetchedOn"]
    if not isinstance(fetched_on, str) or _DATE.fullmatch(fetched_on) is None:
        raise fail("fetchedOn is not a date of the form YYYY-MM-DD")
    try:
        date.fromisoformat(fetched_on)
    except ValueError as error:
        raise fail(f"fetchedOn is not a date: {fetched_on}") from error
    if not isinstance(document["client"], str):
        raise fail("client is not a string")

    sources: dict[str, dict[str, object]] = {
        "graphql": {"endpoint": graphql.ENDPOINT, "query": graphql.QUERY},
        "mediawiki": {
            "endpoint": mediawiki.ENDPOINT,
            "titlesPerRequest": mediawiki.TITLES_PER_REQUEST,
        },
    }
    for key, wanted in sources.items():
        source = document[key]
        if not isinstance(source, dict) or set(source) != set(wanted) | {"sha256"}:
            raise fail(f"{key} does not have exactly the known keys")
        digest = source["sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise fail(f"{key}.sha256 is not a SHA-256 in lowercase hexadecimal")
        for name, value in wanted.items():
            if type(source[name]) is not type(value) or source[name] != value:
                raise fail(
                    f"{key}.{name} is not the one this version of the code uses, "
                    "so the snapshot must be fetched again"
                )

    base_names = document["baseNames"]
    if not isinstance(base_names, list) or not all(isinstance(name, str) for name in base_names):
        raise fail("baseNames is not a list of strings")
    if base_names != sorted(set(base_names)):
        raise fail("baseNames is not sorted and free of repeats")
    return document


def _pages(document: object, where: Path) -> tuple[WikiPage, ...]:
    if not isinstance(document, dict) or set(document) != {"pages"}:
        raise SnapshotError(f"{where}: expected an object with the key 'pages'")
    records = document["pages"]
    if not isinstance(records, list):
        raise SnapshotError(f"{where}: 'pages' is not a list")
    pages = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != _PAGE_KEYS:
            raise SnapshotError(f"{where}: page {index} does not have exactly the known keys")
        requested, title, exists = record["requested"], record["title"], record["exists"]
        page_id, revision_id, timestamp = (
            record["pageId"],
            record["revisionId"],
            record["timestamp"],
        )
        if not (isinstance(requested, str) and isinstance(title, str) and type(exists) is bool):
            raise SnapshotError(f"{where}: page {index} has a value of the wrong type")
        if exists:
            consistent = (
                type(page_id) is int
                and page_id > 0
                and type(revision_id) is int
                and revision_id > 0
                and isinstance(timestamp, str)
                and is_utc_timestamp(timestamp)
            )
        else:
            consistent = page_id is None and revision_id is None and timestamp is None
        if not consistent:
            raise SnapshotError(
                f"{where}: page {index} must have positive ids and a UTC timestamp when it "
                "exists, and none of them when it does not"
            )
        pages.append(WikiPage(requested, title, exists, page_id, revision_id, timestamp))
    titles = [page.requested for page in pages]
    if titles != sorted(set(titles)):
        raise SnapshotError(f"{where}: the requested titles are not sorted and free of repeats")
    return tuple(pages)
