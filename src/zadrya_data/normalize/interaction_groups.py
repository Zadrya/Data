# SPDX-License-Identifier: GPL-3.0-or-later
"""Interaction groups: the classes of substances that interaction targets name.

An interaction target such as "MAOIs", "25x-NBOMe" or "Stimulants" names a class, not
one substance. ``NAME_TO_GROUP`` maps every such name seen in the data (without case,
so "MAOI", "MAOIs" and "maois" are one entry) to a group id, and ``GROUPS`` gives each
group its display name and the documented rule that selects its members from the
catalog. A substance is a member when it matches any part of the rule:

- ``categories``: a category of the catalog (``stimulant``);
- ``psychoactive`` or ``chemical``: a class of the API, compared without case;
- ``pattern``: a regular expression the whole name matches (the 25x-NBOMe series);
- ``names``: an explicit list of catalog names.

Under-inclusion means a missed warning, so a rule includes when unsure, and each such
choice is written next to it. Every group is reported with its members; an empty group
and an explicit name that is not in the catalog are reported on their own.
"""

import re
from dataclasses import dataclass
from typing import Any

from zadrya_data.normalize.report import Kind, Report


@dataclass(frozen=True, slots=True)
class GroupRule:
    """A group of the dataset and how its members are found in the catalog."""

    name: str
    categories: tuple[str, ...] = ()
    psychoactive: tuple[str, ...] = ()
    chemical: tuple[str, ...] = ()
    pattern: str | None = None
    names: tuple[str, ...] = ()

    def describe(self) -> str:
        """Return the rule in words, for the report."""
        parts = []
        if self.categories:
            parts.append(f"category {' or '.join(self.categories)}")
        if self.psychoactive:
            parts.append(f"psychoactive class {' or '.join(self.psychoactive)}")
        if self.chemical:
            parts.append(f"chemical class {' or '.join(self.chemical)}")
        if self.pattern is not None:
            parts.append(f"name matching {self.pattern}")
        if self.names:
            parts.append(f"named {', '.join(self.names)}")
        return "; ".join(parts) if parts else "no catalog substance belongs to it"

    def matches(self, substance: dict[str, Any]) -> bool:
        """Tell whether a normalized substance is a member."""
        psychoactive = {c.casefold() for c in substance["classes"]["psychoactive"]}
        chemical = {c.casefold() for c in substance["classes"]["chemical"]}
        if self.pattern is not None and re.fullmatch(self.pattern, substance["name"]):
            return True
        return (
            any(category in substance["categories"] for category in self.categories)
            or any(c.casefold() in psychoactive for c in self.psychoactive)
            or any(c.casefold() in chemical for c in self.chemical)
            or substance["name"] in self.names
        )


GROUPS = {
    "25x-nboh": GroupRule("25x-NBOH", pattern=r"25[A-Z]-NBOH"),
    "25x-nbome": GroupRule("25x-NBOMe", pattern=r"25[A-Z]-NBOMe"),
    # 2C-T itself is the parent of the series and is included.
    "2c-t-x": GroupRule("2C-T-x", pattern=r"2C-T(-[0-9]+)?"),
    # Every 2C compound, including 2C-T-x and 2C-B-FLY; βk-2C-B is a 2C-B analog and is
    # included because leaving it out would hide a warning.
    "2c-x": GroupRule("2C-x", pattern=r"2C-[A-Z].*", names=("Βk-2C-B",)),
    # The x stands for letters and the name ends in T: 5-MeO-DiBF is a benzofuran.
    "5-meo-xxt": GroupRule("5-MeO-xxT", pattern=r"5-MeO-[A-Za-z]+T"),
    "aldh2-inhibitors": GroupRule("ALDH2 inhibitors"),
    "antidepressants": GroupRule(
        "Antidepressants",
        categories=("antidepressant",),
        psychoactive=("Antidepressant", "Antidepressants"),
        chemical=("Antidepressants",),
    ),
    # No class marks antihistamines: the H1 antihistamines of the catalog by name, the
    # two whose base summary says "antihistamine". Quetiapine and Mirtazapine are
    # antihistaminic but classed as an antipsychotic and an antidepressant, and no wiki
    # class calls them antihistamines, so they are left out.
    "antihistamines": GroupRule("Antihistamines", names=("Diphenhydramine", "Promethazine")),
    "barbiturates": GroupRule(
        "Barbiturates", categories=("barbiturate",), chemical=("Barbiturates",)
    ),
    "benzodiazepines": GroupRule(
        "Benzodiazepines",
        categories=("benzodiazepine",),
        chemical=("Benzodiazepines", "Thienodiazepines"),
        # Base-only benzodiazepines without the category or an API class.
        names=("Chlordiazepoxide", "Cinolazepam"),
    ),
    # Substrates of CYP2C19 in the catalog whose main metabolism goes through it.
    "cyp2c19-substrates": GroupRule(
        "CYP2C19 substrates", names=("Carisoprodol", "Diazepam", "Flunitrazepam")
    ),
    "deliriants": GroupRule(
        "Deliriants", categories=("deliriant",), psychoactive=("Deliriant", "Deliriants")
    ),
    # Desomorphine is an opioid without the depressant category or class, and Tilidin
    # a base-only opioid without any category.
    "depressants": GroupRule(
        "Depressants",
        categories=("depressant", "benzodiazepine", "barbiturate"),
        psychoactive=("Depressant", "Depressants"),
        names=("Desomorphine", "Tilidin"),
    ),
    "dissociatives": GroupRule(
        "Dissociatives",
        categories=("dissociative",),
        psychoactive=("Dissociative", "Dissociatives"),
    ),
    "dox": GroupRule("DOx", pattern=r"DO[A-Z]"),
    "hepatotoxic-drugs": GroupRule("Hepatotoxic drugs"),
    # Progesterone is a hormone used in hormonal birth control.
    "hormonal-birth-control": GroupRule("Hormonal birth control", names=("Progesterone",)),
    # No class marks MAOIs. Ayahuasca contains harmala alkaloids, which are MAO
    # inhibitors; the base summary of 2C-T-7 calls it a "possible MAOI", included because
    # a missed MAOI warning is the unsafe direction. Syrian rue (Peganum harmala) and
    # Banisteriopsis caapi have API entries without any number, so they are not in the
    # catalog (ADR 4); no pharmaceutical MAOI is in the catalog.
    "maois": GroupRule("MAOIs", names=("2C-T-7", "Ayahuasca")),
    # Tilidin is a base-only opioid without any category.
    "opioids": GroupRule(
        "Opioids", categories=("opioid",), psychoactive=("Opioid", "Opioids"), names=("Tilidin",)
    ),
    "protease-inhibitors": GroupRule("Protease inhibitors"),
    "psychedelics": GroupRule(
        "Psychedelics", categories=("psychedelic",), psychoactive=("Psychedelic", "Psychedelics")
    ),
    # The entactogen class of the API (MDMA, the cathinones, the benzofurans, αMT), and
    # mCPP, a serotonin releaser classed as a stimulant, and Ethylone, an entactogenic
    # cathinone like Methylone whose API classes lack the class. NM-2-AI is in the entactogen
    # category without the class and is included because its action is not clear. The
    # entactogen category is not used: it also holds 2C-B, 2C-T, 2C-T-7, 4-AcO-MiPT,
    # 5-MeO-DiPT, Ayahuasca and Psilocin, which act on receptors and release no serotonin.
    "serotonin-releasers": GroupRule(
        "Serotonin releasers",
        psychoactive=("Entactogen", "Entactogens"),
        names=("Ethylone", "MCPP", "NM-2-AI"),
    ),
    "snris": GroupRule("SNRIs"),
    "ssris": GroupRule("SSRIs"),
    "stimulants": GroupRule(
        "Stimulants", categories=("stimulant",), psychoactive=("Stimulant", "Stimulants")
    ),
    # Amphetamine and Dextroamphetamine have the chemical class of phenethylamines only.
    "substituted-amphetamines": GroupRule(
        "Substituted amphetamines",
        chemical=("Amphetamine", "Substituted amphetamines"),
        names=("Amphetamine", "Dextroamphetamine"),
    ),
    # Tianeptine is an atypical tricyclic antidepressant.
    "tricyclic-antidepressants": GroupRule("Tricyclic antidepressants", names=("Tianeptine",)),
}

