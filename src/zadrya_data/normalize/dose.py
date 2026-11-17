# SPDX-License-Identifier: GPL-3.0-or-later
"""Dose boundaries of one route, from the API or from the base file.

The dataset stores five boundaries: ``thresholdMin``, ``lightMin``, ``commonMin``,
``strongMin`` and ``heavyMin``.

From the API, each boundary is the value the API states for it: ``threshold``,
``light.min``, ``common.min``, ``strong.min`` and ``heavy``. Range maxima are not
stored, with one exception: when the API does not state a boundary, it is filled from
the maximum of the range just below it (``heavyMin`` from ``strong.max``,
``strongMin`` from ``common.max``, ``commonMin`` from ``light.max``). Without the fill
a route that has a strong range and no ``heavy`` value would never show a dose as
heavy, however large. A fill is used only when the direct value is absent, never
across more than one step, and is dropped again if it would break the order.

From the base file, ``thresholdMin`` is the base ``lightMin`` (the convention of the
Journal app, see ADR 0001), ``lightMin`` is absent and the other three are as named.

One thing, and only one, crosses from one source to the other: a unit qualifier. The
base file writes the doses of Cannabis in ``mg THC`` and of Psilocybin mushrooms in
``mg Psilocybin``, because the numbers are milligrams of the active compound, not of
the material a user weighs; the API writes plain ``mg``. Plain ``mg`` is a mass unit
the app may convert, so half a gram of flower would be compared with 10 mg and shown
as far beyond heavy. When the API block is the one chosen and the base unit is exactly
the API unit, one space and a qualifier, the dose takes the base unit. No number ever
crosses.

A block is consistent when it has units, every API range has its minimum at or below
its maximum, every boundary is finite and not negative, and the boundaries do not
decrease in the order above (equal neighbours are allowed and reported).
"""

from fractions import Fraction

from zadrya_data.base import BaseDose
from zadrya_data.graphql import ApiDose, ApiRange
from zadrya_data.normalize import text
from zadrya_data.normalize.blocks import Candidate, Note
from zadrya_data.normalize.numbers import exact, is_usable, plain
from zadrya_data.normalize.report import Kind

BOUNDARIES = ("thresholdMin", "lightMin", "commonMin", "strongMin", "heavyMin")
MASS_UNITS = ("µg", "mg", "g")
GREEK_MU = "μ"
MICRO_SIGN = "µ"

type Dose = dict[str, int | float | str]


def _qualified(units: str, base_units: str | None) -> str | None:
    """Return the base unit when it is the given unit, one space and a qualifier."""
    if base_units is None:
        return None
    candidate = text.line(text.strip(base_units).replace(GREEK_MU, MICRO_SIGN))
    if candidate is None or not candidate.startswith(units + " "):
        return None
    qualifier = candidate[len(units) + 1 :]
    return candidate if qualifier == qualifier.strip() else None


def _units(raw: str | None, qualifier_from: str | None = None) -> tuple[str | None, list[Note]]:
    """Return the cleaned units, or ``None`` when there are none or they are not valid text."""
    if raw is None:
        return None, []
    notes: list[Note] = []
    stripped = text.strip(raw)
    if GREEK_MU in stripped:
        notes.append((Kind.UNIT_REPAIRED, f"units '{stripped}' written with the Greek letter mu"))
        stripped = stripped.replace(GREEK_MU, MICRO_SIGN)
    units = text.line(stripped)
    qualified = _qualified(units, qualifier_from) if units is not None else None
    if units is not None and qualified is not None:
        notes.append(
            (
                Kind.UNIT_QUALIFIED,
                f"the API units '{units}' become the base units '{qualified}': the numbers "
                "refer to what the qualifier names",
            )
        )
        units = qualified
    if units is not None and units not in MASS_UNITS:
        notes.append((Kind.UNIT_NOT_MASS, f"units '{units}' are not a mass unit"))
    return units, notes


def _decreases(values: dict[str, float]) -> str | None:
    """Return a description of the first place where the boundaries decrease, if any."""
    present = [(name, values[name]) for name in BOUNDARIES if name in values]
    for (lower, low), (upper, high) in zip(present, present[1:]):
        if low > high:
            return f"{lower} {low:g} is above {upper} {high:g}"
    return None


def _equal_neighbours(values: dict[str, float]) -> list[str]:
    present = [(name, values[name]) for name in BOUNDARIES if name in values]
    return [
        f"{lower} and {upper} are both {low:g}"
        for (lower, low), (upper, high) in zip(present, present[1:])
        if low == high
    ]


