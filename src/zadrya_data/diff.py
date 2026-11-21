# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two datasets for the diff report.

``compare`` takes two datasets that ``check_dataset`` accepted and returns every
difference as rows of plain text (``diff_report`` escapes and lays them out). A row a
reviewer must never miss carries a ``Risk``: such a row is never left out, and the
report counts each kind at its top. ``compare`` is pure and deterministic: rows come
in the order of sorted names, the schema's route order and the field order below,
and nothing depends on the order of a set or a dict. The rules are in
``docs/adr/0008-diff-report.md``.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from zadrya_data.base import load_base
from zadrya_data.mediawiki import WikiPage
from zadrya_data.normalize import normalize
from zadrya_data.schema import SCHEMA_VERSION, SchemaName, load_schema, validate
from zadrya_data.snapshot import Snapshot
from zadrya_data.strict_json import loads

SEVERITIES = ("dangerous", "unsafe", "uncertain")
_RANK = {"uncertain": 1, "unsafe": 2, "dangerous": 3}
BOUNDARIES = ("thresholdMin", "lightMin", "commonMin", "strongMin", "heavyMin")
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
ABSENT = "none"
ALL_ROUTES = "all routes"


class DiffInputError(ValueError):
    """An input of the diff cannot be read: a file, its JSON or the base file format."""


class DiffRefusedError(ValueError):
    """An input of the diff is readable and is not a dataset that can be compared."""


class Risk(StrEnum):
    """A kind of change that a reviewer must never miss, in the order the report lists them."""

    LOWERED_INTERACTION = "Interactions lowered"
    REMOVED_INTERACTION = "Interactions removed"
    REMOVED_INTERACTION_MEMBER = "Members removed from interaction groups"
    REMOVED_GROUP = "Groups removed"
    REMOVED_SUBSTANCE = "Substances removed"
    RENAMED_SUBSTANCE = "Substances renamed"
    REMOVED_ROUTE = "Routes removed"
    CHANGED_UNITS = "Dose units changed"
    RISKY_DOSE = "Risky dose changes"
    RISKY_DURATION = "Risky duration changes"
    REMOVED_TOLERANCE = "Tolerance values removed"
    REMOVED_CROSS_TOLERANCE = "Cross tolerances removed"


class Change(StrEnum):
    """How an interaction changed between the two datasets."""

    LOWERED = "lowered"
    REMOVED = "removed"
    RAISED = "raised"
    ADDED = "added"


@dataclass(frozen=True, slots=True)
class Row:
    """One change, as plain text cells.

    ``risk`` marks a row that is never left out. ``group`` names the rows that are
    alike (same field, same kind of change), which the report may show together.
    ``added`` marks a row that only adds information, shown after the changes.
    """

    cells: tuple[str, ...]
    risk: Risk | None = None
    group: str = ""
    added: bool = False

    @property
    def protected(self) -> bool:
        """Whether the row is shown whatever the cap."""
        return self.risk is not None


@dataclass(frozen=True, slots=True)
class Rename:
    """A substance that has another name in the new dataset."""

    old: str
    new: str
    reason: str


@dataclass(slots=True)
class Diff:
    """Every difference between two datasets."""

    old_count: int
    new_count: int
    versions: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    hints: dict[str, str] = field(default_factory=dict)
    renamed: list[Rename] = field(default_factory=list)
    numbers: list[Row] = field(default_factory=list)
    interactions: dict[Change, list[Row]] = field(default_factory=dict)
    groups: list[Row] = field(default_factory=list)
    flags: list[Row] = field(default_factory=list)
    unflagged: int = 0

    def risks(self) -> dict[Risk, int]:
        """Return how many changes of each risk there are, leaving out the kinds with none."""
        rows = [*self.numbers, *self.groups, *(r for rs in self.interactions.values() for r in rs)]
        counts = Counter(row.risk for row in rows if row.risk is not None)
        counts[Risk.REMOVED_SUBSTANCE] = len(self.removed)
        counts[Risk.RENAMED_SUBSTANCE] = len(self.renamed)
        return {risk: counts[risk] for risk in Risk if counts[risk]}


# Loading


def _route_order() -> tuple[str, ...]:
    schema = load_schema(SchemaName.SUBSTANCES)
    return tuple(schema["$defs"]["roa"]["properties"]["route"]["enum"])