# Every interaction target name of the data that names a class, in lower case.
NAME_TO_GROUP = {
    "25x-nboh": "25x-nboh",
    "25x-nbome": "25x-nbome",
    "nbome": "25x-nbome",
    "nbomes": "25x-nbome",
    "2c-t-x": "2c-t-x",
    "2c-x": "2c-x",
    "5-meo-xxt": "5-meo-xxt",
    "aldh2 inhibitors": "aldh2-inhibitors",
    "antidepressants": "antidepressants",
    "antihistamine": "antihistamines",
    "antihistamines": "antihistamines",
    "barbiturates": "barbiturates",
    "benzodiazepines": "benzodiazepines",
    "cyp2c19-substrates": "cyp2c19-substrates",
    "deliriant": "deliriants",
    "deliriants": "deliriants",
    "depressant": "depressants",
    "depressants": "depressants",
    "dissociatives": "dissociatives",
    "dox": "dox",
    "hepatotoxic drugs": "hepatotoxic-drugs",
    "hormonal birth control": "hormonal-birth-control",
    "maoi": "maois",
    "maois": "maois",
    "opioids": "opioids",
    "protease inhibitors": "protease-inhibitors",
    "psychedelics": "psychedelics",
    "serotonin releasers": "serotonin-releasers",
    "snris": "snris",
    "ssri": "ssris",
    "ssris": "ssris",
    "stimulants": "stimulants",
    "amphetamines": "substituted-amphetamines",
    "substituted amphetamines": "substituted-amphetamines",
    "tricyclic antidepressants": "tricyclic-antidepressants",
}


def group_of(name: str) -> str | None:
    """Return the id of the group a target name stands for, or ``None``."""
    return NAME_TO_GROUP.get(name.casefold())


def interaction_groups(
    ids: set[str], substances: list[dict[str, Any]], report: Report
) -> list[dict[str, Any]]:
    """Return the groups with these ids, sorted, with their members, and report each one."""
    catalog = {substance["name"] for substance in substances}
    result = []
    for group in sorted(ids):
        rule = GROUPS[group]
        members = sorted(s["name"] for s in substances if rule.matches(s))
        result.append({"id": group, "name": rule.name, "members": members})
        report.add(
            Kind.INTERACTION_GROUP,
            f"{group} ({len(members)}), {rule.describe()}: {', '.join(members) or 'none'}",
        )
        for name in rule.names:
            if name not in catalog:
                report.add(
                    Kind.INTERACTION_GROUP_NAME_MISSING,
                    f"{group}: the named member '{name}' is not in the catalog",
                )
        if not members:
            report.add(
                Kind.INTERACTION_GROUP_EMPTY,
                f"{group}: no catalog substance belongs to it, so the app can only show "
                "the warning on the substance that lists it",
            )
    return result
