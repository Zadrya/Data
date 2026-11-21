# SPDX-License-Identifier: GPL-3.0-or-later
"""The dataset diff report: what changed between two datasets, as readable Markdown.

``compare`` takes two schema-valid documents and returns every difference as rows of
a few sections; ``render`` turns them into Markdown. Both are pure and deterministic:
everything is sorted, nothing depends on the order of a set or a dict. The rules
(renames, interaction pairs, the cap, the escaping) are in
``docs/adr/0007-diff-report.md``.

A section shows at most ``max_rows`` rows and says how many it left out, except for
the rows a reviewer must never miss, which are always shown: removed substances,
lowered and removed interactions, members removed from an interaction group, and
dose changes in the risky direction.
"""

import argparse
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from zadrya_data.base import load_base
from zadrya_data.mediawiki import WikiPage
from zadrya_data.normalize import NormalizationError, normalize
from zadrya_data.schema import SCHEMA_VERSION, SchemaName, load_schema, validate
from zadrya_data.snapshot import Snapshot
from zadrya_data.strict_json import loads

DEFAULT_MAX_ROWS = 100

SEVERITIES = ("dangerous", "unsafe", "uncertain")
_RANK = {"uncertain": 1, "unsafe": 2, "dangerous": 3}
BOUNDARIES = ("thresholdMin", "lightMin", "commonMin", "strongMin", "heavyMin")
# A boundary in this list that rises shows the doses between the two values in the
# class below (ADR 4); one of the upper boundaries that disappears does the same.
_RISKY_IF_HIGHER = ("strongMin", "heavyMin")
_RISKY_IF_REMOVED = ("commonMin", "strongMin", "heavyMin")
PHASES = ("onset", "comeup", "peak", "offset", "total", "afterglow")
FLAGGED_FIELDS = (
    "aliases",
    "url",
    "categories",
    "classes",
    "summary",
    "addictionPotential",
    "toxicities",
    "effectsSummary",
    "dosageRemark",
    "generalRisks",
    "longtermRisks",
    "saferUse",
)
GROUP_LISTS = ("interactionGroups", "crossToleranceGroups")
_ABSENT = "none"

# ASCII punctuation that has no meaning in Markdown and stays as it is.
_INERT = frozenset(",;'\"/?=%")
_ZERO_WIDTH_SPACE = "&#8203;"


class DiffInputError(ValueError):
    """An input of the diff cannot be read: a file, its JSON or the base file format."""


class DiffRefusedError(ValueError):
    """An input of the diff is readable and is not a dataset that can be compared."""


class Change(StrEnum):
    """How an interaction changed between the two datasets."""

    LOWERED = "lowered"
    REMOVED = "removed"
    RAISED = "raised"
    ADDED = "added"


@dataclass(frozen=True, slots=True)
class Row:
    """One line of a section. A protected row is never left out by the cap."""

    cells: tuple[str, ...]
    protected: bool = False


@dataclass(frozen=True, slots=True)
class Rename:
    """A substance that has another name in the new dataset."""

    old: str
    new: str
    reason: str


@dataclass(slots=True)
class Diff:
    """Every difference between two datasets, in the order the report shows them."""

    old_count: int
    new_count: int
    versions: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    renamed: list[Rename] = field(default_factory=list)
    numbers: list[Row] = field(default_factory=list)
    interactions: dict[Change, list[Row]] = field(default_factory=dict)
    groups: list[Row] = field(default_factory=list)
    flags: list[Row] = field(default_factory=list)
    unflagged: int = 0


# Loading


def _route_order() -> tuple[str, ...]:
    schema = load_schema(SchemaName.SUBSTANCES)
    return tuple(schema["$defs"]["roa"]["properties"]["route"]["enum"])


def check_dataset(document: object, where: str) -> dict[str, Any]:
    """Return the document if it is a valid dataset with unique names, or raise.

    The schema does not check that names are unique (the invariants do); the diff
    matches substances by name, so it refuses a dataset where a name repeats.
    """
    violations = validate(document, SchemaName.SUBSTANCES)
    if violations:
        shown = "; ".join(str(violation) for violation in violations[:5])
        raise DiffRefusedError(
            f"{where} is not valid against the substances schema "
            f"({len(violations)} violation(s)): {shown}"
        )
    assert isinstance(document, dict)
    for key in ("substances", *GROUP_LISTS, "categories"):
        label = "name" if key == "substances" else "id"
        seen: set[str] = set()
        for entry in document[key]:
            if entry[label] in seen:
                raise DiffRefusedError(f"{where}: {key} has '{entry[label]}' twice")
            seen.add(entry[label])
    return document


