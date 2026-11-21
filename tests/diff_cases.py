# SPDX-License-Identifier: GPL-3.0-or-later
"""Builders for diff tests: small valid datasets with every other key filled in."""

from pathlib import Path
from typing import Any
from urllib.parse import quote

FIXTURES = Path(__file__).parent / "fixtures" / "diff"
BASE_FILE = Path(__file__).parents[1] / "sources" / "base" / "Substances.json"


def substance(name: str, **extra: Any) -> dict[str, Any]:
    """A valid substance with nothing but a name, and the keys given."""
    return {
        "name": name,
        "aliases": [],
        "url": f"https://psychonautwiki.org/wiki/{quote(name)}",
        "categories": [],
        "classes": {"psychoactive": [], "chemical": []},
        "roas": [],
        "crossTolerances": [],
        "interactions": {"dangerous": [], "unsafe": [], "uncertain": []},
        "toxicities": [],
    } | extra


def dataset(*substances: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A valid dataset of the substances, with the top-level keys given."""
    return {
        "schemaVersion": "1.0.0",
        "datasetVersion": "1.0.0",
        "attribution": [{"name": "PW", "url": "https://psychonautwiki.org", "license": "CC0"}],
        "categories": [],
        "interactionGroups": [],
        "crossToleranceGroups": [],
        "substances": list(substances),
    } | extra


def interacting(name: str, severity: str, *targets: str) -> dict[str, Any]:
    """A substance listing catalog substances under one severity."""
    interactions: dict[str, list[dict[str, str]]] = {
        "dangerous": [],
        "unsafe": [],
        "uncertain": [],
    }
    interactions[severity] = [{"kind": "substance", "name": target} for target in targets]
    return substance(name, interactions=interactions)


def group(group_id: str, *members: str, name: str = "Group") -> dict[str, Any]:
    """An entry of interactionGroups or crossToleranceGroups."""
    return {"id": group_id, "name": name, "members": list(members)}


def oral(**route: Any) -> dict[str, Any]:
    """An oral route with the keys given."""
    return {"route": "oral"} | route
