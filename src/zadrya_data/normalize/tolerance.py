# SPDX-License-Identifier: GPL-3.0-or-later
"""The tolerance timeline of one substance.

``full``, ``half`` and ``zero`` are three independent facts, so each is taken on its
own: the API text when it is present and not empty, otherwise the base text. Using
the base text is reported, and so is every case where both sources have a text and
the texts differ. Text that is not valid after stripping is reported and treated as
absent.

``full`` stays free text. ``half`` and ``zero`` are ``{text, min, max}``: the wording
of the wiki and, when it reads as a time ("5 days", "3 - 7 days", "1-1.5 months",
"2 weeks"), the same as a range in minutes. A minute is 1, an hour 60, a day 1440, a
week 10080 and a month 30 days (43200): never a calendar month, so the same text
always gives the same number. A wording that does not read as a time keeps its text
without numbers and is reported.
"""

import re
from fractions import Fraction
from typing import Any

from zadrya_data.base import BaseSubstance
from zadrya_data.graphql import ApiSubstance
from zadrya_data.normalize import text
from zadrya_data.normalize.numbers import plain, rounded
from zadrya_data.normalize.report import Kind, Report

MINUTES_PER_UNIT = {
    "minute": Fraction(1),
    "hour": Fraction(60),
    "day": Fraction(1440),
    "week": Fraction(10080),
    "month": Fraction(43200),
}

# A number, optionally a hyphen and a second number, then a unit in singular or plural.
_TIME = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)(?:\s*-\s*(?P<high>\d+(?:\.\d+)?))?\s*"
    r"(?P<unit>minute|hour|day|week|month)s?",
    re.IGNORECASE | re.ASCII,
)

FIELDS = ("full", "half", "zero")


def minutes(wording: str) -> tuple[int | float, int | float] | None:
    """Return the wording as a range in minutes, or ``None`` when it is not a time."""
    match = _TIME.fullmatch(wording)
    if match is None:
        return None
    factor = MINUTES_PER_UNIT[match["unit"].casefold()]
    low = Fraction(match["low"]) * factor
    high = Fraction(match["high"] or match["low"]) * factor
    if low > high:
        return None
    return plain(rounded(low)), plain(rounded(high))


def _clean(name: str, source: str, field: str, raw: str | None, report: Report) -> str | None:
    if raw is None or not text.strip(raw):
        return None
    cleaned = text.line(raw)
    if cleaned is None:
        report.add(
            Kind.TEXT_DROPPED,
            f"tolerance {field} of the {source} {text.describe(raw)} is not valid text",
            substance=name,
        )
    return cleaned


def substance_tolerance(
    name: str, base: BaseSubstance | None, api: ApiSubstance | None, report: Report
) -> dict[str, Any] | None:
    """Return the ``tolerance`` object of one substance, or ``None`` when nothing is known."""
    result: dict[str, Any] = {}
    for field in FIELDS:
        from_api = _clean(
            name,
            "API",
            field,
            getattr(api.tolerance, field) if api and api.tolerance else None,
            report,
        )
        from_base = _clean(
            name,
            "base file",
            field,
            getattr(base.tolerance, field) if base and base.tolerance else None,
            report,
        )
        chosen = from_api if from_api is not None else from_base
        if chosen is None:
            continue
        if from_api is None:
            report.add(
                Kind.TOLERANCE_FROM_BASE,
                f"{field}: the API has no usable text, the base text '{chosen}' is used",
                substance=name,
            )
        elif from_base is not None and from_base != from_api:
            report.add(
                Kind.TOLERANCE_DIFFERS,
                f"{field}: the API text '{from_api}' is used, the base text was '{from_base}'",
                substance=name,
            )
        if field == "full":
            result[field] = chosen
            continue
        time = minutes(chosen)
        if time is None:
            report.add(
                Kind.TOLERANCE_NOT_PARSED,
                f"{field}: '{chosen}' does not read as a time, the text is kept without numbers",
                substance=name,
            )
            result[field] = {"text": chosen}
        else:
            result[field] = {"text": chosen, "min": time[0], "max": time[1]}
    return result or None