def load_dataset(path: Path) -> dict[str, Any]:
    """Read a dataset file as strict JSON and check it with ``check_dataset``."""
    try:
        document = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DiffInputError(f"cannot read {path} as strict JSON: {error}") from None
    return check_dataset(document, str(path))


def load_base_dataset(path: Path) -> dict[str, Any]:
    """Normalize the base file alone, as if the API had no entry, and return it as a dataset.

    The first dataset is compared with this, so its review shows every change the
    API brought against the base file. The versions and the attribution of the
    result are placeholders: the report does not show them for the base file.
    """
    try:
        base = load_base(path)
    except (OSError, ValueError) as error:
        raise DiffInputError(f"cannot read the base file {path}: {error}") from None
    names = tuple(sorted(substance.name for substance in base.substances))
    pages = tuple(WikiPage(name, name, True, None, None, None) for name in names)
    normalized = normalize(base, Snapshot((), pages, names, date(1970, 1, 1), {}))
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "datasetVersion": "0.0.0",
        "attribution": [
            {"name": "base file", "url": "https://psychonautwiki.org", "license": "none"}
        ],
        **normalized.document,
    }
    return check_dataset(document, f"{path} (normalized)")


# Comparing


def _casefolded(texts: Iterable[str]) -> set[str]:
    return {text.casefold() for text in texts}


def _match_renames(removed: list[dict[str, Any]], added: list[dict[str, Any]]) -> list[Rename]:
    """Pair a removed and an added substance when exactly one of each matches.

    They match when the names are equal but for case, or when one name is an alias
    of the other substance (compared without case). A name that matches several
    candidates is not paired: both stay added and removed.
    """

    def reason(old: dict[str, Any], new: dict[str, Any]) -> str | None:
        if old["name"].casefold() == new["name"].casefold():
            return "same name but for case"
        if old["name"].casefold() in _casefolded(new["aliases"]):
            return "the old name is an alias of the new substance"
        if new["name"].casefold() in _casefolded(old["aliases"]):
            return "the new name is an alias of the old substance"
        return None

    candidates = {
        (old["name"], new["name"]): why
        for old in removed
        for new in added
        if (why := reason(old, new)) is not None
    }
    renames = []
    for (old_name, new_name), why in candidates.items():
        olds = [pair for pair in candidates if pair[0] == old_name]
        news = [pair for pair in candidates if pair[1] == new_name]
        if len(olds) == 1 and len(news) == 1:
            renames.append(Rename(old_name, new_name, why))
    return sorted(renames, key=lambda rename: (rename.new, rename.old))


def _number(value: float | int) -> str:
    return repr(value) if isinstance(value, float) else str(value)


def _with_unit(value: float | int | None, unit: str) -> str:
    return _ABSENT if value is None else f"{_number(value)} {escape(unit)}"


def _direction(old: float | int | None, new: float | int | None) -> str:
    if old is None:
        return "added"
    if new is None:
        return "removed"
    return "higher" if new > old else "lower"


