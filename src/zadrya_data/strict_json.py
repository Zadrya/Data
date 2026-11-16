# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict JSON parsing: only what RFC 8259 allows, and nothing that hides data.

``json.loads`` is lenient in ways that matter for a dataset that is hashed, signed
and read by another JSON implementation: it accepts ``NaN`` and ``Infinity``, turns
a number such as ``1e999`` into infinity, reads integers of any size (which other
parsers round or read as infinity), and keeps the last value when an object repeats
a key. ``loads`` here rejects all of them, and reports nesting that is too deep as
an error instead of a ``RecursionError``.
"""

import json
import math

# Largest integer that an IEEE 754 double, the number type of most JSON parsers,
# represents exactly together with all smaller ones.
MAX_SAFE_INTEGER = 2**53 - 1


class StrictJsonError(ValueError):
    """The text is not JSON that this project accepts."""


def _reject_constant(constant: str) -> object:
    raise StrictJsonError(f"{constant} is not a JSON number")


def _finite_float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise StrictJsonError(f"the number {text} is out of range")
    return number


def _safe_integer(text: str) -> int:
    try:
        number = int(text)
    except ValueError as error:  # more digits than Python converts by default
        raise StrictJsonError("an integer has too many digits") from error
    if abs(number) > MAX_SAFE_INTEGER:
        raise StrictJsonError(f"the integer {text} is outside the safe range of a double")
    return number


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise StrictJsonError(f"the key '{key}' appears twice in one object")
        document[key] = value
    return document


def loads(text: str) -> object:
    """Parse JSON text, or raise ``StrictJsonError`` with the reason."""
    try:
        document: object = json.loads(
            text,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            parse_int=_safe_integer,
            object_pairs_hook=_unique_keys,
        )
    except StrictJsonError:
        raise
    except RecursionError as error:
        raise StrictJsonError("the document is nested too deeply") from error
    except ValueError as error:
        raise StrictJsonError(f"not valid JSON: {error}") from error
    return document
