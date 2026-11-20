# SPDX-License-Identifier: GPL-3.0-or-later
"""Invariants of a built dataset: the cross-field rules the schema cannot express.

This is a second, independent check over the output of the build. It reads the
finished document only, imports nothing from ``normalize``, and does not trust that
normalization already enforced a rule: a rule here may repeat one there on purpose.
It assumes a document that the schema accepts (the build validates the schema
first), and it never changes the document.

Each rule is a function in ``RULES`` that yields every place where the document
breaks it, naming the substance (``None`` for the catalog lists) and the field.
``check`` returns all failures of all rules, sorted; ``require`` raises
``InvariantError`` with all of them, not just the first. The rules and why they
hold are in ``docs/adr/0007-invariants-and-build.md``.
"""

import math
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

# The five dose boundaries, from the lowest to the highest (ADR 1).
BOUNDARIES = ("thresholdMin", "lightMin", "commonMin", "strongMin", "heavyMin")
SEVERITIES = ("dangerous", "unsafe", "uncertain")
# The three spellings of a mass unit that the app may convert between (ADR 1).
MASS_UNITS = frozenset({"µg", "mg", "g"})
# Other spellings of a mass unit, after NFKC (which turns the micro sign into the Greek
# mu) and case folding. A unit written this way would look convertible to a reader
# and be opaque to the app, so it is refused instead of being guessed.
_MASS_SPELLINGS = frozenset(
    {
        "μg",
        "ug",
        "mcg",
        "mg",
        "mgs",
        "g",
        "gs",
        "kg",
        "microgram",
        "micrograms",
        "milligram",
        "milligrams",
        "gram",
        "grams",
        "kilogram",
        "kilograms",
    }
)
_GREEK_MU = "μ"

type Document = Mapping[str, Any]


@dataclass(frozen=True, slots=True, order=True)
class Failure:
    """One place where the document breaks one rule."""

    rule: str
    substance: str | None
    field: str
    detail: str

    def __str__(self) -> str:
        where = self.substance if self.substance is not None else "(catalog)"
        return f"{where}: {self.field}: {self.detail} ({self.rule})"


class InvariantError(ValueError):
    """The dataset breaks at least one invariant. ``failures`` lists every one."""

    def __init__(self, failures: list[Failure]) -> None:
        self.failures = failures
        lines = "".join(f"\n  {failure}" for failure in failures)
        super().__init__(f"the dataset breaks its invariants in {len(failures)} place(s):{lines}")


def _substances(document: Document) -> list[dict[str, Any]]:
    substances: list[dict[str, Any]] = document["substances"]
    return substances


def _route_field(route: Mapping[str, Any], rest: str) -> str:
    return f"roas[{route['route']}].{rest}"


def _dose_order(document: Document) -> Iterator[Failure]:
    """Dose boundaries never decrease: equal neighbours are allowed (ADR 4)."""
    for substance in _substances(document):
        for route in substance["roas"]:
            dose = route.get("dose", {})
            present = [(key, dose[key]) for key in BOUNDARIES if key in dose]
            for (low_key, low), (key, value) in zip(present, present[1:]):
                if value < low:
                    yield Failure(
                        "dose-order",
                        substance["name"],
                        _route_field(route, f"dose.{key}"),
                        f"{value} is below {low_key} {low}",
                    )


def _ranges(document: Document) -> Iterator[Failure]:
    """Every min is at most its max: duration phases, bioavailability, tolerance times."""
    for substance in _substances(document):
        blocks: list[tuple[str, Mapping[str, Any]]] = []
        for route in substance["roas"]:
            for phase, block in route.get("duration", {}).items():
                blocks.append((_route_field(route, f"duration.{phase}"), block))
            if "bioavailability" in route:
                blocks.append((_route_field(route, "bioavailability"), route["bioavailability"]))
        for time in ("half", "zero"):
            if time in substance.get("tolerance", {}):
                blocks.append((f"tolerance.{time}", substance["tolerance"][time]))
        for field, block in blocks:
            if "min" in block and "max" in block and block["min"] > block["max"]:
                yield Failure(
                    "range",
                    substance["name"],
                    field,
                    f"min {block['min']} is above max {block['max']}",
                )


def _targets(substance: Mapping[str, Any]) -> Iterator[tuple[str, dict[str, str]]]:
    for severity in SEVERITIES:
        for target in substance["interactions"][severity]:
            yield severity, target


def _target_exists(document: Document) -> Iterator[Failure]:
    """A substance target is another substance of the catalog."""
    names = {substance["name"] for substance in _substances(document)}
    for substance in _substances(document):
        for severity, target in _targets(substance):
            if target["kind"] != "substance":
                continue
            field = f"interactions.{severity}"
            if target["name"] == substance["name"]:
                detail = f"'{target['name']}' is the substance itself"
                yield Failure("target-exists", substance["name"], field, detail)
            elif target["name"] not in names:
                detail = f"'{target['name']}' is not a substance of the catalog"
                yield Failure("target-exists", substance["name"], field, detail)


