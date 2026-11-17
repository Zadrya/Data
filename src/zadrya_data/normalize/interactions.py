# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactions: typed targets by severity, merged from both sources and made symmetric.

For each substance the dangerous, unsafe and uncertain lists of both sources are
merged as a union. Each target name is resolved, in this order:

1. a catalog substance by its exact name, then through ``TARGET_NAMES`` (colloquial
   names of the data, without case), then by its name without case, then by an alias
   (without case) that only one catalog substance has: ``{kind: substance}``;
2. a class named in ``interaction_groups.NAME_TO_GROUP``: ``{kind: group, groupId}``;
3. anything else: ``{kind: other, name}``, with the name as written, one entry per
   name without case (the first spelling, base before API, is kept).

A target found under two severities keeps the higher one (dangerous over unsafe over
uncertain), and the conflict is reported. A substance target that is the substance
itself is dropped and reported. Every resolution that is not an exact name, and every
``other`` target, is reported once per spelling with the number of substances that
list it.

Substance targets are then made symmetric: when A lists B, B lists A with the same,
highest, severity, and each pair that was added or raised is reported. Group targets
are not expanded into substance pairs: the app resolves a group through its members
in both directions (ADR 5). A substance that lists a group it is a member of keeps
that target, and it is reported.

Within each severity the targets are sorted by kind (substance, group, other), then
by name or group id, by code points.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from zadrya_data.normalize import text
from zadrya_data.normalize.catalog import Entry
from zadrya_data.normalize.interaction_groups import GROUPS, group_of, interaction_groups
from zadrya_data.normalize.report import Kind, Report

SEVERITIES = ("dangerous", "unsafe", "uncertain")
_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}
_KIND_ORDER = {"substance": 0, "group": 1, "other": 2}

# Colloquial target names of the data, in lower case, to the catalog substance they
# mean. Only names whose meaning is certain: the API writes "Mushrooms" where the base
# file writes "Psilocybin mushrooms" (ten cannabinoids and Cocaine).
TARGET_NAMES = {
    "mushrooms": "Psilocybin mushrooms",
}

# A resolved target: (kind, value). The value is a canonical name, a group id, or for
# ``other`` the name without case (the spelling shown is kept apart).
type Key = tuple[str, str]


@dataclass(slots=True)
class _Resolver:
    """Resolves target names against the catalog and remembers what it did, for the report."""

    names: set[str]
    by_folded_name: dict[str, list[str]]
    by_alias: dict[str, set[str]]
    # (spelling, how, result) to the substances that list it.
    seen: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)

    @classmethod
    def of(cls, substances: list[dict[str, Any]]) -> "_Resolver":
        by_folded_name: dict[str, list[str]] = defaultdict(list)
        by_alias: dict[str, set[str]] = defaultdict(set)
        for substance in substances:
            by_folded_name[substance["name"].casefold()].append(substance["name"])
            for alias in substance["aliases"]:
                by_alias[alias.casefold()].add(substance["name"])
        return cls({s["name"] for s in substances}, by_folded_name, by_alias)

    def resolve(self, raw: str, lister: str) -> Key:
        """Return the target a name stands for."""
        folded = raw.casefold()
        if raw in self.names:
            return ("substance", raw)
        meant = TARGET_NAMES.get(folded)
        if meant is not None and meant in self.names:
            return self._note(raw, "by the target name table", ("substance", meant), lister)
        named = self.by_folded_name.get(folded, [])
        if len(named) == 1:
            return self._note(raw, "by its name without case", ("substance", named[0]), lister)
        owners = self.by_alias.get(folded, set())
        if len(owners) == 1:
            (owner,) = owners
            return self._note(raw, "by an alias only it has", ("substance", owner), lister)
        group = group_of(raw)
        if group is not None:
            return self._note(raw, "by the group table", ("group", group), lister)
        if len(owners) > 1 or len(named) > 1:
            several = ", ".join(sorted(owners | set(named)))
            how = f"is an alias or name of several substances ({several})"
        else:
            how = "is neither a catalog substance nor a group"
        return self._note(raw, how, ("other", folded), lister)

    def _note(self, raw: str, how: str, key: Key, lister: str) -> Key:
        self.seen.setdefault((raw, how, key[1]), set()).add(lister)
        return key

    def report(self, report: Report) -> None:
        """Report every resolution that was not an exact name, once per spelling."""
        for (raw, how, value), listers in sorted(
            self.seen.items(), key=lambda item: (item[0][0].casefold(), item[0])
        ):
            count = f"listed by {len(listers)} substance{'s' if len(listers) > 1 else ''}"
            if how.startswith("by the group"):
                detail = f"'{raw}' is the group '{value}' {how} ({count})"
                report.add(Kind.INTERACTION_TARGET_RESOLVED, detail)
            elif how.startswith("by "):
                detail = f"'{raw}' is the substance '{value}' {how} ({count})"
                report.add(Kind.INTERACTION_TARGET_RESOLVED, detail)
            else:
                detail = f"'{raw}' {how}: kept as other ({count})"
                report.add(Kind.INTERACTION_TARGET_OTHER, detail)


def _raw_targets(entry: Entry) -> list[tuple[str, str, str]]:
    """Return (severity, source, name) for every target of both sources, base first."""
    found: list[tuple[str, str, str]] = []
    if entry.base is not None and entry.base.interactions is not None:
        for severity in SEVERITIES:
            found += [(severity, "base", n) for n in getattr(entry.base.interactions, severity)]
    if entry.api is not None:
        for severity in SEVERITIES:
            names = getattr(entry.api, f"{severity}_interactions") or ()
            found += [(severity, "API", name) for name in names]
    return found