def _dose_rows(name: str, route: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    """Compare two dose blocks of a route; an empty dict is a route without a dose."""
    rows = []
    old_unit, new_unit = old.get("units", ""), new.get("units", "")
    comparable = old_unit == new_unit or not old or not new
    if old and new and not comparable:
        rows.append(
            Row(
                (
                    name,
                    route,
                    "dose units",
                    escape(old_unit),
                    escape(new_unit),
                    "**units differ: the numbers cannot be compared**",
                ),
                protected=True,
            )
        )
    elif bool(old) != bool(new):
        units = (escape(old_unit) or _ABSENT, escape(new_unit) or _ABSENT)
        rows.append(Row((name, route, "dose units", *units, "added" if new else "removed")))
    for boundary in BOUNDARIES:
        before, after = old.get(boundary), new.get(boundary)
        if before == after:
            continue
        note = _direction(before, after) if comparable else "units differ"
        risky = comparable and (
            (note == "higher" and boundary in _RISKY_IF_HIGHER)
            or (note == "removed" and boundary in _RISKY_IF_REMOVED)
        )
        rows.append(
            Row(
                (
                    name,
                    route,
                    f"dose {boundary}",
                    _with_unit(before, old_unit),
                    _with_unit(after, new_unit),
                    f"**{note} (risky)**" if risky else note,
                ),
                protected=risky,
            )
        )
    return rows


def _range_rows(
    name: str, route: str, label: str, old: dict[str, Any], new: dict[str, Any], unit: str
) -> list[Row]:
    return [
        Row(
            (
                name,
                route,
                f"{label} {bound}",
                _with_unit(old.get(bound), unit),
                _with_unit(new.get(bound), unit),
                _direction(old.get(bound), new.get(bound)),
            )
        )
        for bound in ("min", "max")
        if old.get(bound) != new.get(bound)
    ]


def _route_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    route = old["route"]
    rows = _dose_rows(name, route, old.get("dose", {}), new.get("dose", {}))
    old_duration, new_duration = old.get("duration", {}), new.get("duration", {})
    for phase in PHASES:
        rows += _range_rows(
            name,
            route,
            f"duration {phase}",
            old_duration.get(phase, {}),
            new_duration.get(phase, {}),
            "min",
        )
    rows += _range_rows(
        name,
        route,
        "bioavailability",
        old.get("bioavailability", {}),
        new.get("bioavailability", {}),
        "%",
    )
    return rows


def _tolerance_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    rows = []
    if old.get("full") != new.get("full"):
        rows.append(
            Row(
                (
                    name,
                    "all routes",
                    "tolerance full",
                    _text(old.get("full")),
                    _text(new.get("full")),
                    "changed",
                ),
            )
        )
    for time in ("half", "zero"):
        before, after = old.get(time, {}), new.get(time, {})
        if before.get("text") != after.get("text"):
            rows.append(
                Row(
                    (
                        name,
                        "all routes",
                        f"tolerance {time}",
                        _text(before.get("text")),
                        _text(after.get("text")),
                        "changed",
                    ),
                )
            )
        rows += _range_rows(name, "all routes", f"tolerance {time}", before, after, "min")
    return rows


def _text(value: str | None) -> str:
    return _ABSENT if value is None else escape(value)


def _number_rows(
    name: str, old: dict[str, Any], new: dict[str, Any], routes: Sequence[str]
) -> list[Row]:
    rows = []
    old_routes = {roa["route"]: roa for roa in old["roas"]}
    new_routes = {roa["route"]: roa for roa in new["roas"]}
    for route in routes:
        if route in old_routes and route in new_routes:
            rows += _route_rows(name, old_routes[route], new_routes[route])
        elif route in old_routes:
            rows.append(Row((name, route, "route", "present", _ABSENT, "**removed**"), True))
        elif route in new_routes:
            rows.append(Row((name, route, "route", _ABSENT, "present", "added")))
    rows += _tolerance_rows(name, old.get("tolerance", {}), new.get("tolerance", {}))
    return rows


type Pair = tuple[str, str, str]


def _interactions(document: dict[str, Any], rename: Callable[[str], str]) -> dict[Pair, str]:
    """Return the severity of every pair the dataset lists.

    Two catalog substances form one pair whichever of them lists the other, and the
    pair takes the higher severity, as the app reads it (ADR 5). A group or a target
    outside the catalog forms a pair with the substance that lists it. Groups are not
    expanded: membership changes have their own section.
    """
    pairs: dict[Pair, str] = {}
    for substance in document["substances"]:
        subject = rename(substance["name"])
        for severity in SEVERITIES:
            for target in substance["interactions"][severity]:
                if target["kind"] == "substance":
                    first, second = sorted((subject, rename(target["name"])))
                    key = ("substance", first, second)
                elif target["kind"] == "group":
                    key = ("group", subject, target["groupId"])
                else:
                    key = ("other", subject, target["name"])
                if _RANK[severity] > _RANK.get(pairs.get(key, ""), 0):
                    pairs[key] = severity
    return pairs


def _pair_cells(pair: Pair) -> tuple[str, str]:
    kind, subject, target = pair
    if kind == "substance":
        return escape(subject), escape(target)
    if kind == "group":
        return escape(subject), f"group {escape(target)}"
    return escape(subject), f"other: {escape(target)}"


def _interaction_rows(
    old: dict[str, Any], new: dict[str, Any], rename: Callable[[str], str]
) -> dict[Change, list[Row]]:
    before = _interactions(old, rename)
    after = _interactions(new, rename)
    rows: dict[Change, list[Row]] = {change: [] for change in Change}
    for pair in sorted(before.keys() | after.keys()):
        was, now = before.get(pair), after.get(pair)
        if was == now:
            continue
        if was is None:
            change = Change.ADDED
        elif now is None:
            change = Change.REMOVED
        else:
            change = Change.RAISED if _RANK[now] > _RANK[was] else Change.LOWERED
        protected = change in (Change.LOWERED, Change.REMOVED)
        rows[change].append(
            Row((*_pair_cells(pair), was or _ABSENT, now or _ABSENT), protected=protected)
        )
    return rows


def _group_rows(
    old: dict[str, Any], new: dict[str, Any], rename: Callable[[str], str]
) -> list[Row]:
    rows = []
    for key in GROUP_LISTS:
        label = "interaction group" if key == "interactionGroups" else "cross tolerance group"
        before = {group["id"]: group for group in old[key]}
        after = {group["id"]: group for group in new[key]}
        for group_id in sorted(before.keys() | after.keys()):
            was, now = before.get(group_id), after.get(group_id)
            cell = f"{label} {escape(group_id)}"
            if now is None:
                gone = sorted(rename(name) for name in before[group_id]["members"])
                members = ", ".join(escape(name) for name in gone)
                rows.append(Row((cell, "**group removed**", members or _ABSENT), protected=True))
                continue
            if was is None:
                members = ", ".join(escape(name) for name in sorted(now["members"]))
                rows.append(Row((cell, "group added", members or _ABSENT)))
                continue
            if was["name"] != now["name"]:
                rows.append(Row((cell, "name changed", "n/a")))
            old_members = {rename(name) for name in was["members"]}
            new_members = set(now["members"])
            if gone := sorted(old_members - new_members):
                rows.append(
                    Row(
                        (cell, "**members removed**", ", ".join(escape(n) for n in gone)),
                        protected=key == "interactionGroups",
                    )
                )
            if joined := sorted(new_members - old_members):
                rows.append(Row((cell, "members added", ", ".join(escape(n) for n in joined))))
    return rows


def _cross_tolerance_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    rows = []
    before, after = set(old["crossTolerances"]), set(new["crossTolerances"])
    cell = f"substance {escape(name)}"
    if gone := sorted(before - after):
        listed = ", ".join(escape(group) for group in gone)
        rows.append(Row((cell, "cross tolerance removed", listed)))
    if joined := sorted(after - before):
        listed = ", ".join(escape(group) for group in joined)
        rows.append(Row((cell, "cross tolerance added", listed)))
    return rows


def _flag(key: str, old: dict[str, Any], new: dict[str, Any]) -> str | None:
    if key not in old and key in new:
        return f"{key} (added)"
    if key in old and key not in new:
        return f"{key} (removed)"
    return f"{key} (changed)" if old.get(key) != new.get(key) else None


def _category_rows(old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    before = {category["id"]: category for category in old["categories"]}
    after = {category["id"]: category for category in new["categories"]}
    rows = []
    for category_id in sorted(before.keys() | after.keys()):
        was, now = before.get(category_id, {}), after.get(category_id, {})
        changed = [f for key in ("name", "description") if (f := _flag(key, was, now))]
        if not was or not now:
            changed = ["category added" if now else "category removed"]
        if changed:
            rows.append(Row((f"category {escape(category_id)}", ", ".join(changed))))
    return rows


def compare(old: dict[str, Any], new: dict[str, Any], *, versions: bool = True) -> Diff:
    """Return every difference between two valid datasets (see ``check_dataset``).

    With ``versions`` false, the versions and the attribution are not compared: the
    old side is the base file, whose values for them are placeholders.
    """
    routes = _route_order()
    old_by_name = {substance["name"]: substance for substance in old["substances"]}
    new_by_name = {substance["name"]: substance for substance in new["substances"]}
    gone = [old_by_name[name] for name in sorted(old_by_name.keys() - new_by_name.keys())]
    fresh = [new_by_name[name] for name in sorted(new_by_name.keys() - old_by_name.keys())]
    renames = _match_renames(gone, fresh)
    new_name = {rename.old: rename.new for rename in renames}

    def rename(name: str) -> str:
        return new_name.get(name, name)

    diff = Diff(old_count=len(old_by_name), new_count=len(new_by_name), renamed=renames)
    for key in ("schemaVersion", "datasetVersion") if versions else ():
        if old[key] != new[key]:
            diff.versions.append(f"{key}: {escape(old[key])} -> {escape(new[key])}")
    if versions and old["attribution"] != new["attribution"]:
        diff.versions.append("attribution: changed")
    diff.removed = sorted(s["name"] for s in gone if s["name"] not in new_name)
    diff.added = sorted(s["name"] for s in fresh if s["name"] not in new_name.values())

    pairs = sorted(
        [(name, name) for name in old_by_name.keys() & new_by_name.keys()]
        + [(r.old, r.new) for r in renames],
        key=lambda pair: pair[1],
    )
    diff.flags = _category_rows(old, new)
    diff.groups = _group_rows(old, new, rename)
    for old_name, name in pairs:
        before, after = old_by_name[old_name], new_by_name[name]
        diff.numbers += _number_rows(escape(name), before, after, routes)
        diff.groups += _cross_tolerance_rows(name, before, after)
        flagged = [f for key in FLAGGED_FIELDS if (f := _flag(key, before, after))]
        if flagged:
            diff.flags.append(Row((f"substance {escape(name)}", ", ".join(flagged))))
        else:
            diff.unflagged += 1
    diff.interactions = _interaction_rows(old, new, rename)
    return diff


# Rendering


def escape(text: str) -> str:
    """Return text that Markdown shows as written, in a paragraph, a list or a table cell.

    Every ASCII punctuation character with a meaning in Markdown (or GitHub's math and
    tables) is escaped with a backslash. ``@`` and ``#`` are followed by a zero width
    space, so a name never mentions a user or links an issue. Line breaks and other
    control characters become spaces, and the em dash becomes its character
    reference, so the report never contains one.
    """
    out = []
    for char in text:
        if char in "@#":
            out.append(f"\\{char}{_ZERO_WIDTH_SPACE}")
        elif char.isascii() and not char.isalnum() and not char.isspace() and char not in _INERT:
            out.append(f"\\{char}")
        elif char == "\u2014":
            out.append("&#8212;")
        elif char.isspace() or not char.isprintable():
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def _capped(rows: list[Row], max_rows: int) -> tuple[list[Row], int]:
    """Keep every protected row and the first unprotected ones, up to ``max_rows`` in all."""
    room = max(max_rows - sum(row.protected for row in rows), 0)
    kept = []
    for row in rows:
        if row.protected or room > 0:
            kept.append(row)
            room -= not row.protected
    return kept, len(rows) - len(kept)


def _table(header: Sequence[str], rows: list[Row], max_rows: int) -> list[str]:
    if not rows:
        return ["None.", ""]
    kept, omitted = _capped(rows, max_rows)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(row.cells) + " |" for row in kept),
        "",
    ]
    if omitted:
        lines += [f"{omitted} more row(s) not shown.", ""]
    return lines