def _target_unique(document: Document) -> Iterator[Failure]:
    """A target appears once across the three severities (``other`` without case)."""
    for substance in _substances(document):
        seen: dict[tuple[str, str], str] = {}
        for severity, target in _targets(substance):
            value = target.get("groupId") or target["name"]
            key = (target["kind"], value.casefold() if target["kind"] == "other" else value)
            if key in seen:
                yield Failure(
                    "target-unique",
                    substance["name"],
                    f"interactions.{severity}",
                    f"the {target['kind']} target '{value}' is also listed as {seen[key]}",
                )
            else:
                seen[key] = severity


def _interaction_symmetric(document: Document) -> Iterator[Failure]:
    """When A lists the substance B, B lists A with the same severity."""
    by_name = {substance["name"]: substance for substance in _substances(document)}
    severity_of: dict[tuple[str, str], str] = {}
    for substance in _substances(document):
        for severity, target in _targets(substance):
            if target["kind"] == "substance":
                severity_of.setdefault((substance["name"], target["name"]), severity)
    for (name, other), severity in severity_of.items():
        if other == name or other not in by_name:
            continue  # target-exists reports these
        back = severity_of.get((other, name))
        if back is None:
            detail = f"lists '{other}', and '{other}' does not list it"
        elif back != severity:
            detail = f"lists '{other}', and '{other}' lists it as {back}"
        else:
            continue
        yield Failure("interaction-symmetric", name, f"interactions.{severity}", detail)


def _group_exists(document: Document) -> Iterator[Failure]:
    """A group target names an entry of ``interactionGroups``."""
    ids = {group["id"] for group in document["interactionGroups"]}
    for substance in _substances(document):
        for severity, target in _targets(substance):
            if target["kind"] == "group" and target["groupId"] not in ids:
                yield Failure(
                    "group-exists",
                    substance["name"],
                    f"interactions.{severity}",
                    f"'{target['groupId']}' is not an entry of interactionGroups",
                )


def _member_exists(document: Document) -> Iterator[Failure]:
    """Every member of a group is a substance of the catalog."""
    names = {substance["name"] for substance in _substances(document)}
    for key in ("interactionGroups", "crossToleranceGroups"):
        for group in document[key]:
            for member in group["members"]:
                if member not in names:
                    yield Failure(
                        "member-exists",
                        None,
                        f"{key}[{group['id']}].members",
                        f"'{member}' is not a substance of the catalog",
                    )


def _cross_tolerance(document: Document) -> Iterator[Failure]:
    """A substance lists exactly the cross tolerance groups it is a member of."""
    members = {group["id"]: set(group["members"]) for group in document["crossToleranceGroups"]}
    listed = {
        substance["name"]: substance["crossTolerances"] for substance in _substances(document)
    }
    for name, ids in listed.items():
        for group_id in ids:
            if group_id not in members:
                detail = f"'{group_id}' is not an entry of crossToleranceGroups"
            elif name not in members[group_id]:
                detail = f"lists '{group_id}' and is not one of its members"
            else:
                continue
            yield Failure("cross-tolerance", name, "crossTolerances", detail)
    for group_id, names in members.items():
        for name in sorted(names):
            if name in listed and group_id not in listed[name]:
                yield Failure(
                    "cross-tolerance",
                    name,
                    "crossTolerances",
                    f"is a member of '{group_id}' and does not list it",
                )


def _category_exists(document: Document) -> Iterator[Failure]:
    """A substance's categories are entries of ``categories``."""
    ids = {category["id"] for category in document["categories"]}
    for substance in _substances(document):
        for category in substance["categories"]:
            if category not in ids:
                yield Failure(
                    "category-exists",
                    substance["name"],
                    "categories",
                    f"'{category}' is not an entry of categories",
                )


def _unique_id(document: Document) -> Iterator[Failure]:
    """Ids are unique within ``categories`` and within each group list."""
    for key in ("categories", "interactionGroups", "crossToleranceGroups"):
        counts = Counter(entry["id"] for entry in document[key])
        for entry_id, count in sorted(counts.items()):
            if count > 1:
                yield Failure("unique-id", None, key, f"the id '{entry_id}' appears {count} times")


def _unique_name(document: Document) -> Iterator[Failure]:
    """Canonical names are unique without case."""
    first: dict[str, str] = {}
    for substance in _substances(document):
        name = substance["name"]
        folded = name.casefold()
        if folded in first:
            detail = f"'{name}' is also the name of '{first[folded]}' (without case)"
            yield Failure("unique-name", name, "name", detail)
        else:
            first[folded] = name


def _unique_alias(document: Document) -> Iterator[Failure]:
    """An alias leads to exactly one substance: no other name, no other holder, no repeat."""
    names = {substance["name"].casefold(): substance["name"] for substance in _substances(document)}
    holders: dict[str, list[str]] = defaultdict(list)
    for substance in _substances(document):
        for alias in substance["aliases"]:
            holders[alias.casefold()].append(substance["name"])
    for substance in _substances(document):
        name = substance["name"]
        for alias in substance["aliases"]:
            folded = alias.casefold()
            others = sorted({holder for holder in holders[folded] if holder != name})
            if names.get(folded) == name:
                detail = f"'{alias}' is the substance's own name"
            elif folded in names:
                detail = f"'{alias}' is the name of '{names[folded]}'"
            elif others:
                detail = f"'{alias}' is also an alias of {', '.join(others)}"
            elif holders[folded].count(name) > 1:
                detail = f"'{alias}' appears more than once (without case)"
            else:
                continue
            yield Failure("unique-alias", name, "aliases", detail)