def check_dataset(document: object, where: str) -> dict[str, Any]:
    """Return the document if it is a valid dataset with unique names, or raise.

    The schema does not check that names and ids are unique; the diff matches by
    them, so it refuses a dataset where one repeats.
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

    The first dataset is compared with this, so that its review shows every change
    the API brought against the base file. The versions and the attribution of the
    result are placeholders: compare it with ``versions=False``.
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


# Substances


def _name_relation(old: dict[str, Any], new: dict[str, Any]) -> str | None:
    if old["name"].casefold() == new["name"].casefold():
        return "same name but for case"
    if old["name"].casefold() in {alias.casefold() for alias in new["aliases"]}:
        return f"{new['name']} lists {old['name']} as an alias"
    if new["name"].casefold() in {alias.casefold() for alias in old["aliases"]}:
        return f"{old['name']} listed {new['name']} as an alias"
    return None


def _match_renames(
    removed: list[dict[str, Any]], added: list[dict[str, Any]]
) -> tuple[list[Rename], dict[str, str]]:
    """Pair removed and added substances that are the same one under another name.

    When both have an address, only the same address makes a rename: a name or alias
    match at another address is only a hint next to the removed substance. Without
    an address on either side, a name or alias match is a rename. Either way a
    candidate counts only when the match is one to one.
    """
    candidates: dict[tuple[str, str], str] = {}
    hints: dict[str, str] = {}
    for old in removed:
        for new in added:
            relation = _name_relation(old, new)
            if old.get("url") and new.get("url"):
                if old["url"] == new["url"]:
                    candidates[old["name"], new["name"]] = relation or "same address"
                elif relation is not None:
                    hints.setdefault(
                        old["name"], f"possible rename: {relation}, at another address"
                    )
            elif relation is not None:
                candidates[old["name"], new["name"]] = relation
    renames = []
    for (old_name, new_name), reason in candidates.items():
        if (
            sum(o == old_name for o, _ in candidates)
            == 1
            == sum(n == new_name for _, n in candidates)
        ):
            renames.append(Rename(old_name, new_name, reason))
            hints.pop(old_name, None)
    return sorted(renames, key=lambda rename: (rename.new, rename.old)), hints


# Numbers


def _number(value: float | int) -> str:
    return repr(value) if isinstance(value, float) else str(value)


def _with_unit(value: float | int | None, unit: str) -> str:
    return ABSENT if value is None else f"{_number(value)} {unit}"


def _direction(old: float | int | None, new: float | int | None) -> str:
    if old is None:
        return "added"
    if new is None:
        return "removed"
    return "higher" if new > old else "lower"


def _dose_text(dose: dict[str, Any]) -> str:
    parts = [f"units {dose['units']}"]
    parts += [f"{key} {_number(dose[key])}" for key in BOUNDARIES if key in dose]
    return "; ".join(parts)


def _dose_rows(name: str, route: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    """Compare two dose blocks of a route; an empty dict is a route without a dose.

    A higher ``strongMin`` or ``heavyMin``, or a lost ``commonMin``, ``strongMin`` or
    ``heavyMin``, shows doses in a lower class than before (ADR 4): it is risky. A
    higher ``commonMin`` does the same for light and common doses and gets a note.
    When the units differ the numbers cannot be compared, so the whole block is one
    row.
    """
    if old and new and old["units"] != new["units"]:
        whole = (name, route, "dose", _dose_text(old), _dose_text(new), "units differ")
        return [Row(whole, Risk.CHANGED_UNITS)]
    rows = []
    unit = (old or new).get("units", "")
    if bool(old) != bool(new):
        direction = "added" if new else "removed"
        units: tuple[str, ...] = (old.get("units", ABSENT), new.get("units", ABSENT))
        rows.append(
            Row(
                (name, route, "dose units", *units, direction),
                group=f"dose units {direction}",
                added=bool(new),
            )
        )
    for boundary in BOUNDARIES:
        before, after = old.get(boundary), new.get(boundary)
        if before == after:
            continue
        direction = _direction(before, after)
        between = f"doses from {_number(before or 0)} to {_with_unit(after, unit)}"
        risk, note = None, direction
        if direction == "higher" and boundary in ("strongMin", "heavyMin"):
            risk, note = Risk.RISKY_DOSE, f"higher (risky: {between} now show in the class below)"
        elif direction == "removed" and boundary in ("commonMin", "strongMin", "heavyMin"):
            risk, note = Risk.RISKY_DOSE, "removed (risky: higher doses now show in a lower class)"
        elif direction == "higher" and boundary == "commonMin":
            note = f"higher (note: {between} now show in the class below)"
        cells = (name, route, f"dose {boundary}", _with_unit(before, unit), _with_unit(after, unit))
        rows.append(
            Row(
                (*cells, note),
                risk,
                group=f"dose {boundary} {direction}",
                added=direction == "added",
            )
        )
    return rows


def _range_rows(
    name: str,
    route: str,
    label: str,
    pair: tuple[dict[str, Any], dict[str, Any]],
    unit: str,
    risky: tuple[Risk, str] | None = None,
) -> list[Row]:
    """Compare the two bounds of a range. With ``risky``, a lower or removed bound is risky."""
    old, new = pair
    rows = []
    for bound in ("min", "max"):
        before, after = old.get(bound), new.get(bound)
        if before == after:
            continue
        direction = _direction(before, after)
        risk, note = None, direction
        if risky is not None and direction in ("lower", "removed"):
            risk, note = risky[0], f"{direction} (risky: {risky[1]})"
        cells = (name, route, f"{label} {bound}", _with_unit(before, unit), _with_unit(after, unit))
        rows.append(
            Row(
                (*cells, note),
                risk,
                group=f"{label} {direction}",
                added=direction == "added",
            )
        )
    return rows


def _route_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    route = old["route"]
    rows = _dose_rows(name, route, old.get("dose", {}), new.get("dose", {}))
    old_duration, new_duration = old.get("duration", {}), new.get("duration", {})
    shorter = (Risk.RISKY_DURATION, "the app shows a shorter timeline")
    for phase in PHASES:
        pair = (old_duration.get(phase, {}), new_duration.get(phase, {}))
        rows += _range_rows(name, route, f"duration {phase}", pair, "min", shorter)
    pair = (old.get("bioavailability", {}), new.get("bioavailability", {}))
    rows += _range_rows(name, route, "bioavailability", pair, "%")
    return rows


def _tolerance_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    """Compare tolerance texts and times. A value that disappears is never left out."""
    rows = []
    texts = [("full", old.get("full"), new.get("full"))]
    texts += [(t, old.get(t, {}).get("text"), new.get(t, {}).get("text")) for t in ("half", "zero")]
    for time, before, after in texts:
        if before != after:
            direction = "added" if before is None else "removed" if after is None else "changed"
            risk = Risk.REMOVED_TOLERANCE if direction == "removed" else None
            cells = (name, ALL_ROUTES, f"tolerance {time}", before or ABSENT, after or ABSENT)
            rows.append(
                Row(
                    (*cells, direction),
                    risk,
                    group=f"tolerance {time} {direction}",
                    added=direction == "added",
                )
            )
        if time != "full":
            pair = (old.get(time, {}), new.get(time, {}))
            for row in _range_rows(name, ALL_ROUTES, f"tolerance {time}", pair, "min"):
                removed = row.cells[5] == "removed"
                rows.append(
                    Row(
                        row.cells, Risk.REMOVED_TOLERANCE if removed else None, row.group, row.added
                    )
                )
    return rows


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
            rows.append(
                Row((name, route, "route", "present", ABSENT, "removed"), Risk.REMOVED_ROUTE)
            )
        elif route in new_routes:
            cells = (name, route, "route", ABSENT, "present", "added")
            rows.append(Row(cells, group="route added", added=True))
    rows += _tolerance_rows(name, old.get("tolerance", {}), new.get("tolerance", {}))
    return rows


# Interactions


type Pair = tuple[str, str, str]


def _interactions(document: dict[str, Any], rename: Callable[[str], str]) -> dict[Pair, str]:
    """Return the severity of every pair the dataset lists.

    Two catalog substances form one pair whichever of them lists the other, and the
    pair takes the higher severity, as the app reads it (ADR 5). A group or a target
    outside the catalog forms a pair with the substance that lists it. Groups are not
    expanded: membership changes are rows of their own.
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
    if kind == "group":
        return subject, f"group {target}"
    if kind == "other":
        return subject, f"other: {target}"
    return subject, target


