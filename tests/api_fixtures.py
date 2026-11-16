# SPDX-License-Identifier: GPL-3.0-or-later
"""Recorded API answers in ``tests/fixtures/api`` and a transport that replays them.

The fixtures are real answers trimmed to a few entries that cover the odd cases:
``graphql.json`` has LSD (all three interaction lists, bioavailability), 2C-x (a class
page without routes), MDAI (a phase with null units), Clonidine (dose units written
with the Greek letter mu), Phenylpiracetam (the unit ``hour``), Diphenidine (a range
with a null bound) and Ayahuasca (a null class list). ``mediawiki-query.json`` has a
redirect, a normalized title, two missing pages and a title outside ASCII.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from zadrya_data import graphql, mediawiki
from zadrya_data.http import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "api"

# The titles that mediawiki-query.json was recorded for, in request order.
WIKI_TITLES = (
    "LSD",
    "Acid",
    "Oxazepam",
    "No such page xyz",
    "Βk-2C-B",
    "lsd",
    "DXM",
    "1,4-Butanediol",
)


def recorded(name: str) -> Any:
    """Return one recorded answer as parsed JSON."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def replay(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[PoliteClient, list[httpx.Request]]:
    """Return a client that never sleeps and answers from the handler, and the requests it saw."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = PoliteClient(httpx.MockTransport(handle), sleep=lambda seconds: None)
    return client, seen


def api_handler(request: httpx.Request) -> httpx.Response:
    """Answer the GraphQL query with the recording, and any wiki lookup with missing pages."""
    if str(request.url) == graphql.ENDPOINT:
        return httpx.Response(200, json=recorded("graphql.json"))
    assert str(request.url) == mediawiki.ENDPOINT
    titles = parse_qs(request.content.decode())["titles"][0].split("|")
    pages: list[dict[str, object]] = []
    for number, title in enumerate(titles):
        if title == "Oxazepam":
            pages.append({"ns": 0, "title": title, "missing": True})
        else:
            revision = {"revid": 1000 + number, "parentid": 1, "timestamp": "2026-01-01T00:00:00Z"}
            pages.append({"pageid": number + 1, "ns": 0, "title": title, "revisions": [revision]})
    return httpx.Response(200, json={"batchcomplete": True, "query": {"pages": pages}})
