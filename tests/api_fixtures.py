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

import httpx

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