def _interaction_rows(
    old: dict[str, Any], new: dict[str, Any], rename: Callable[[str], str]
) -> dict[Change, list[Row]]:
    before = _interactions(old, rename)
    after = _interactions(new, rename)
    rows: dict[Change, list[Row]] = {change: [] for change in Change}
    risks = {Change.LOWERED: Risk.LOWERED_INTERACTION, Change.REMOVED: Risk.REMOVED_INTERACTION}
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
        cells = (*_pair_cells(pair), was or ABSENT, now or ABSENT)
        rows[change].append(Row(cells, risks.get(change), added=change == Change.ADDED))
    return rows


# Groups and cross tolerance


def _group_rows(
    old: dict[str, Any], new: dict[str, Any], rename: Callable[[str], str]
) -> list[Row]:
    rows = []
    for key in GROUP_LISTS:
        interaction = key == "interactionGroups"
        label = "interaction group" if interaction else "cross tolerance group"
        lost = Risk.REMOVED_INTERACTION_MEMBER if interaction else Risk.REMOVED_CROSS_TOLERANCE
        before = {group["id"]: group for group in old[key]}
        after = {group["id"]: group for group in new[key]}
        for group_id in sorted(before.keys() | after.keys()):
            where = f"{label} {group_id}"
            if group_id not in after:
                members = sorted(rename(name) for name in before[group_id]["members"])
                rows.append(Row((where, "group removed", _names(members)), Risk.REMOVED_GROUP))
                continue
            if group_id not in before:
                members = sorted(after[group_id]["members"])
                rows.append(Row((where, "group added", _names(members)), added=True))
                continue
            if before[group_id]["name"] != after[group_id]["name"]:
                rows.append(Row((where, "name changed", "n/a")))
            old_members = {rename(name) for name in before[group_id]["members"]}
            new_members = set(after[group_id]["members"])
            if gone := sorted(old_members - new_members):
                rows.append(Row((where, "members removed", _names(gone)), lost))
            if joined := sorted(new_members - old_members):
                rows.append(Row((where, "members added", _names(joined)), added=True))
    return rows


