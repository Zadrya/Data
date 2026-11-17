# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalization: the typed base file and a typed snapshot become schema-shaped data.

``normalize`` is pure: no network, no clock, no randomness. The same inputs give the
same document and the same report. One module holds each concern:

- ``catalog``: which substances exist and under which name;
- ``names``: aliases;
- ``fields``: summary, risks, safer use, addiction potential, toxicities;
- ``categories`` and ``classes``;
- ``routes`` with ``dose``, ``duration`` and ``bioavailability``, merged by ``blocks``;
- ``tolerance`` and ``cross_tolerance``;
- ``report``: every drop, fallback and repair.

Interactions are not normalized yet. Until they are, every substance has empty
interaction lists and ``interactionGroups`` is empty, so the document already has the
shape of the schema. ``_not_yet_normalized`` is the one place that says so.
"""

from dataclasses import dataclass
from typing import Any

from zadrya_data.base import BaseFile
from zadrya_data.normalize.catalog import Entry, build_catalog
from zadrya_data.normalize.categories import category_list, substance_categories
from zadrya_data.normalize.classes import substance_classes
from zadrya_data.normalize.cross_tolerance import (
    cross_tolerance_groups,
    substance_cross_tolerances,
)
from zadrya_data.normalize.errors import NormalizationError
from zadrya_data.normalize.fields import substance_fields
from zadrya_data.normalize.names import aliases
from zadrya_data.normalize.report import Finding, Kind, Report
from zadrya_data.normalize.routes import normalize_routes
from zadrya_data.normalize.tolerance import substance_tolerance
from zadrya_data.snapshot import Snapshot

__all__ = ["Finding", "Kind", "NormalizationError", "Normalized", "Report", "normalize"]


@dataclass(frozen=True, slots=True)
class Normalized:
    """The result of a normalization.

    ``document`` holds ``categories``, ``interactionGroups``, ``crossToleranceGroups``
    and ``substances`` as plain data in the shape of the schema. The versions and the
    attribution of a dataset are added by the build. Order: categories as in the base
    file; substances by the code points of their names; routes in the order of the
    schema's route list; aliases, classes, toxicities and safer use items in source
    order (base first, then API, where both contribute).
    """

    document: dict[str, Any]
    report: Report


def _not_yet_normalized() -> dict[str, Any]:
    """Return the parts of a substance that the next slice fills in."""
    return {"interactions": {"dangerous": [], "unsafe": [], "uncertain": []}}


def _has_number(routes: list[dict[str, Any]]) -> bool:
    """Tell whether any route still has a dose boundary, a duration or a bioavailability."""
    for route in routes:
        boundaries = [key for key in route.get("dose", {}) if key != "units"]
        if boundaries or route.get("duration") or route.get("bioavailability"):
            return True
    return False


def _substance(entry: Entry, known_categories: set[str], report: Report) -> dict[str, Any]:
    base, api = entry.base, entry.api
    substance: dict[str, Any] = {
        "name": entry.name,
        "aliases": aliases(
            entry.name,
            base.common_names if base else (),
            (api.common_names or ()) if api else (),
            report,
        ),
        "url": entry.url,
        "categories": substance_categories(entry.name, base, api, known_categories, report),
        "classes": substance_classes(entry.name, api, report),
    }
    substance |= substance_fields(entry.name, base, api, report)
    substance["roas"] = normalize_routes(entry.name, base, api, report)
    tolerance = substance_tolerance(entry.name, base, api, report)
    if tolerance is not None:
        substance["tolerance"] = tolerance
    substance["crossTolerances"] = substance_cross_tolerances(entry.name, base, api, report)
    substance |= _not_yet_normalized()
    return substance


def normalize(base: BaseFile, snapshot: Snapshot) -> Normalized:
    """Turn the base file and a snapshot into the substance part of a dataset."""
    report = Report()
    categories = category_list(base)
    known = {category["id"] for category in categories}
    substances = []
    for entry in build_catalog(base, snapshot, report):
        substance = _substance(entry, known, report)
        if entry.base is None and not _has_number(substance["roas"]):
            report.add(
                Kind.API_ENTRY_DROPPED,
                "not in the base file and no route with a number is left after normalization",
                substance=entry.name,
            )
            continue
        substances.append(substance)
    document = {
        "categories": categories,
        "interactionGroups": [],
        "crossToleranceGroups": cross_tolerance_groups(substances, report),
        "substances": substances,
    }
    return Normalized(document, report)