def _alias_not_group(document: Document) -> Iterator[Failure]:
    """No alias is, without case, the name or id of a group."""
    groups: dict[str, str] = {}
    for key in ("interactionGroups", "crossToleranceGroups"):
        for group in document[key]:
            for label in (group["id"], group["name"]):
                groups.setdefault(label.casefold(), f"{key}[{group['id']}]")
    for substance in _substances(document):
        for alias in substance["aliases"]:
            if alias.casefold() in groups:
                yield Failure(
                    "alias-not-group",
                    substance["name"],
                    "aliases",
                    f"'{alias}' is the name or id of the group {groups[alias.casefold()]}",
                )


def _repeats(values: list[Any]) -> list[Any]:
    counts = Counter(values)
    return [value for value in counts if counts[value] > 1]


def _unique_items(document: Document) -> Iterator[Failure]:
    """No list holds the same item twice: routes, categories, texts, group members."""
    for substance in _substances(document):
        lists: dict[str, list[Any]] = {
            "roas": [route["route"] for route in substance["roas"]],
            "categories": substance["categories"],
            "classes.psychoactive": substance["classes"]["psychoactive"],
            "classes.chemical": substance["classes"]["chemical"],
            "crossTolerances": substance["crossTolerances"],
            "toxicities": substance["toxicities"],
            "saferUse": substance.get("saferUse", []),
        }
        for field, values in lists.items():
            for value in _repeats(values):
                yield Failure(
                    "unique-items", substance["name"], field, f"'{value}' appears more than once"
                )
    for key in ("interactionGroups", "crossToleranceGroups"):
        for group in document[key]:
            for value in _repeats(group["members"]):
                yield Failure(
                    "unique-items",
                    None,
                    f"{key}[{group['id']}].members",
                    f"'{value}' appears more than once",
                )


def _mass_unit(document: Document) -> Iterator[Failure]:
    """A mass unit is written µg (micro sign), mg or g; every other unit stays opaque."""
    for substance in _substances(document):
        for route in substance["roas"]:
            if "dose" not in route:
                continue
            units: str = route["dose"]["units"]
            if _GREEK_MU in units:
                detail = (
                    f"'{units}' holds the Greek letter mu (U+03BC): micrograms are written "
                    "with the micro sign (U+00B5)"
                )
            elif (
                units not in MASS_UNITS
                and unicodedata.normalize("NFKC", units).casefold().strip() in _MASS_SPELLINGS
            ):
                detail = f"'{units}' spells a mass unit another way: write µg, mg or g"
            else:
                continue
            yield Failure("mass-unit", substance["name"], _route_field(route, "dose.units"), detail)


def _numbers(value: Any, field: str) -> Iterator[tuple[str, float]]:
    if isinstance(value, float):
        yield field, value
    elif isinstance(value, Mapping):
        for key, inner in value.items():
            yield from _numbers(inner, f"{field}.{key}" if field else key)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            label = inner["route"] if field == "roas" else index
            yield from _numbers(inner, f"{field}[{label}]")


def _finite(document: Document) -> Iterator[Failure]:
    """No number is NaN or infinite."""
    for key, value in document.items():
        items = value if key == "substances" else [None]
        for substance in items:
            where = substance if substance is not None else {key: value}
            name = substance["name"] if substance is not None else None
            for field, number in _numbers(where, ""):
                if not math.isfinite(number):
                    yield Failure("finite", name, field, f"{number} is not a finite number")


RULES: dict[str, Callable[[Document], Iterator[Failure]]] = {
    "dose-order": _dose_order,
    "range": _ranges,
    "target-exists": _target_exists,
    "target-unique": _target_unique,
    "interaction-symmetric": _interaction_symmetric,
    "group-exists": _group_exists,
    "member-exists": _member_exists,
    "cross-tolerance": _cross_tolerance,
    "category-exists": _category_exists,
    "unique-id": _unique_id,
    "unique-name": _unique_name,
    "unique-alias": _unique_alias,
    "alias-not-group": _alias_not_group,
    "unique-items": _unique_items,
    "mass-unit": _mass_unit,
    "finite": _finite,
}


def check(document: Document) -> list[Failure]:
    """Return every failure of every rule, sorted by rule, substance and field."""
    found = [failure for rule in RULES.values() for failure in rule(document)]
    return sorted(found, key=lambda f: (f.rule, f.substance or "", f.field, f.detail))


def require(document: Document) -> None:
    """Raise ``InvariantError`` with every failure, unless the document breaks no rule."""
    failures = check(document)
    if failures:
        raise InvariantError(failures)