def _merge(
    entry: Entry, resolver: _Resolver, report: Report
) -> tuple[dict[Key, str], dict[Key, str]]:
    """Return the severity of each target of one substance, and the spelling of each other."""
    heard: dict[Key, dict[str, list[str]]] = {}
    shown: dict[Key, str] = {}
    sources: dict[Key, set[str]] = {}
    for severity, source, raw in _raw_targets(entry):
        cleaned = text.line(raw)
        if cleaned is None:
            report.add(
                Kind.TEXT_DROPPED,
                f"{severity} interaction of the {source} {text.describe(raw)} is not valid text",
                substance=entry.name,
            )
            continue
        key = resolver.resolve(cleaned, entry.name)
        if key == ("substance", entry.name):
            report.add(
                Kind.INTERACTION_TARGET_DROPPED,
                f"the {severity} target '{cleaned}' of the {source} is the substance itself",
                substance=entry.name,
            )
            continue
        shown.setdefault(key, cleaned if key[0] == "other" else key[1])
        heard.setdefault(key, {}).setdefault(severity, []).append(f"{source} '{cleaned}'")
        sources.setdefault(key, set()).add(source)
    # Targets only one source has are compared when both sources list some: a source
    # that lists none at all is one finding, not one per target.
    contributing = {source for found in sources.values() for source in found}
    both = entry.base is not None and entry.api is not None
    if both and len(contributing) == 1:
        (source,) = contributing
        silent = "API" if source == "base" else "base"
        report.add(
            Kind.INTERACTION_ONLY_IN_ONE_SOURCE,
            f"the {silent} lists no interactions: every target ({len(heard)}) is from the {source}",
            substance=entry.name,
        )
    chosen: dict[Key, str] = {}
    for key, severities in heard.items():
        ordered = sorted(severities, key=_RANK.__getitem__)
        chosen[key] = ordered[0]
        if len(contributing) == 2 and len(sources[key]) == 1:
            (source,) = sources[key]
            report.add(
                Kind.INTERACTION_ONLY_IN_ONE_SOURCE,
                f"'{shown[key]}' ({ordered[0]}) is only in the {source}",
                substance=entry.name,
            )
        if len(ordered) > 1:
            listed = "; ".join(f"{s} in {', '.join(severities[s])}" for s in ordered)
            report.add(
                Kind.INTERACTION_SEVERITY_CONFLICT,
                f"'{shown[key]}' is listed as {listed}: {ordered[0]} is kept",
                substance=entry.name,
            )
    return chosen, shown


def _symmetric(chosen: dict[str, dict[Key, str]], report: Report) -> None:
    """Give every substance pair the same, highest, severity in both directions."""
    pairs: dict[tuple[str, str], str] = {}
    for name, targets in chosen.items():
        for (kind, other), severity in targets.items():
            if kind != "substance":
                continue
            pair = (min(name, other), max(name, other))
            if pair not in pairs or _RANK[severity] < _RANK[pairs[pair]]:
                pairs[pair] = severity
    for (one, two), severity in sorted(pairs.items()):
        for name, other in ((one, two), (two, one)):
            had = chosen[name].get(("substance", other))
            if had == severity:
                continue
            chosen[name][("substance", other)] = severity
            if had is None:
                detail = f"'{other}' added as {severity}: '{other}' lists '{name}' as {severity}"
                report.add(Kind.INTERACTION_SYMMETRY_ADDED, detail, substance=name)
            else:
                detail = (
                    f"'{other}' raised from {had} to {severity}: "
                    f"'{other}' lists '{name}' as {severity}"
                )
                report.add(Kind.INTERACTION_SYMMETRY_RAISED, detail, substance=name)


def normalize_interactions(
    entries: list[tuple[Entry, dict[str, Any]]], report: Report
) -> list[dict[str, Any]]:
    """Fill in the ``interactions`` of every substance and return the interaction groups."""
    substances = [substance for _, substance in entries]
    resolver = _Resolver.of(substances)
    chosen: dict[str, dict[Key, str]] = {}
    shown: dict[str, dict[Key, str]] = {}
    for entry, substance in entries:
        chosen[substance["name"]], shown[substance["name"]] = _merge(entry, resolver, report)
    resolver.report(report)
    _symmetric(chosen, report)

    ids = {value for targets in chosen.values() for kind, value in targets if kind == "group"}
    groups = interaction_groups(ids, substances, report)
    members = {group["id"]: set(group["members"]) for group in groups}
    for substance in substances:
        name = substance["name"]
        lists: dict[str, list[dict[str, str]]] = {severity: [] for severity in SEVERITIES}
        for key in sorted(chosen[name], key=lambda k: (_KIND_ORDER[k[0]], _value(k, shown, name))):
            kind, value = key
            severity = chosen[name][key]
            if kind == "group":
                lists[severity].append({"kind": "group", "groupId": value})
                if name in members[value]:
                    report.add(
                        Kind.INTERACTION_OWN_GROUP,
                        f"lists its own group '{value}' ({GROUPS[value].name}) as {severity}: "
                        "kept, it may mean another substance of the same class",
                        substance=name,
                    )
            else:
                lists[severity].append({"kind": kind, "name": _value(key, shown, name)})
        substance["interactions"] = lists
    return groups


def _value(key: Key, shown: dict[str, dict[Key, str]], name: str) -> str:
    """Return the name or group id a target is written with and sorted by."""
    if key[0] == "other":
        return shown[name][key]
    return key[1]
