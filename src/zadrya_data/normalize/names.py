# SPDX-License-Identifier: GPL-3.0-or-later
"""Aliases of one substance.

The aliases are the common names of the base file followed by those of the API,
stripped, without the canonical name itself, without repeats. Repeats and the
canonical name are recognized without regard to case, and the first spelling is
kept. Collisions between different substances are not resolved here.
"""

from collections.abc import Iterable

from zadrya_data.normalize import text
from zadrya_data.normalize.report import Kind, Report


def aliases(
    name: str, base_names: Iterable[str], api_names: Iterable[str], report: Report
) -> list[str]:
    """Return the aliases of a substance in source order (base first, then API)."""
    seen = {name.casefold()}
    result: list[str] = []
    for raw in [*base_names, *api_names]:
        alias = text.line(raw)
        if alias is None:
            report.add(
                Kind.ALIAS_DROPPED,
                f"alias {text.describe(raw)} is not valid text",
                substance=name,
            )
            continue
        if alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        result.append(alias)
    return result
