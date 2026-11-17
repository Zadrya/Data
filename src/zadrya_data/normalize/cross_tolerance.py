# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross tolerance: the groups of the dataset, and the groups of each substance.

Both sources list cross tolerance as loose tokens taken from the wiki's wording
("psychedelic", "psychedelics", "GABA|gabaergic", "trycyclic antidepressants"). The
tokens of a substance are the union of both sources, compared without case; a token
that only one source has is reported. Each token is looked up, without case, in the
explicit table ``TOKEN_TO_GROUP``. A token whose entry is ``None`` names no group of its
own (``analog`` only qualifies the token next to it) and a token missing from the
table is unknown: both are dropped and reported, never guessed.

A substance is a member of every group its tokens map to; a group's members are those
substances, sorted by code points. Only groups with at least one member are listed.
"""

from collections.abc import Iterable
from typing import Any

from zadrya_data.base import BaseSubstance
from zadrya_data.graphql import ApiSubstance
from zadrya_data.normalize import text
from zadrya_data.normalize.report import Kind, Report

# Group id to display name.
CROSS_TOLERANCE_GROUPS = {
    "benzodiazepines": "Benzodiazepines",
    "cannabinoids": "Cannabinoids",
    "deliriants": "Deliriants",
    "depressants": "Depressants",
    "dissociatives": "Dissociatives",
    "dopaminergic": "Dopaminergic substances",
    "entactogens": "Entactogens",
    "gabaergic": "GABAergic substances",
    "hallucinogens": "Hallucinogens",
    "modafinil-analogs": "Modafinil and its benzhydryl analogs",
    "noradrenergic": "Noradrenergic substances",
    "nootropics": "Nootropics",
    "opioids": "Opioids",
    "psychedelics": "Psychedelics",
    "racetams": "Racetams",
    "serotonergic": "Serotonergic substances",
    "stimulants": "Stimulants",
    "thienodiazepines": "Thienodiazepines",
    "tricyclic-antidepressants": "Tricyclic antidepressants",
}

# Every token seen in either source (snapshot of 2026-11-16 and the base file), in
# lower case, to a group id. ``None`` marks a token that names no group of its own.
# "a|b" tokens are wiki links (target|label) and map as a whole.
TOKEN_TO_GROUP: dict[str, str | None] = {
    "analog": None,
    "benzhydryl": "modafinil-analogs",
    "benzodiazepine": "benzodiazepines",
    "benzodiazepines": "benzodiazepines",
    "cannabinoids": "cannabinoids",
    "deliriant": "deliriants",
    "depressants": "depressants",
    "dissociative": "dissociatives",
    "dissociative|dissociatives": "dissociatives",
    "dissociatives": "dissociatives",
    "dopamine": "dopaminergic",
    "dopaminergic": "dopaminergic",
    "entactogens": "entactogens",
    "gaba": "gabaergic",
    "gaba|gabaergic": "gabaergic",
    "gabaergic": "gabaergic",
    "hallucinogen": "hallucinogens",
    # A misspelling of modafinil: N-Methylbisfluoromodafinil lists "modafanil" and
    # "analog", the wiki's "modafinil analogs", which the benzhydryl group is.
    "modafanil": "modafinil-analogs",
    "nootropic": "nootropics",
    "nootropic|nootropics": "nootropics",
    "norepinephrine|noradrenergic": "noradrenergic",
    "opioids": "opioids",
    "psychedelic": "psychedelics",
    "psychedelics": "psychedelics",
    "racetam": "racetams",
    "serotonergic": "serotonergic",
    "serotonin|serotonergic": "serotonergic",
    "stimulant": "stimulants",
    "stimulants": "stimulants",
    "thienodiazepine": "thienodiazepines",
    # A misspelling of thienodiazepines (Metizolam).
    "thienzodiazepines": "thienodiazepines",
    # A misspelling of tricyclic (Tianeptine).
    "trycyclic antidepressants": "tricyclic-antidepressants",
}

# Why a token that names no group is dropped.
DROPPED_TOKENS = {
    "analog": "it only qualifies the token next to it",
}


def _tokens(name: str, source: str, raws: Iterable[str], report: Report) -> dict[str, str]:
    """Return the valid tokens of one source by their lower case form, first spelling kept."""
    found: dict[str, str] = {}
    for raw in raws:
        token = text.line(raw)
        if token is None:
            report.add(
                Kind.TEXT_DROPPED,
                f"cross tolerance token of the {source} {text.describe(raw)} is not valid text",
                substance=name,
            )
            continue
        found.setdefault(token.casefold(), token)
    return found


def substance_cross_tolerances(
    name: str, base: BaseSubstance | None, api: ApiSubstance | None, report: Report
) -> list[str]:
    """Return the cross tolerance group ids of one substance, sorted."""
    from_base = _tokens(name, "base file", base.cross_tolerances if base else (), report)
    from_api = _tokens(name, "API", (api.cross_tolerances or ()) if api else (), report)
    if base is not None and api is not None:
        for key, token in from_base.items():
            if key not in from_api:
                report.add(
                    Kind.CROSS_TOLERANCE_SOURCES_DIFFER,
                    f"the token '{token}' is only in the base file",
                    substance=name,
                )
        for key, token in from_api.items():
            if key not in from_base:
                report.add(
                    Kind.CROSS_TOLERANCE_SOURCES_DIFFER,
                    f"the token '{token}' is only in the API",
                    substance=name,
                )
    groups: set[str] = set()
    for key, token in (
        from_base | {k: v for k, v in from_api.items() if k not in from_base}
    ).items():
        if key not in TOKEN_TO_GROUP:
            report.add(
                Kind.CROSS_TOLERANCE_TOKEN_DROPPED,
                f"the token '{token}' is not in the mapping table",
                substance=name,
            )
            continue
        group = TOKEN_TO_GROUP[key]
        if group is None:
            report.add(
                Kind.CROSS_TOLERANCE_TOKEN_DROPPED,
                f"the token '{token}' names no group: {DROPPED_TOKENS[key]}",
                substance=name,
            )
            continue
        groups.add(group)
    return sorted(groups)


def cross_tolerance_groups(
    substances: list[dict[str, Any]], report: Report
) -> list[dict[str, Any]]:
    """Return the groups that have members, by id, and report each with its members."""
    members: dict[str, list[str]] = {}
    for substance in substances:
        for group in substance["crossTolerances"]:
            members.setdefault(group, []).append(substance["name"])
    result = []
    for group in sorted(members):
        names = sorted(members[group])
        result.append({"id": group, "name": CROSS_TOLERANCE_GROUPS[group], "members": names})
        report.add(
            Kind.CROSS_TOLERANCE_GROUP,
            f"{group} ({len(names)}): {', '.join(names)}",
        )
    return result
