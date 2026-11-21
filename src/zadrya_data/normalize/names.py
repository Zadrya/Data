# SPDX-License-Identifier: GPL-3.0-or-later
"""Aliases of the substances.

The aliases of one substance are the common names of the base file followed by those
of the API, stripped, without the canonical name itself, without repeats, and without
the aliases that ``ALIAS_REMOVALS`` lists for it. Names are compared by
``name_key`` (Unicode normalization, case, spaces and invisible format characters
do not count), and the first spelling is kept.

Once every substance is known, ``drop_ambiguous_aliases`` removes, across the whole
catalog, an alias that is the name of another substance and an alias that several
substances carry: a name that does not lead to exactly one substance could attach an
ingestion, and its warnings, to the wrong one. Every removal is reported.
"""

import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from zadrya_data.normalize import text
from zadrya_data.normalize.report import Kind, Report

# Aliases of the source data that name a different substance, by (canonical name,
# ``name_key`` of the alias), with the reason. Only aliases the catalog-wide rule does not
# catch belong here, each confirmed in the dataset review.
ALIAS_REMOVALS: dict[tuple[str, str], str] = {
    ("Buspirone", "dimethyltryptamine"): (
        "it is the chemical name of DMT, a different substance; matching it could "
        "attach DMT warnings to Buspirone"
    ),
    ("Buspirone", "dmitri"): (
        "it is a street name of DMT, a different substance; matching it could attach "
        "DMT warnings to Buspirone"
    ),
}


def name_key(name: str) -> str:
    """Return the form in which two names count as the same name.

    Format characters (Unicode category Cf, such as the zero-width space and the
    soft hyphen) are removed, the text is normalized with NFKC and case folded (twice
    NFKC, as Unicode's caseless identifier matching does), and runs of whitespace
    become one space, without spaces at the ends. "LSD", "lsd", "L\u200bSD" and
    " L S D" with a double space all differ from "L S D" only where this says so:
    ``name_key("Ama  nita") == name_key("ama nita")``.
    """
    visible = "".join(c for c in name if unicodedata.category(c) != "Cf")
    folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", visible).casefold())
    return " ".join(folded.split())


def aliases(
    name: str, base_names: Iterable[str], api_names: Iterable[str], report: Report
) -> list[str]:
    """Return the aliases of a substance in source order (base first, then API)."""
    seen = {name_key(name)}
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
        if name_key(alias) in seen:
            continue
        seen.add(name_key(alias))
        reason = ALIAS_REMOVALS.get((name, name_key(alias)))
        if reason is not None:
            report.add(
                Kind.ALIAS_REMOVED,
                f"alias '{alias}' removed by the table: {reason}",
                substance=name,
            )
            continue
        result.append(alias)
    return result


def drop_ambiguous_aliases(substances: list[dict[str, Any]], report: Report) -> None:
    """Remove, in place, every alias that does not name exactly one substance.

    An alias whose ``name_key`` is that of another substance's name is dropped from
    the substance that carries it. An alias that several substances carry, compared
    by ``name_key``, is dropped from all of them. Findings follow the catalog order.
    """
    names = {name_key(substance["name"]): substance["name"] for substance in substances}
    holders: dict[str, list[str]] = defaultdict(list)
    for substance in substances:
        for alias in substance["aliases"]:
            holders[name_key(alias)].append(substance["name"])
    for substance in substances:
        kept: list[str] = []
        for alias in substance["aliases"]:
            folded = name_key(alias)
            if folded in names:
                report.add(
                    Kind.ALIAS_NAMES_ANOTHER_SUBSTANCE,
                    f"alias '{alias}' dropped: it is the name of the substance {names[folded]}",
                    substance=substance["name"],
                )
            elif len(holders[folded]) > 1:
                others = ", ".join(h for h in holders[folded] if h != substance["name"])
                report.add(
                    Kind.ALIAS_SHARED,
                    f"alias '{alias}' dropped: {others} carries it too, so it names no "
                    "single substance",
                    substance=substance["name"],
                )
            else:
                kept.append(alias)
        substance["aliases"] = kept
