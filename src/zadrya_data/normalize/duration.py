# SPDX-License-Identifier: GPL-3.0-or-later
"""Duration phases of one route, converted to minutes.

Each phase (onset, comeup, peak, offset, total, afterglow) is a block of its own: it
comes whole from the API or whole from the base file. Units are matched without case
and in singular or plural (``Hours``, ``hour``): seconds divide by 60, minutes stay,
hours multiply by 60 and days by 1440. A phase with numbers and a missing or unknown
unit is inconsistent, and so is a negative number or a minimum above the maximum. A
phase with one bound is kept. Converted values follow ``numbers``: exact arithmetic,
then four decimal places.
"""

from fractions import Fraction

from zadrya_data.normalize.blocks import Candidate, Note
from zadrya_data.normalize.numbers import exact, is_usable, plain, rounded
from zadrya_data.normalize.report import Kind

PHASES = ("onset", "comeup", "peak", "offset", "total", "afterglow")

_MINUTES_PER_UNIT = {
    "second": Fraction(1, 60),
    "seconds": Fraction(1, 60),
    "minute": Fraction(1),
    "minutes": Fraction(1),
    "hour": Fraction(60),
    "hours": Fraction(60),
    "day": Fraction(1440),
    "days": Fraction(1440),
}

type Phase = dict[str, int | float]


def phase(low: float | None, high: float | None, units: str | None) -> Candidate[Phase]:
    """Return one phase in minutes, as a candidate for the merge policy."""
    if low is None and high is None:
        return Candidate()
    factor = _MINUTES_PER_UNIT.get(units.strip().casefold()) if units is not None else None
    if factor is None:
        shown = "no unit" if units is None else f"the unknown unit '{units}'"
        return Candidate(problem=f"numbers with {shown}")
    bounds = {"min": low, "max": high}
    for name, value in bounds.items():
        if value is not None and not is_usable(value):
            return Candidate(problem=f"{name} is negative or not finite")
    if low is not None and high is not None and low > high:
        return Candidate(problem=f"min {low:g} is above max {high:g} {units}")

    result: Phase = {}
    notes: list[Note] = []
    for name, value in bounds.items():
        if value is None:
            continue
        minutes = exact(value) * factor
        kept = rounded(minutes)
        if kept != minutes:
            notes.append(
                (
                    Kind.DURATION_ROUNDED,
                    f"{name} {value:g} {units} is {plain(kept)} minutes after rounding",
                )
            )
        result[name] = plain(kept)
    return Candidate(result, notes=tuple(notes))


def changes(phase_name: str, chosen: Phase, base: Phase) -> list[Note]:
    """Describe how the chosen API phase differs from the base phase, bound by bound.

    A bound the base states and the API phase does not is a finding of its own.
    """
    notes: list[Note] = []
    for bound in ("min", "max"):
        if bound in base and bound not in chosen:
            notes.append(
                (
                    Kind.DURATION_BOUND_NOT_IN_API,
                    f"{phase_name} {bound} {base[bound]:g} minutes, not in the API phase",
                )
            )
            continue
        if bound not in chosen or bound not in base or chosen[bound] == base[bound]:
            continue
        old, new = base[bound], chosen[bound]
        direction = "lower" if new < old else "higher"
        notes.append(
            (Kind.DURATION_CHANGED, f"{phase_name} {bound} {old:g} to {new:g} minutes, {direction}")
        )
    return notes
