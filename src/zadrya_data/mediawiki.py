# SPDX-License-Identifier: GPL-3.0-or-later
"""Client of the PsychonautWiki MediaWiki API: which pages exist, under which title.

For a list of substance names it records, per name, whether the wiki has a page, the
title of that page after normalization and redirects, and the id and timestamp of its
last revision. That is the provenance of the snapshot, and it lets a later step see
that a substance was renamed or lost its page. Only ``action=query`` is used: no page
text is read.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from zadrya_data.http import PoliteClient

ENDPOINT = "https://psychonautwiki.org/w/api.php"
TITLES_PER_REQUEST = 50
MAX_REDIRECTS = 5


_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def is_utc_timestamp(text: str) -> bool:
    """Tell whether the text is an ISO 8601 UTC time of the form ``2025-12-11T08:07:17Z``."""
    if _TIMESTAMP.fullmatch(text) is None:
        return False
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


class WikiFormatError(ValueError):
    """The answer of the wiki does not have the shape this reader knows."""


@dataclass(frozen=True, slots=True)
class WikiPage:
    """What the wiki says about one requested title."""

    requested: str
    title: str
    exists: bool
    page_id: int | None
    revision_id: int | None
    timestamp: str | None


def fetch_pages(client: PoliteClient, titles: Iterable[str]) -> tuple[WikiPage, ...]:
    """Look up every title, 50 per request, and return one page per title, sorted by title."""
    wanted = sorted(set(titles))
    for title in wanted:
        if "|" in title or title.strip() != title or not title:
            raise WikiFormatError(f"the title {title!r} cannot be sent in a list of titles")
    pages: list[WikiPage] = []
    for start in range(0, len(wanted), TITLES_PER_REQUEST):
        batch = wanted[start : start + TITLES_PER_REQUEST]
        answer = client.post_form(
            ENDPOINT,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "revisions",
                "rvprop": "ids|timestamp",
                "titles": "|".join(batch),
            },
        )
        pages.extend(parse_answer(answer, batch))
    return tuple(pages)


def parse_answer(answer: object, titles: Iterable[str]) -> list[WikiPage]:
    """Resolve each requested title in one answer of ``action=query``."""
    top = _object(answer, "$", required=("batchcomplete", "query"))
    if top["batchcomplete"] is not True:
        raise WikiFormatError("$.batchcomplete: expected true, the answer is not complete")
    query = _object(
        top["query"], "$.query", required=("pages",), optional=("normalized", "redirects")
    )
    normalized = _renames(query.get("normalized", []), "$.query.normalized", ("fromencoded",))
    redirects = _renames(query.get("redirects", []), "$.query.redirects", ("tofragment",))
    by_title: dict[str, WikiPage] = {}
    for index, item in enumerate(_list(query["pages"], "$.query.pages")):
        page = _page(item, f"$.query.pages[{index}]")
        if page.title in by_title:
            raise WikiFormatError(f"$.query.pages[{index}]: second page titled '{page.title}'")
        by_title[page.title] = page

    pages = []
    for requested in titles:
        title = normalized.get(requested, requested)
        hops = 0
        while title in redirects:
            if hops == MAX_REDIRECTS:
                raise WikiFormatError(
                    f"$.query.redirects: more than {MAX_REDIRECTS} redirects from '{requested}'"
                )
            title = redirects[title]
            hops += 1
        if title not in by_title:
            raise WikiFormatError(f"$.query.pages: no page for the requested title '{requested}'")
        found = by_title[title]
        pages.append(
            WikiPage(
                requested=requested,
                title=found.title,
                exists=found.exists,
                page_id=found.page_id,
                revision_id=found.revision_id,
                timestamp=found.timestamp,
            )
        )
    unasked = sorted(set(by_title) - {page.title for page in pages})
    if unasked:
        raise WikiFormatError(f"$.query.pages: a page nobody asked for, '{unasked[0]}'")
    return pages


def _page(value: object, path: str) -> WikiPage:
    page = _object(
        value, path, required=("ns", "title"), optional=("pageid", "missing", "revisions")
    )
    title = _text(page["title"], f"{path}.title")
    namespace = _integer(page["ns"], f"{path}.ns")
    if namespace != 0:
        raise WikiFormatError(f"{path}.ns: expected the article namespace 0, found {namespace}")
    if "missing" in page:
        if page["missing"] is not True:
            raise WikiFormatError(f"{path}.missing: expected true")
        if "pageid" in page or "revisions" in page:
            raise WikiFormatError(f"{path}: a missing page cannot have an id or revisions")
        return WikiPage(title, title, False, None, None, None)
    revisions = _list(page.get("revisions"), f"{path}.revisions")
    if len(revisions) != 1:
        raise WikiFormatError(f"{path}.revisions: expected one revision, found {len(revisions)}")
    revision = _object(
        revisions[0], f"{path}.revisions[0]", required=("revid", "parentid", "timestamp")
    )
    timestamp = _text(revision["timestamp"], f"{path}.revisions[0].timestamp")
    if not is_utc_timestamp(timestamp):
        raise WikiFormatError(
            f"{path}.revisions[0].timestamp: expected an ISO 8601 UTC time, found '{timestamp}'"
        )
    return WikiPage(
        requested=title,
        title=title,
        exists=True,
        page_id=_positive(page.get("pageid"), f"{path}.pageid"),
        revision_id=_positive(revision["revid"], f"{path}.revisions[0].revid"),
        timestamp=timestamp,
    )


def _renames(value: object, path: str, optional: tuple[str, ...]) -> dict[str, str]:
    renames: dict[str, str] = {}
    for index, item in enumerate(_list(value, path)):
        where = f"{path}[{index}]"
        entry = _object(item, where, required=("from", "to"), optional=optional)
        renames[_text(entry["from"], f"{where}.from")] = _text(entry["to"], f"{where}.to")
    return renames


def _object(
    value: object, path: str, *, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WikiFormatError(f"{path}: expected an object, found {type(value).__name__}")
    missing = [key for key in required if key not in value]
    if missing:
        raise WikiFormatError(f"{path}: missing key '{missing[0]}'")
    unknown = sorted(set(value) - set(required) - set(optional))
    if unknown:
        names = ", ".join(f"'{key}'" for key in unknown)
        raise WikiFormatError(f"{path}: unknown key(s) {names}")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WikiFormatError(f"{path}: expected a list, found {type(value).__name__}")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise WikiFormatError(f"{path}: expected a string, found {type(value).__name__}")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WikiFormatError(f"{path}: expected an integer, found {type(value).__name__}")
    return value


def _positive(value: object, path: str) -> int:
    number = _integer(value, path)
    if number <= 0:
        raise WikiFormatError(f"{path}: expected a positive integer, found {number}")
    return number