def _bullets(rows: list[Row], max_rows: int) -> list[str]:
    if not rows:
        return ["None.", ""]
    kept, omitted = _capped(rows, max_rows)
    lines = [f"- {' '.join(row.cells)}" for row in kept] + [""]
    if omitted:
        lines += [f"{omitted} more substance(s) not shown.", ""]
    return lines


def render(diff: Diff, *, old_label: str, new_label: str, max_rows: int = DEFAULT_MAX_ROWS) -> str:
    """Return the report as Markdown. The same diff always gives the same text."""
    lowered = len(diff.interactions[Change.LOWERED])
    removed = len(diff.interactions[Change.REMOVED])
    counts = {change: len(rows) for change, rows in diff.interactions.items()}
    lines = ["# Dataset diff report", ""]
    lines += [f"Old: {escape(old_label)}", "", f"New: {escape(new_label)}", ""]
    if lowered or removed:
        lines += [
            f"> **Warning: {lowered} interaction(s) lowered and {removed} removed. "
            "Review them first, in the Interactions section.**",
            "",
        ]
    lines += ["## Summary", ""]
    lines += [
        f"- Substances: {diff.old_count} old, {diff.new_count} new",
        f"- Added: {len(diff.added)}, removed: {len(diff.removed)}, "
        f"renamed: {len(diff.renamed)}",
        f"- Changed numbers and units: {len(diff.numbers)}",
        "- Interactions: " + ", ".join(f"{counts[change]} {change}" for change in Change),
        f"- Group and cross tolerance changes: {len(diff.groups)}",
        f"- Categories and texts changed: {len(diff.flags)} "
        f"(unchanged substances: {diff.unflagged})",
        *(f"- {version}" for version in diff.versions),
        "",
    ]
    lines += ["## Substances", "", "### Added", ""]
    lines += _bullets([Row((escape(name),)) for name in diff.added], max_rows)
    lines += ["### Removed (never truncated)", ""]
    lines += _bullets([Row((f"**{escape(name)}**",), True) for name in diff.removed], max_rows)
    lines += ["### Renamed", ""]
    renamed = [Row((escape(r.old), "->", escape(r.new), f"({r.reason})")) for r in diff.renamed]
    lines += _bullets(renamed, max_rows)
    lines += ["## Doses, durations, tolerance and bioavailability", ""]
    lines += _table(("Substance", "Route", "Field", "Old", "New", "Note"), diff.numbers, max_rows)
    lines += ["## Interactions", ""]
    titles = {
        Change.LOWERED: "### **LOWERED** interactions (never truncated)",
        Change.REMOVED: "### **REMOVED** interactions (never truncated)",
        Change.RAISED: "### Raised interactions",
        Change.ADDED: "### Added interactions",
    }
    for change in Change:
        lines += [titles[change], ""]
        lines += _table(("Substance", "With", "Old", "New"), diff.interactions[change], max_rows)
    lines += ["## Groups and cross tolerance", ""]
    lines += _table(("Where", "Change", "Substances"), diff.groups, max_rows)
    lines += ["## Categories and texts", ""]
    lines += ["Only whether a field changed, never its text.", ""]
    lines += _table(("Where", "Changed"), diff.flags, max_rows)
    return "\n".join(lines).rstrip("\n") + "\n"


