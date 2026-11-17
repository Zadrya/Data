# SPDX-License-Identifier: GPL-3.0-or-later
"""Bioavailability of one route, in percent.

Consistent means every bound is within 0 to 100 and the minimum is not above the
maximum. A block with one bound is kept.
"""

from zadrya_data.normalize.blocks import Candidate, Note
from zadrya_data.normalize.numbers import exact, is_usable, plain
from zadrya_data.normalize.report import Kind

type Bioavailability = dict[str, int | float]


def bioavailability(low: float | None, high: float | None) -> Candidate[Bioavailability]:
    """Return the bioavailability block one source offers."""
    if low is None and high is None:
        return Candidate()
    bounds = {"min": low, "max": high}
    for name, value in bounds.items():
        if value is not None and (not is_usable(value) or value > 100):
            return Candidate(problem=f"{name} {value:g} is not within 0 to 100")
    if low is not None and high is not None and low > high:
        return Candidate(problem=f"min {low:g} is above max {high:g}")
    return Candidate(
        {name: plain(exact(value)) for name, value in bounds.items() if value is not None}
    )


def changes(chosen: Bioavailability, base: Bioavailability) -> list[Note]:
    """Describe how the chosen API bioavailability differs from the base one, bound by bound.

    A bound both state with different values is a finding with its direction, and a bound
    the base states and the API block does not is a finding of its own.
    """
    notes: list[Note] = []
    for bound in ("min", "max"):
        if bound in base and bound not in chosen:
            notes.append(
                (
                    Kind.BIOAVAILABILITY_BOUND_NOT_IN_API,
                    f"{bound} {base[bound]:g} %, not in the API block",
                )
            )
            continue
        if bound not in chosen or bound not in base or chosen[bound] == base[bound]:
            continue
        old, new = base[bound], chosen[bound]
        direction = "lower" if new < old else "higher"
        notes.append((Kind.BIOAVAILABILITY_CHANGED, f"{bound} {old:g} to {new:g} %, {direction}"))
    return notes
