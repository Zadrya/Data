# SPDX-License-Identifier: GPL-3.0-or-later
"""Builders for normalization tests: small inputs with every other key filled in.

A reference case under ``tests/fixtures/normalize`` states only what its rule is
about: a few keys of a base substance, a few keys of an API entry. These helpers add
the rest (required keys of the base file, the nulls the API always sends) and build
the typed objects that ``normalize`` takes, without a network or a file.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

from zadrya_data import graphql
from zadrya_data.base import BaseFile, parse_base
from zadrya_data.mediawiki import WikiPage
from zadrya_data.snapshot import Snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "normalize"

CATEGORIES = [
    {"name": "psychedelic", "description": "Psychedelics.", "color": 1},
    {"name": "stimulant", "description": "Stimulants.", "color": 2},
    {"name": "depressant", "description": "Depressants.", "color": 3},
    {"name": "common", "description": "Common substances.", "color": 4},
]

_RANGES = ("light", "common", "strong")
_PHASES = ("onset", "comeup", "peak", "offset", "total", "afterglow", "duration")
_API_KEYS = (
    "url",
    "featured",
    "summary",
    "systematicName",
    "commonNames",
    "addictionPotential",
    "toxicity",
    "crossTolerances",
    "class",
    "tolerance",
    "roas",
    "uncertainInteractions",
    "unsafeInteractions",
    "dangerousInteractions",
)


def base_substance(partial: dict[str, Any]) -> dict[str, Any]:
    """Return a base substance with the required keys the partial one leaves out."""
    name = partial["name"]
    return {
        "commonNames": [],
        "url": f"https://psychonautwiki.org/wiki/{name.replace(' ', '_')}",
        "isApproved": True,
        "crossTolerances": [],
        "toxicities": [],
        "categories": [],
        "roas": [],
    } | partial


def _api_route(partial: dict[str, Any]) -> dict[str, Any]:
    route: dict[str, Any] = {"dose": None, "duration": None, "bioavailability": None} | partial
    if route["dose"] is not None:
        dose = {"units": None, "threshold": None, "heavy": None} | route["dose"]
        for name in _RANGES:
            dose[name] = None if dose.get(name) is None else {"min": None, "max": None} | dose[name]
        route["dose"] = dose
    if route["duration"] is not None:
        duration = dict(route["duration"])
        for name in _PHASES:
            given = duration.get(name)
            duration[name] = (
                None if given is None else {"min": None, "max": None, "units": None} | given
            )
        route["duration"] = duration
    if route["bioavailability"] is not None:
        route["bioavailability"] = {"min": None, "max": None} | route["bioavailability"]
    return route


def api_substance(partial: dict[str, Any]) -> dict[str, Any]:
    """Return an API entry with every key the API sends, null where the partial one is silent."""
    name = partial["name"]
    entry = dict.fromkeys(_API_KEYS) | partial
    if entry["url"] is None:
        entry["url"] = f"https://psychonautwiki.org/wiki/{name.replace(' ', '%20')}"
    if entry["roas"] is not None:
        entry["roas"] = [_api_route(route) for route in entry["roas"]]
    if entry["class"] is not None:
        entry["class"] = {"chemical": None, "psychoactive": None} | entry["class"]
    return entry


def build(
    base: list[dict[str, Any]],
    api: list[dict[str, Any]],
    pages: dict[str, dict[str, Any]] | None = None,
    categories: list[dict[str, Any]] | None = None,
) -> tuple[BaseFile, Snapshot]:
    """Return the typed inputs of ``normalize`` for partial base substances and API entries.

    Every name has a wiki page titled like the name, unless ``pages`` says otherwise
    with ``{"title": ..., "exists": ...}``.
    """
    base_file = parse_base(
        {
            "categories": CATEGORIES if categories is None else categories,
            "substances": [base_substance(partial) for partial in base],
        }
    )
    entries = sorted((api_substance(partial) for partial in api), key=lambda e: e["name"])
    substances = graphql.parse_data({"substances": entries}) if entries else ()
    names = sorted({s.name for s in base_file.substances} | {s.name for s in substances})
    records = []
    for number, name in enumerate(names, start=1):
        override = (pages or {}).get(name, {})
        if override.get("exists", True):
            records.append(
                WikiPage(
                    name,
                    override.get("title", name),
                    True,
                    number,
                    1000 + number,
                    "2026-01-01T00:00:00Z",
                )
            )
        else:
            records.append(WikiPage(name, override.get("title", name), False, None, None, None))
    snapshot = Snapshot(
        substances=substances,
        pages=tuple(records),
        base_names=tuple(sorted(s.name for s in base_file.substances)),
        fetched_on=date(2026, 11, 16),
        counts={},
    )
    return base_file, snapshot


def case_names() -> list[str]:
    """Return the names of the reference cases, sorted."""
    return sorted(path.stem for path in FIXTURES.glob("*.json"))


def load_case(name: str) -> dict[str, Any]:
    """Return one reference case as parsed JSON."""
    case: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return case
