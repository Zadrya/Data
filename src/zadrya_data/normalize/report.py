# SPDX-License-Identifier: GPL-3.0-or-later
"""The report of a normalization: every drop, fallback and repair, as data.

Normalization never changes anything silently. Whatever it drops, takes from the
other source or repairs is recorded as a ``Finding``, in the order the catalog is
walked (substances by name, routes in schema order), so the same input gives the
same report. A later step prints it for review.
"""

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    """What a finding is about. The values are stable: reports are compared across builds."""

    # Catalog
    API_ENTRY_DROPPED = "api-entry-dropped"
    API_ENTRY_NOT_ALLOWED = "api-entry-not-on-allow-list"
    API_ONLY_ADDED = "api-only-added"
    BASE_ONLY = "base-only"
    NAME_MATCHED = "name-matched"
    WIKI_PAGE_MISSING = "wiki-page-missing"
    WIKI_TITLE_DIFFERS = "wiki-title-differs"
    # Names and text
    ALIAS_DROPPED = "alias-dropped"
    TEXT_DROPPED = "text-dropped"
    NO_SUMMARY = "no-summary"
    # Categories and classes
    CATEGORY_UNKNOWN = "category-unknown"
    CATEGORIES_DERIVED = "categories-derived"
    CLASS_UNMAPPED = "class-unmapped"
    # Routes and their blocks
    ROUTE_ONLY_IN_BASE = "route-only-in-base"
    ROUTE_ONLY_IN_API = "route-only-in-api"
    API_BLOCK_REJECTED = "api-block-rejected"
    BASE_BLOCK_USED = "base-block-used"
    BLOCK_DROPPED = "block-dropped"
    API_PHASE_IGNORED = "api-phase-ignored"
    DOSE_BOUNDARY_FILLED = "dose-boundary-filled"
    DOSE_FILL_DISCARDED = "dose-fill-discarded"
    DOSE_LABEL_DIFFERS = "dose-label-differs"
    DOSE_EQUAL_BOUNDARIES = "dose-equal-boundaries"
    UNIT_REPAIRED = "unit-repaired"
    UNIT_NOT_MASS = "unit-not-mass"
    UNIT_QUALIFIED = "unit-qualified"
    DURATION_ROUNDED = "duration-rounded"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing normalization did that a reviewer should be able to see."""

    kind: Kind
    substance: str | None
    route: str | None
    detail: str


@dataclass(slots=True)
class Report:
    """The findings of one normalization, in the order they were made."""

    findings: list[Finding] = field(default_factory=list)

    def add(
        self, kind: Kind, detail: str, *, substance: str | None = None, route: str | None = None
    ) -> None:
        """Record one finding."""
        self.findings.append(Finding(kind, substance, route, detail))

    def of(self, kind: Kind) -> list[Finding]:
        """Return the findings of one kind."""
        return [finding for finding in self.findings if finding.kind is kind]

    def counts(self) -> dict[str, int]:
        """Return the number of findings per kind, by kind name."""
        return dict(sorted(Counter(finding.kind.value for finding in self.findings).items()))