def _names(names: list[str]) -> str:
    return ", ".join(names) or ABSENT


def _cross_tolerance_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    rows = []
    before, after = set(old["crossTolerances"]), set(new["crossTolerances"])
    where = f"substance {name}"
    if gone := sorted(before - after):
        cells = (where, "cross tolerance removed", _names(gone))
        rows.append(Row(cells, Risk.REMOVED_CROSS_TOLERANCE))
    if joined := sorted(after - before):
        rows.append(Row((where, "cross tolerance added", _names(joined)), added=True))
    return rows


# Categories and texts


def _flag(key: str, old: dict[str, Any], new: dict[str, Any]) -> str | None:
    if key not in old and key in new:
        return "added"
    if key in old and key not in new:
        return "removed"
    return "changed" if old.get(key) != new.get(key) else None


def _category_rows(old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    before = {category["id"]: category for category in old["categories"]}
    after = {category["id"]: category for category in new["categories"]}
    rows = []
    for category_id in sorted(before.keys() | after.keys()):
        where = f"category {category_id}"
        if category_id not in before or category_id not in after:
            status = "added" if category_id in after else "removed"
            rows.append(Row((where, f"category {status}"), group=f"category {status}"))
            continue
        for key in ("name", "description"):
            if change := _flag(key, before[category_id], after[category_id]):
                rows.append(Row((where, f"{key} {change}"), group=f"category {key} {change}"))
    return rows


def _flag_rows(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Row]:
    rows = []
    for key in FLAGGED_FIELDS:
        if change := _flag(key, old, new):
            rows.append(Row((f"substance {name}", f"{key} {change}"), group=f"{key} {change}"))
    return rows


# The whole comparison


def compare(old: dict[str, Any], new: dict[str, Any], *, versions: bool = True) -> Diff:
    """Return every difference between two datasets that ``check_dataset`` accepted.

    With ``versions`` false, the versions and the attribution are not compared: the
    old side is the normalized base file, whose values for them are placeholders.
    """
    routes = _route_order()
    old_by_name = {substance["name"]: substance for substance in old["substances"]}
    new_by_name = {substance["name"]: substance for substance in new["substances"]}
    gone = [old_by_name[name] for name in sorted(old_by_name.keys() - new_by_name.keys())]
    fresh = [new_by_name[name] for name in sorted(new_by_name.keys() - old_by_name.keys())]
    renames, hints = _match_renames(gone, fresh)
    new_name = {rename.old: rename.new for rename in renames}

    def rename(name: str) -> str:
        return new_name.get(name, name)

    diff = Diff(old_count=len(old_by_name), new_count=len(new_by_name), renamed=renames)
    diff.hints = hints
    for key in ("schemaVersion", "datasetVersion") if versions else ():
        if old[key] != new[key]:
            diff.versions.append(f"{key}: {old[key]} -> {new[key]}")
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
        diff.numbers += _number_rows(name, before, after, routes)
        diff.groups += _cross_tolerance_rows(name, before, after)
        flags = _flag_rows(name, before, after)
        diff.flags += flags
        diff.unflagged += not flags
    diff.interactions = _interaction_rows(old, new, rename)
    return diff
