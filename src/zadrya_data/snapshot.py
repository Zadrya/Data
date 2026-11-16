# SPDX-License-Identifier: GPL-3.0-or-later
"""The raw snapshot: what ``fetch`` writes and every later command reads offline.

A snapshot is a directory with three files:

- ``graphql.json``: the ``data`` member of the GraphQL answer, with every value as
  received and the substances ordered by name.
- ``mediawiki.json``: one record per looked up title (existence, canonical title,
  last revision).
- ``snapshot.json``: where and when the two were fetched, the exact query and counts.

The first two are written deterministically (sorted keys, two-space indent, UTF-8,
no ``NaN``), so two fetches of unchanged upstream data give the same bytes. Only
``snapshot.json`` carries the date. Reading goes through ``strict_json``.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from zadrya_data import graphql, mediawiki
from zadrya_data.graphql import ApiSubstance
from zadrya_data.http import USER_AGENT, PoliteClient
from zadrya_data.mediawiki import WikiPage
from zadrya_data.strict_json import StrictJsonError, loads

GRAPHQL_FILE = "graphql.json"
MEDIAWIKI_FILE = "mediawiki.json"
INFO_FILE = "snapshot.json"
FORMAT_VERSION = 1

_PAGE_KEYS = ("requested", "title", "exists", "pageId", "revisionId", "timestamp")


class SnapshotError(ValueError):
    """A snapshot directory cannot be read as a snapshot."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A snapshot read back into typed objects."""

    substances: tuple[ApiSubstance, ...]
    pages: tuple[WikiPage, ...]
    fetched_on: date
    query: str
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
    directory: Path, data: dict[str, object], pages: Iterable[WikiPage], fetched_on: date
) -> Snapshot:
    """Write the three files, read them back as a check and return what was read."""
    pages = tuple(pages)
    data = sort_substances(data)
    substances = graphql.parse_data(data)
    info = {
        "formatVersion": FORMAT_VERSION,
        "fetchedOn": fetched_on.isoformat(),
        "client": USER_AGENT,
        "graphql": {"endpoint": graphql.ENDPOINT, "query": graphql.QUERY},
        "mediawiki": {
            "endpoint": mediawiki.ENDPOINT,
            "titlesPerRequest": mediawiki.TITLES_PER_REQUEST,
        },
        "counts": _counts(substances, pages),
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / GRAPHQL_FILE).write_text(dump_json(data), encoding="utf-8")
    (directory / MEDIAWIKI_FILE).write_text(
        dump_json({"pages": [_page_document(page) for page in pages]}), encoding="utf-8"
    )
    (directory / INFO_FILE).write_text(dump_json(info), encoding="utf-8")
    return load_snapshot(directory)


def load_snapshot(directory: Path) -> Snapshot:
    """Read a snapshot directory into typed objects, or raise ``SnapshotError``."""
    try:
        substances = graphql.parse_data(_read(directory / GRAPHQL_FILE))
    except graphql.ApiFormatError as error:
        raise SnapshotError(f"{directory / GRAPHQL_FILE}: {error}") from error
    pages = _pages(_read(directory / MEDIAWIKI_FILE), directory / MEDIAWIKI_FILE)
    info = _read(directory / INFO_FILE)
    where = directory / INFO_FILE
    if not isinstance(info, dict) or info.get("formatVersion") != FORMAT_VERSION:
        raise SnapshotError(f"{where}: expected a snapshot of format version {FORMAT_VERSION}")
    counts = info.get("counts")
    if counts != _counts(substances, pages):
        raise SnapshotError(f"{where}: the counts do not match the other two files")
    source = info.get("graphql")
    query = source.get("query") if isinstance(source, dict) else None
    fetched_on = info.get("fetchedOn")
    if not isinstance(query, str) or not isinstance(fetched_on, str):
        raise SnapshotError(f"{where}: missing the query or the fetch date")
    try:
        day = date.fromisoformat(fetched_on)
    except ValueError as error:
        raise SnapshotError(f"{where}: fetchedOn is not a date: {fetched_on}") from error
    return Snapshot(substances, pages, day, query, _counts(substances, pages))


def _counts(substances: tuple[ApiSubstance, ...], pages: tuple[WikiPage, ...]) -> dict[str, int]:
    return {
        "substances": len(substances),
        "substancesWithoutRoutes": sum(not substance.roas for substance in substances),
        "routes": sum(len(substance.roas or ()) for substance in substances),
        "titles": len(pages),
        "pagesMissing": sum(not page.exists for page in pages),
        "pagesRedirected": sum(page.exists and page.title != page.requested for page in pages),
    }


def _page_document(page: WikiPage) -> dict[str, object]:
    return {
        "requested": page.requested,
        "title": page.title,
        "exists": page.exists,
        "pageId": page.page_id,
        "revisionId": page.revision_id,
        "timestamp": page.timestamp,
    }


def _read(path: Path) -> object:
    try:
        return loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, StrictJsonError) as error:
        raise SnapshotError(f"{path}: {error}") from error


def _pages(document: object, where: Path) -> tuple[WikiPage, ...]:
    if not isinstance(document, dict) or set(document) != {"pages"}:
        raise SnapshotError(f"{where}: expected an object with the key 'pages'")
    records = document["pages"]
    if not isinstance(records, list):
        raise SnapshotError(f"{where}: 'pages' is not a list")
    pages = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != set(_PAGE_KEYS):
            raise SnapshotError(f"{where}: page {index} does not have exactly the known keys")
        requested, title, exists = record["requested"], record["title"], record["exists"]
        page_id, revision_id, timestamp = (
            record["pageId"],
            record["revisionId"],
            record["timestamp"],
        )
        well_typed = (
            isinstance(requested, str)
            and isinstance(title, str)
            and isinstance(exists, bool)
            and _is_optional(page_id, int)
            and _is_optional(revision_id, int)
            and _is_optional(timestamp, str)
        )
        if not well_typed:
            raise SnapshotError(f"{where}: page {index} has a value of the wrong type")
        pages.append(WikiPage(requested, title, exists, page_id, revision_id, timestamp))
    return tuple(pages)


def _is_optional(value: object, kind: type) -> bool:
    return value is None or (isinstance(value, kind) and not isinstance(value, bool))
