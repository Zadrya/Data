# SPDX-License-Identifier: GPL-3.0-or-later
"""Which substances are in the catalog, under which name, from which sources.

The catalog is every substance of the base file, plus the API entries that are not in
the base file, have at least one route with a number (in its dose, duration or
bioavailability) and are named in ``ALLOWED_API_ONLY``. API entries without a number
are class and disambiguation pages: they are dropped and reported. An entry with
numbers that is not on the list is reported too, so that it can be considered.

The two sources are matched by exact name. An API name that differs from a base name
only by case or whitespace, or that the wiki redirects to the same page, is the same
substance: it is reported and takes the canonical title of the wiki as its name.
"""

import re
from dataclasses import dataclass

from zadrya_data.base import BaseFile, BaseSubstance
from zadrya_data.graphql import ApiSubstance
from zadrya_data.mediawiki import WikiPage
from zadrya_data.normalize.errors import NormalizationError
from zadrya_data.normalize.report import Kind, Report
from zadrya_data.schema import SchemaName, load_schema
from zadrya_data.snapshot import Snapshot

# API entries that are not in the base file and may enter the catalog, each with the
# reason. PROPOSED: catalog membership is the owner's decision, confirmed in the
# dataset review. Having route data is not enough: the wiki also has joke and stub
# pages with doses.
ALLOWED_API_ONLY = {
    "25E-NBOH": "a substance with its own wiki article, a sublingual dose and durations",
    "Blue Lotus": "a plant with its own wiki article, a smoked dose and oral durations",
    "Tizanidine": "a medicine with its own wiki article and oral durations",
}

# What a reviewer must know about an API entry that has data and is not allowed.
NOT_ALLOWED_NOTES = {
    "Cake": "its wiki page is a satire page (the 2017 April Fools joke)",
}


@dataclass(frozen=True, slots=True)
class Entry:
    """One substance of the catalog and what each source says about it."""

    name: str
    url: str
    base: BaseSubstance | None
    api: ApiSubstance | None


def _loose(name: str) -> str:
    """Return the name without case and with single spaces, for near matches only."""
    return " ".join(name.casefold().split())


def has_route_data(substance: ApiSubstance) -> bool:
    """Tell whether an API entry has a route with a dose, duration or bioavailability number.

    Units alone are not data: some entries list routes whose every number is null.
    """
    for route in substance.roas or ():
        dose, duration, available = route.dose, route.duration, route.bioavailability
        if available is not None and (available.min is not None or available.max is not None):
            return True
        if dose is not None:
            ranges = [dose.light, dose.common, dose.strong]
            numbers = [dose.threshold, dose.heavy]
            numbers += [bound for item in ranges if item for bound in (item.min, item.max)]
            if any(number is not None for number in numbers):
                return True
        if duration is not None:
            phases = [
                duration.onset,
                duration.comeup,
                duration.peak,
                duration.offset,
                duration.total,
                duration.afterglow,
            ]
            if any(p is not None and (p.min is not None or p.max is not None) for p in phases):
                return True
    return False


def _twin(
    api: ApiSubstance, base_names: dict[str, BaseSubstance], pages: dict[str, WikiPage]
) -> list[str]:
    """Return the base names that are the same substance as an API entry under another spelling."""
    page = pages[api.name]
    found = []
    for name in base_names:
        other = pages[name]
        same_page = page.exists and other.exists and page.title == other.title
        if _loose(name) == _loose(api.name) or same_page:
            found.append(name)
    return found


def build_catalog(base: BaseFile, snapshot: Snapshot, report: Report) -> list[Entry]:
    """Return the catalog entries sorted by name, recording every decision in the report."""
    base_by_name = {substance.name: substance for substance in base.substances}
    pages = {page.requested: page for page in snapshot.pages}
    missing = sorted(
        name
        for name in [*base_by_name, *(s.name for s in snapshot.substances)]
        if name not in pages
    )
    if missing:
        raise NormalizationError(
            f"the snapshot has no wiki record for '{missing[0]}': it was not fetched "
            "with this base file"
        )

    api_for: dict[str, ApiSubstance] = {}
    renamed: dict[str, str] = {}
    additions: list[ApiSubstance] = []
    for api in snapshot.substances:
        if api.name in base_by_name:
            api_for[api.name] = api
            continue
        twins = _twin(api, base_by_name, pages)
        if len(twins) > 1:
            raise NormalizationError(f"the API entry '{api.name}' matches several base names")
        if not twins:
            additions.append(api)
            continue
        twin = twins[0]
        if twin in api_for:
            raise NormalizationError(f"two API entries match the base substance '{twin}'")
        api_for[twin] = api
        page = pages[api.name] if pages[api.name].exists else pages[twin]
        renamed[twin] = page.title if page.exists else twin
        report.add(
            Kind.NAME_MATCHED,
            f"base name '{twin}' and API name '{api.name}' are one substance, "
            f"named '{renamed[twin]}'",
            substance=renamed[twin],
        )

    entries: list[Entry] = []
    for base_name, substance in base_by_name.items():
        name = renamed.get(base_name, base_name)
        api_entry = api_for.get(base_name)
        if api_entry is None:
            report.add(Kind.BASE_ONLY, "the API has no entry: base data only", substance=name)
        entries.append(Entry(name, substance.url, substance, api_entry))
        _report_page(pages[base_name], name, report)
    for api in additions:
        if not has_route_data(api):
            report.add(
                Kind.API_ENTRY_DROPPED,
                "not in the base file and no route with a dose, duration or "
                "bioavailability number",
                substance=api.name,
            )
            continue
        if api.name not in ALLOWED_API_ONLY:
            note = NOT_ALLOWED_NOTES.get(api.name)
            report.add(
                Kind.API_ENTRY_NOT_ALLOWED,
                "not in the base file, has route data, not on the allow list"
                + (f": {note}" if note else ""),
                substance=api.name,
            )
            continue
        if api.url is None:
            raise NormalizationError(f"the API entry '{api.name}' has no url")
        report.add(
            Kind.API_ONLY_ADDED,
            f"not in the base file, on the allow list ({ALLOWED_API_ONLY[api.name]})",
            substance=api.name,
        )
        entries.append(Entry(api.name, api.url, None, api))
        _report_page(pages[api.name], api.name, report)

    entries.sort(key=lambda entry: entry.name)
    url = re.compile(
        load_schema(SchemaName.SUBSTANCES)["$defs"]["substance"]["properties"]["url"]["pattern"]
    )
    for previous, entry in zip(entries, entries[1:]):
        if previous.name == entry.name:
            raise NormalizationError(f"two substances end up with the name '{entry.name}'")
    for entry in entries:
        if not url.search(entry.url):
            raise NormalizationError(f"'{entry.name}' has a url the schema refuses: {entry.url}")
    return entries


def _report_page(page: WikiPage, name: str, report: Report) -> None:
    if not page.exists:
        report.add(Kind.WIKI_PAGE_MISSING, "wiki page missing", substance=name)
    elif page.title != name:
        report.add(
            Kind.WIKI_TITLE_DIFFERS,
            f"the wiki redirects to '{page.title}'",
            substance=name,
        )