def _candidate(
    raw_units: str | None,
    direct: dict[str, float | None],
    fills: dict[str, tuple[str, float | None]],
    extra_notes: list[Note],
    qualifier_from: str | None = None,
) -> Candidate[Dose]:
    values = {name: value for name, value in direct.items() if value is not None}
    units, notes = _units(raw_units, qualifier_from)
    if not values and not any(value is not None for _, value in fills.values()):
        if units is None:
            return Candidate()
        return Candidate({"units": units}, notes=tuple(notes), weak=True)

    unusable = [name for name, value in values.items() if not is_usable(value)]
    if unusable:
        return Candidate(problem=f"{unusable[0]} is negative or not finite")
    problem = _decreases(values)
    if problem is not None:
        return Candidate(problem=problem)
    if units is None:
        return Candidate(problem="boundaries without usable units")

    for name, (source, value) in fills.items():
        if name in values or value is None:
            continue
        trial = values | {name: value}
        reason = None if is_usable(value) else "it is negative or not finite"
        reason = reason or _decreases(trial)
        if reason is not None:
            notes.append(
                (
                    Kind.DOSE_FILL_DISCARDED,
                    f"{name} is not filled from {source} {value:g}: {reason}",
                )
            )
            continue
        values = trial
        notes.append((Kind.DOSE_BOUNDARY_FILLED, f"{name} {value:g} filled from {source}"))

    equal = _equal_neighbours(values)
    if equal:
        notes.append((Kind.DOSE_EQUAL_BOUNDARIES, "; ".join(equal)))
    dose: Dose = {"units": units}
    for name in BOUNDARIES:
        if name in values:
            dose[name] = plain(Fraction(exact(values[name])))
    return Candidate(dose, notes=tuple([*notes, *extra_notes]))


def _bound(item: ApiRange | None, which: str) -> float | None:
    if item is None:
        return None
    return item.min if which == "min" else item.max


def _inverted_range(dose: ApiDose) -> str | None:
    """Return a description of the first API range whose minimum is above its maximum."""
    for name, item in (("light", dose.light), ("common", dose.common), ("strong", dose.strong)):
        if item is not None and item.min is not None and item.max is not None:
            if item.min > item.max:
                return f"{name}.min {item.min:g} is above {name}.max {item.max:g}"
    return None


def from_api(dose: ApiDose | None, base: BaseDose | None) -> Candidate[Dose]:
    """Return the dose block the API offers. The base block is read for its units and reports.

    A range whose minimum is above its maximum makes the whole block inconsistent before
    anything is mapped or filled: its numbers cannot be trusted for either purpose.
    """
    if dose is None:
        return Candidate()
    inverted = _inverted_range(dose)
    if inverted is not None:
        return Candidate(problem=inverted)
    direct = {
        "thresholdMin": dose.threshold,
        "lightMin": _bound(dose.light, "min"),
        "commonMin": _bound(dose.common, "min"),
        "strongMin": _bound(dose.strong, "min"),
        "heavyMin": dose.heavy,
    }
    fills = {
        "commonMin": ("light.max", _bound(dose.light, "max")),
        "strongMin": ("common.max", _bound(dose.common, "max")),
        "heavyMin": ("strong.max", _bound(dose.strong, "max")),
    }
    extra: list[Note] = []
    light = direct["lightMin"]
    if dose.threshold is None and light is not None and base is not None:
        if base.light_min is not None:
            extra.append(
                (
                    Kind.DOSE_LABEL_DIFFERS,
                    f"the API has no threshold and a light minimum of {light:g}, stored as "
                    f"lightMin; the base file calls {base.light_min:g} the threshold",
                )
            )
    return _candidate(dose.units, direct, fills, extra, base.units if base else None)


def from_base(dose: BaseDose | None) -> Candidate[Dose]:
    """Return the dose block the base file offers."""
    if dose is None:
        return Candidate()
    direct = {
        "thresholdMin": dose.light_min,
        "commonMin": dose.common_min,
        "strongMin": dose.strong_min,
        "heavyMin": dose.heavy_min,
    }
    return _candidate(dose.units, direct, {}, [])


UPPER_BOUNDARIES = ("commonMin", "strongMin", "heavyMin")


def require_upper_boundaries(api: Candidate[Dose], base: Candidate[Dose]) -> Candidate[Dose]:
    """Reject an API block that lacks an upper boundary the consistent base block has.

    Losing ``commonMin``, ``strongMin`` or ``heavyMin`` is the unsafe direction: larger
    doses would be shown in a lower class. A complete base block is preferred to a
    truncated API block, even when the base is older. Differences in ``thresholdMin``
    and ``lightMin`` are not checked here; they are reported as label differences.
    """
    if api.value is None or api.weak or base.value is None or base.weak:
        return api
    missing = [name for name in UPPER_BOUNDARIES if name in base.value and name not in api.value]
    if not missing:
        return api
    return Candidate(problem=f"missing upper boundaries the base has ({', '.join(missing)})")


def lost_upper_boundaries(base: Candidate[Dose], chosen: Dose | None) -> list[str]:
    """Return the upper boundaries of a consistent base block that the chosen dose lacks."""
    if base.value is None or base.weak:
        return []
    return [name for name in UPPER_BOUNDARIES if name in base.value and name not in (chosen or {})]
