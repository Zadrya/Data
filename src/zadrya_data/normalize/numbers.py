# SPDX-License-Identifier: GPL-3.0-or-later
"""How numbers are computed and written, so the output has no floating point noise.

Every number is handled as an exact fraction made from the shortest decimal text of
the source value (``15.0`` is 15, ``0.1`` is one tenth, not the nearest binary
double). Conversions multiply or divide those fractions exactly. A converted value is
then rounded to four decimal places, half to even, which is finer than any value the
sources state. A number is written as an integer when it is whole and as the shortest
decimal otherwise, so 45 seconds is ``0.75`` minutes and 15.0 is ``15``.
"""

import math
from fractions import Fraction

DECIMAL_PLACES = 4


def is_usable(value: float) -> bool:
    """Tell whether a source number is finite and not negative."""
    return math.isfinite(value) and value >= 0


def exact(value: float) -> Fraction:
    """Return the value as the fraction its shortest decimal text states."""
    return Fraction(str(value))


def rounded(value: Fraction) -> Fraction:
    """Round to four decimal places, half to even."""
    return Fraction(round(value, DECIMAL_PLACES))


def plain(value: Fraction) -> int | float:
    """Return the number as it is written: an integer when whole, else a float."""
    if value.denominator == 1:
        return value.numerator
    return float(value)