# Command line

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_UNREADABLE = 2


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise ValueError(value)
    return number


def register(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``diff`` command to the command line."""
    parser = commands.add_parser(
        "diff",
        help="write the readable report of what changed between two datasets",
        description="Compare two datasets and write a Markdown report: substances added, "
        "removed and renamed, changed doses, durations, tolerance, bioavailability and "
        "units, interaction changes (lowered first), group membership changes, and which "
        "categories and texts changed. With --old-format base, OLD is the base file, "
        "normalized without API data. Exit code 0: written, 1: an input is not a valid "
        "dataset, 2: a file cannot be read or written.",
    )
    parser.add_argument("old", type=Path, help="the dataset before the change")
    parser.add_argument("new", type=Path, help="the dataset after the change")
    parser.add_argument(
        "--old-format",
        choices=("dataset", "base"),
        default="dataset",
        help="read OLD as a dataset or as the base file (default: %(default)s)",
    )
    parser.add_argument("--output", type=Path, help="write the report here instead of stdout")
    parser.add_argument("--old-label", help="how the report names OLD (default: its path)")
    parser.add_argument("--new-label", help="how the report names NEW (default: its path)")
    parser.add_argument(
        "--max-rows",
        type=_positive,
        default=DEFAULT_MAX_ROWS,
        help="rows per section before the rest is counted, not shown; rows a reviewer must "
        "see are always shown (default: %(default)s)",
    )


def run(arguments: argparse.Namespace) -> int:
    """Run the ``diff`` command and return its exit code."""
    old_path: Path = arguments.old
    new_path: Path = arguments.new
    try:
        if arguments.old_format == "base":
            old = load_base_dataset(old_path)
            old_label = arguments.old_label or f"{old_path} (base file, normalized)"
        else:
            old = load_dataset(old_path)
            old_label = arguments.old_label or str(old_path)
        new = load_dataset(new_path)
    except DiffInputError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except (DiffRefusedError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_REFUSED
    report = render(
        compare(old, new, versions=arguments.old_format != "base"),
        old_label=old_label,
        new_label=arguments.new_label or str(new_path),
        max_rows=arguments.max_rows,
    )
    output: Path | None = arguments.output
    if output is None:
        sys.stdout.write(report)
        return EXIT_OK
    if output.resolve() in (old_path.resolve(), new_path.resolve()):
        print(f"error: {output} is an input file: choose another output", file=sys.stderr)
        return EXIT_REFUSED
    temporary = output.with_name(f".{output.name}.partial")
    try:
        temporary.write_text(report, encoding="utf-8")
        os.replace(temporary, output)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        print(f"error: cannot write {output}: {error.strerror}", file=sys.stderr)
        return EXIT_UNREADABLE
    print(f"{output}: diff report of {old_label} and {arguments.new_label or new_path}")
    return EXIT_OK
