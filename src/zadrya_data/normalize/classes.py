# SPDX-License-Identifier: GPL-3.0-or-later
"""Psychoactive and chemical classes of one substance.

Classes come from the API as given: stripped, without exact repeats, in API order.
They are empty lists when the API has none or the substance is only in the base file.
"""

from collections.abc import Iterable

from zadrya_data.graphql import ApiSubstance
from zadrya_data.normalize import text
from zadrya_data.normalize.report import Kind, Report


def _clean(name: str, kind: str, values: Iterable[str] | None, report: Report) -> list[str]:
    result: list[str] = []
    for raw in values or ():
        value = text.line(raw)
        if value is None:
            report.add(
                Kind.TEXT_DROPPED,
                f"{kind} class {text.describe(raw)} is not valid text",
                substance=name,
            )
        elif value not in result:
            result.append(value)
    return result


def substance_classes(name: str, api: ApiSubstance | None, report: Report) -> dict[str, list[str]]:
    """Return the ``classes`` object of one substance."""
    classes = api.classes if api else None
    return {
        "psychoactive": _clean(
            name, "psychoactive", classes.psychoactive if classes else None, report
        ),
        "chemical": _clean(name, "chemical", classes.chemical if classes else None, report),
    }
