# SPDX-License-Identifier: GPL-3.0-or-later
"""Bioavailability of one route, in percent.

Consistent means every bound is within 0 to 100 and the minimum is not above the
maximum. A block with one bound is kept.
"""

from zadrya_data.normalize.blocks import Candidate
from zadrya_data.normalize.numbers import exact, is_usable, plain

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
