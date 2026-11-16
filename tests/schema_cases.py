# SPDX-License-Identifier: GPL-3.0-or-later
"""The schema fixture documents, defined in code.

The files in ``tests/fixtures/schema`` are generated from this module and committed,
so that they can be read, diffed and used by other tools. After changing a case, or
adding one for a new schema rule, rewrite them with::

    uv run python -m tests.schema_cases

``tests/test_schema_fixtures.py`` fails when the committed files and this module
disagree. Every invalid case is a complete document that breaks exactly one rule:
its name says which, ``path`` is the JSON path of the violation and ``rule`` the
schema keyword that rejects it.
"""

import copy
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "schema"

type Step = str | int


@dataclass(frozen=True)
class InvalidCase:
    """A document that breaks one schema rule."""

    name: str
    document: Any
    path: str
    rule: str


def _put(document: Any, path: Sequence[Step], value: object) -> Any:
    """Return a copy of the document with the value at the path set."""
    result = copy.deepcopy(document)
    target = result
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return result


def _cut(document: Any, path: Sequence[Step]) -> Any:
    """Return a copy of the document without the key at the path."""
    result = copy.deepcopy(document)
    target = result
    for step in path[:-1]:
        target = target[step]
    del target[path[-1]]
    return result


# ---- substances.json


def _minimal() -> Any:
    return {
        "schemaVersion": "1.0.0",
        "datasetVersion": "1.0.0",
        "attribution": [
            {
                "name": "PsychonautWiki",
                "url": "https://psychonautwiki.org",
                "license": "CC-BY-SA-4.0",
            }
        ],
        "categories": [],
        "interactionGroups": [],
        "crossToleranceGroups": [],
        "substances": [],
    }


def _minimal_substance() -> Any:
    return {
        "name": "LSD",
        "aliases": [],
        "url": "https://psychonautwiki.org/wiki/LSD",
        "categories": [],
        "classes": {"psychoactive": [], "chemical": []},
        "roas": [],
        "crossTolerances": [],
        "interactions": {"dangerous": [], "unsafe": [], "uncertain": []},
        "toxicities": [],
    }


def _with_substance() -> Any:
    return _put(_minimal(), ["substances"], [_minimal_substance()])


def _with_category() -> Any:
    category = {
        "id": "psychedelic",
        "name": "Psychedelic",
        "description": "Substances that alter perception and cognition.",
    }
    return _put(_minimal(), ["categories"], [category])


def _with_group() -> Any:
    group = {"id": "stimulants", "name": "Stimulants", "members": []}
    return _put(_minimal(), ["interactionGroups"], [group])


def _with_cross_tolerance_group() -> Any:
    group = {"id": "psychedelics", "name": "Psychedelics", "members": []}
    return _put(_minimal(), ["crossToleranceGroups"], [group])


def _with_roa() -> Any:
    roa = {
        "route": "sublingual",
        "dose": {
            "units": "µg",
            "lightMin": 15,
            "commonMin": 75,
            "strongMin": 150,
            "heavyMin": 300,
        },
        "duration": {"onset": {"min": 15, "max": 30}},
        "bioavailability": {"min": 71, "max": 71},
    }
    return _put(_with_substance(), [*_S, "roas"], [roa])


def _with_target() -> Any:
    target = {"kind": "other", "name": "Ritonavir"}
    return _put(_with_substance(), [*_S, "interactions", "unsafe"], [target])


def _full() -> Any:
    document = _with_category()
    document["attribution"].append(
        {
            "name": "PsychonautWiki Journal",
            "url": "https://github.com/isaakhanimann/psychonautwiki-journal-android",
            "license": "GPL-3.0-only",
        }
    )
    document["categories"].append(
        {
            "id": "research-chemical",
            "name": "Research chemical",
            "description": "Substances with little history of human use.",
        }
    )
    document["interactionGroups"] = [
        {"id": "stimulants", "name": "Stimulants", "members": ["1P-LSD"]},
        {
            "id": "tricyclic-antidepressants",
            "name": "Tricyclic antidepressants",
            "members": [],
        },
    ]
    document["crossToleranceGroups"] = [
        {"id": "psychedelics", "name": "Psychedelics", "members": ["LSD", "1P-LSD"]},
        {"id": "5-ht2a-agonists", "name": "5-HT2A agonists", "members": []},
    ]
    lsd = {
        "name": "LSD",
        "aliases": ["LSD-25", "Acid", "Lucy"],
        "url": "https://psychonautwiki.org/wiki/LSD",
        "summary": "LSD is a popular psychedelic with a long history of use and research.",
        "categories": ["psychedelic"],
        "classes": {"psychoactive": ["Psychedelics"], "chemical": ["Lysergamides"]},
        "roas": [
            {
                "route": "sublingual",
                "dose": {
                    "units": "µg",
                    "lightMin": 15,
                    "commonMin": 75,
                    "strongMin": 150,
                    "heavyMin": 300,
                },
                "duration": {
                    "onset": {"min": 15, "max": 30},
                    "comeup": {"min": 45, "max": 90},
                    "peak": {"min": 180, "max": 300},
                    "offset": {"min": 180, "max": 300},
                    "total": {"min": 480, "max": 720},
                    "afterglow": {"min": 720, "max": 2880},
                },
                "bioavailability": {"min": 71, "max": 71},
            },
            {
                "route": "oral",
                "dose": {"units": "µg", "commonMin": 100.5},
                "duration": {"onset": {"max": 0.5}, "total": {"min": 480}},
                "bioavailability": {"max": 80},
            },
            {"route": "smoked", "dose": {"units": "mg THC"}},
            {"route": "intravenous"},
        ],
        "tolerance": {
            "full": "almost immediately after ingestion",
            "half": {"text": "3 days", "min": 4320, "max": 4320},
            "zero": {"text": "1-2 weeks", "min": 10080, "max": 20160},
        },
        "crossTolerances": ["psychedelics", "5-ht2a-agonists"],
        "interactions": {
            "dangerous": [{"kind": "other", "name": "Lithium"}],
            "unsafe": [
                {"kind": "group", "groupId": "tricyclic-antidepressants"},
                {"kind": "other", "name": "Ritonavir"},
            ],
            "uncertain": [
                {"kind": "substance", "name": "1P-LSD"},
                {"kind": "group", "groupId": "stimulants"},
            ],
        },
        "addictionPotential": "non-addictive with a low abuse potential",
        "toxicities": ["extremely low toxicity relative to dose"],
        "effectsSummary": "The effect depends very much on dose, set and setting.",
        "dosageRemark": "Blotters vary widely in strength.",
        "generalRisks": "The risks of LSD use are psychological.\nThere is a risk that latent mental disorders are triggered.",
        "longtermRisks": "Latent mental disorders can be triggered.",
        "saferUse": ["Dose low.", "Take LSD only in an environment where you feel comfortable."],
    }
    other = _minimal_substance() | {
        "name": "1P-LSD",
        "url": "https://psychonautwiki.org/wiki/1P-LSD",
        "categories": ["psychedelic", "research-chemical"],
        "tolerance": {"zero": {"text": "unknown, probably like LSD"}},
    }
    document["substances"] = [lsd, other]
    return document


_S: list[Step] = ["substances", 0]
_R: list[Step] = [*_S, "roas", 0]
_T: list[Step] = [*_S, "interactions", "unsafe", 0]
_SP = "$.substances[0]"
_RP = "$.substances[0].roas[0]"
_TP = "$.substances[0].interactions.unsafe[0]"


def substances_valid() -> dict[str, Any]:
    """Return the valid documents by fixture name."""
    return {
        "minimal": _minimal(),
        "minimal-substance": _with_substance(),
        "full": _full(),
    }


def substances_invalid() -> list[InvalidCase]:
    """Return the invalid documents, one per rule."""
    case = InvalidCase
    x = _with_cross_tolerance_group()
    m, c, g, s, r, t = (
        _minimal(),
        _with_category(),
        _with_group(),
        _with_substance(),
        _with_roa(),
        _with_target(),
    )
    return [
        case("top-level-missing-substances", _cut(m, ["substances"]), "$", "required"),
        case(
            "top-level-unknown-property",
            _put(m, ["generatedAt"], "2026-11-16"),
            "$",
            "additionalProperties",
        ),
        case("top-level-not-an-object", [m], "$", "type"),
        case(
            "schema-version-not-semver",
            _put(m, ["schemaVersion"], "1.0"),
            "$.schemaVersion",
            "pattern",
        ),
        case(
            "schema-version-major-not-1",
            _put(m, ["schemaVersion"], "2.0.0"),
            "$.schemaVersion",
            "pattern",
        ),
        case(
            "schema-version-trailing-newline",
            _put(m, ["schemaVersion"], "1.0.0\n"),
            "$.schemaVersion",
            "pattern",
        ),
        case(
            "dataset-version-trailing-newline",
            _put(m, ["datasetVersion"], "1.0.0\n"),
            "$.datasetVersion",
            "pattern",
        ),
        case(
            "attribution-url-trailing-newline",
            _put(m, ["attribution", 0, "url"], "https://psychonautwiki.org\n"),
            "$.attribution[0].url",
            "pattern",
        ),
        case(
            "attribution-url-with-a-space",
            _put(m, ["attribution", 0, "url"], "https://psychonautwiki.org/wiki/Main Page"),
            "$.attribution[0].url",
            "pattern",
        ),
        case(
            "attribution-url-not-ascii",
            _put(m, ["attribution", 0, "url"], "https://psychonautwiki.org/wiki/\u0391MT"),
            "$.attribution[0].url",
            "pattern",
        ),
        case(
            "category-id-trailing-newline",
            _put(c, ["categories", 0, "id"], "psychedelic\n"),
            "$.categories[0].id",
            "pattern",
        ),
        case(
            "substance-url-trailing-newline",
            _put(s, [*_S, "url"], "https://psychonautwiki.org/wiki/LSD\n"),
            f"{_SP}.url",
            "pattern",
        ),
        case(
            "substance-url-not-ascii",
            _put(s, [*_S, "url"], "https://psychonautwiki.org/wiki/\u0391MT"),
            f"{_SP}.url",
            "pattern",
        ),
        case(
            "dataset-version-not-semver",
            _put(m, ["datasetVersion"], "v1.0.0"),
            "$.datasetVersion",
            "pattern",
        ),
        case(
            "dataset-version-with-pre-release",
            _put(m, ["datasetVersion"], "1.0.0-rc.1"),
            "$.datasetVersion",
            "pattern",
        ),
        case("attribution-empty", _put(m, ["attribution"], []), "$.attribution", "minItems"),
        case(
            "attribution-missing-license",
            _cut(m, ["attribution", 0, "license"]),
            "$.attribution[0]",
            "required",
        ),
        case(
            "attribution-unknown-property",
            _put(m, ["attribution", 0, "author"], "Someone"),
            "$.attribution[0]",
            "additionalProperties",
        ),
        case(
            "attribution-url-not-https",
            _put(m, ["attribution", 0, "url"], "http://psychonautwiki.org"),
            "$.attribution[0].url",
            "pattern",
        ),
        case(
            "attribution-name-empty",
            _put(m, ["attribution", 0, "name"], ""),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-only-whitespace",
            _put(m, ["attribution", 0, "name"], " \t "),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-leading-whitespace",
            _put(m, ["attribution", 0, "name"], " PsychonautWiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-trailing-whitespace",
            _put(m, ["attribution", 0, "name"], "PsychonautWiki "),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-trailing-newline",
            _put(m, ["attribution", 0, "name"], "PsychonautWiki\n"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-leading-no-break-space",
            _put(m, ["attribution", 0, "name"], "\u00a0PsychonautWiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-leading-byte-order-mark",
            _put(m, ["attribution", 0, "name"], "\ufeffPsychonautWiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-null-character",
            _put(m, ["attribution", 0, "name"], "Psychonaut\u0000Wiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-line-break-inside",
            _put(m, ["attribution", 0, "name"], "Psychonaut\nWiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-tab-inside",
            _put(m, ["attribution", 0, "name"], "Psychonaut\tWiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "paragraphs-empty",
            _put(s, [*_S, "generalRisks"], ""),
            f"{_SP}.generalRisks",
            "pattern",
        ),
        case(
            "paragraphs-leading-line-break",
            _put(s, [*_S, "generalRisks"], "\nThe risks are psychological."),
            f"{_SP}.generalRisks",
            "pattern",
        ),
        case(
            "paragraphs-trailing-line-break",
            _put(s, [*_S, "generalRisks"], "The risks are psychological.\n"),
            f"{_SP}.generalRisks",
            "pattern",
        ),
        case(
            "paragraphs-null-character",
            _put(s, [*_S, "generalRisks"], "The risks are\u0000psychological."),
            f"{_SP}.generalRisks",
            "pattern",
        ),
        case(
            "paragraphs-carriage-return",
            _put(s, [*_S, "generalRisks"], "The risks.\r\nThey are psychological."),
            f"{_SP}.generalRisks",
            "pattern",
        ),
        case(
            "category-missing-description",
            _cut(c, ["categories", 0, "description"]),
            "$.categories[0]",
            "required",
        ),
        case(
            "category-unknown-property-color",
            _put(c, ["categories", 0, "color"], 4288423856),
            "$.categories[0]",
            "additionalProperties",
        ),
        case(
            "category-id-not-a-slug",
            _put(c, ["categories", 0, "id"], "Research Chemical"),
            "$.categories[0].id",
            "pattern",
        ),
        case("substance-missing-name", _cut(s, [*_S, "name"]), _SP, "required"),
        case(
            "substance-unknown-property-is-approved",
            _put(s, [*_S, "isApproved"], True),
            _SP,
            "additionalProperties",
        ),
        case("substance-name-empty", _put(s, [*_S, "name"], ""), f"{_SP}.name", "pattern"),
        case(
            "substance-aliases-not-a-list",
            _put(s, [*_S, "aliases"], "Acid"),
            f"{_SP}.aliases",
            "type",
        ),
        case(
            "substance-url-not-https",
            _put(s, [*_S, "url"], "http://psychonautwiki.org/wiki/LSD"),
            f"{_SP}.url",
            "pattern",
        ),
        case(
            "substance-url-not-a-psychonautwiki-article",
            _put(s, [*_S, "url"], "https://en.wikipedia.org/wiki/LSD"),
            f"{_SP}.url",
            "pattern",
        ),
        case(
            "substance-summary-not-a-string",
            _put(s, [*_S, "summary"], ["LSD is a psychedelic."]),
            f"{_SP}.summary",
            "type",
        ),
        case(
            "substance-category-not-a-slug",
            _put(s, [*_S, "categories"], ["Psychedelic"]),
            f"{_SP}.categories[0]",
            "pattern",
        ),
        case(
            "classes-missing-chemical",
            _cut(s, [*_S, "classes", "chemical"]),
            f"{_SP}.classes",
            "required",
        ),
        case(
            "classes-unknown-property",
            _put(s, [*_S, "classes", "legal"], []),
            f"{_SP}.classes",
            "additionalProperties",
        ),
        case(
            "tolerance-empty", _put(s, [*_S, "tolerance"], {}), f"{_SP}.tolerance", "minProperties"
        ),
        case(
            "tolerance-unknown-property",
            _put(s, [*_S, "tolerance"], {"full": "1 day", "quarter": "2 days"}),
            f"{_SP}.tolerance",
            "additionalProperties",
        ),
        case(
            "tolerance-full-not-a-string",
            _put(s, [*_S, "tolerance"], {"full": {"text": "1 day"}}),
            f"{_SP}.tolerance.full",
            "type",
        ),
        case(
            "tolerance-half-not-an-object",
            _put(s, [*_S, "tolerance"], {"half": "3 days"}),
            f"{_SP}.tolerance.half",
            "type",
        ),
        case(
            "tolerance-zero-not-an-object",
            _put(s, [*_S, "tolerance"], {"zero": 7200}),
            f"{_SP}.tolerance.zero",
            "type",
        ),
        case(
            "tolerance-time-missing-text",
            _put(s, [*_S, "tolerance"], {"zero": {"min": 7200, "max": 7200}}),
            f"{_SP}.tolerance.zero",
            "required",
        ),
        case(
            "tolerance-time-unknown-property",
            _put(s, [*_S, "tolerance"], {"zero": {"text": "5 days", "units": "days"}}),
            f"{_SP}.tolerance.zero",
            "additionalProperties",
        ),
        case(
            "tolerance-time-text-empty",
            _put(s, [*_S, "tolerance"], {"zero": {"text": ""}}),
            f"{_SP}.tolerance.zero.text",
            "pattern",
        ),
        case(
            "tolerance-time-min-without-max",
            _put(s, [*_S, "tolerance"], {"zero": {"text": "5 days", "min": 7200}}),
            f"{_SP}.tolerance.zero",
            "dependentRequired",
        ),
        case(
            "tolerance-time-max-without-min",
            _put(s, [*_S, "tolerance"], {"zero": {"text": "5 days", "max": 7200}}),
            f"{_SP}.tolerance.zero",
            "dependentRequired",
        ),
        case(
            "tolerance-time-min-negative",
            _put(s, [*_S, "tolerance"], {"zero": {"text": "5 days", "min": -1, "max": 7200}}),
            f"{_SP}.tolerance.zero.min",
            "minimum",
        ),
        case(
            "tolerance-time-max-not-a-number",
            _put(s, [*_S, "tolerance"], {"zero": {"text": "5 days", "min": 7200, "max": "7200"}}),
            f"{_SP}.tolerance.zero.max",
            "type",
        ),
        case(
            "cross-tolerance-group-missing-name",
            _cut(x, ["crossToleranceGroups", 0, "name"]),
            "$.crossToleranceGroups[0]",
            "required",
        ),
        case(
            "cross-tolerance-group-unknown-property",
            _put(x, ["crossToleranceGroups", 0, "substances"], []),
            "$.crossToleranceGroups[0]",
            "additionalProperties",
        ),
        case(
            "cross-tolerance-group-id-not-a-slug",
            _put(x, ["crossToleranceGroups", 0, "id"], "serotonin|serotonergic"),
            "$.crossToleranceGroups[0].id",
            "pattern",
        ),
        case(
            "cross-tolerance-groups-not-a-list",
            _put(x, ["crossToleranceGroups"], {"psychedelics": ["LSD"]}),
            "$.crossToleranceGroups",
            "type",
        ),
        case(
            "cross-tolerance-not-a-group-id",
            _put(s, [*_S, "crossTolerances"], ["GABA"]),
            f"{_SP}.crossTolerances[0]",
            "pattern",
        ),
        case(
            "toxicities-not-a-list",
            _put(s, [*_S, "toxicities"], "low toxicity"),
            f"{_SP}.toxicities",
            "type",
        ),
        case(
            "safer-use-not-a-list",
            _put(s, [*_S, "saferUse"], "Dose low."),
            f"{_SP}.saferUse",
            "type",
        ),
        case("safer-use-empty", _put(s, [*_S, "saferUse"], []), f"{_SP}.saferUse", "minItems"),
        case("roa-missing-route", _cut(r, [*_R, "route"]), _RP, "required"),
        case(
            "roa-unknown-property",
            _put(r, [*_R, "name"], "sublingual"),
            _RP,
            "additionalProperties",
        ),
        case(
            "roa-route-not-in-the-list",
            _put(r, [*_R, "route"], "sublabial"),
            f"{_RP}.route",
            "enum",
        ),
        case("dose-missing-units", _cut(r, [*_R, "dose", "units"]), f"{_RP}.dose", "required"),
        case("dose-not-an-object", _put(r, [*_R, "dose"], 75), f"{_RP}.dose", "type"),
        case(
            "dose-unknown-property-threshold",
            _put(r, [*_R, "dose", "threshold"], 5),
            f"{_RP}.dose",
            "additionalProperties",
        ),
        case(
            "dose-unknown-property-light-range",
            _put(r, [*_R, "dose", "light"], {"min": 15, "max": 75}),
            f"{_RP}.dose",
            "additionalProperties",
        ),
        case(
            "dose-units-empty",
            _put(r, [*_R, "dose", "units"], ""),
            f"{_RP}.dose.units",
            "pattern",
        ),
        case(
            "dose-units-not-a-string",
            _put(r, [*_R, "dose", "units"], ["µg"]),
            f"{_RP}.dose.units",
            "type",
        ),
        case(
            "dose-units-greek-mu",
            _put(r, [*_R, "dose", "units"], "\u03bcg"),
            f"{_RP}.dose.units",
            "not",
        ),
        case(
            "dose-light-min-negative",
            _put(r, [*_R, "dose", "lightMin"], -1),
            f"{_RP}.dose.lightMin",
            "minimum",
        ),
        case(
            "dose-light-min-not-a-number",
            _put(r, [*_R, "dose", "lightMin"], "75"),
            f"{_RP}.dose.lightMin",
            "type",
        ),
        case(
            "dose-common-min-negative",
            _put(r, [*_R, "dose", "commonMin"], -1),
            f"{_RP}.dose.commonMin",
            "minimum",
        ),
        case(
            "dose-common-min-not-a-number",
            _put(r, [*_R, "dose", "commonMin"], "75"),
            f"{_RP}.dose.commonMin",
            "type",
        ),
        case(
            "dose-strong-min-negative",
            _put(r, [*_R, "dose", "strongMin"], -1),
            f"{_RP}.dose.strongMin",
            "minimum",
        ),
        case(
            "dose-strong-min-not-a-number",
            _put(r, [*_R, "dose", "strongMin"], "75"),
            f"{_RP}.dose.strongMin",
            "type",
        ),
        case(
            "dose-heavy-min-negative",
            _put(r, [*_R, "dose", "heavyMin"], -1),
            f"{_RP}.dose.heavyMin",
            "minimum",
        ),
        case(
            "dose-heavy-min-not-a-number",
            _put(r, [*_R, "dose", "heavyMin"], "75"),
            f"{_RP}.dose.heavyMin",
            "type",
        ),
        case("duration-empty", _put(r, [*_R, "duration"], {}), f"{_RP}.duration", "minProperties"),
        case(
            "duration-unknown-phase",
            _put(r, [*_R, "duration", "hangover"], {"min": 60}),
            f"{_RP}.duration",
            "additionalProperties",
        ),
        case(
            "duration-range-empty",
            _put(r, [*_R, "duration", "onset"], {}),
            f"{_RP}.duration.onset",
            "minProperties",
        ),
        case(
            "duration-range-unknown-property-units",
            _put(r, [*_R, "duration", "onset", "units"], "minutes"),
            f"{_RP}.duration.onset",
            "additionalProperties",
        ),
        case(
            "duration-range-min-negative",
            _put(r, [*_R, "duration", "onset", "min"], -15),
            f"{_RP}.duration.onset.min",
            "minimum",
        ),
        case(
            "duration-range-max-not-a-number",
            _put(r, [*_R, "duration", "onset", "max"], "30 minutes"),
            f"{_RP}.duration.onset.max",
            "type",
        ),
        case(
            "bioavailability-empty",
            _put(r, [*_R, "bioavailability"], {}),
            f"{_RP}.bioavailability",
            "minProperties",
        ),
        case(
            "bioavailability-unknown-property",
            _put(r, [*_R, "bioavailability", "units"], "%"),
            f"{_RP}.bioavailability",
            "additionalProperties",
        ),
        case(
            "bioavailability-min-negative",
            _put(r, [*_R, "bioavailability", "min"], -1),
            f"{_RP}.bioavailability.min",
            "minimum",
        ),
        case(
            "bioavailability-max-above-100",
            _put(r, [*_R, "bioavailability", "max"], 101),
            f"{_RP}.bioavailability.max",
            "maximum",
        ),
        case(
            "interaction-group-missing-members",
            _cut(g, ["interactionGroups", 0, "members"]),
            "$.interactionGroups[0]",
            "required",
        ),
        case(
            "interaction-group-unknown-property",
            _put(g, ["interactionGroups", 0, "description"], "Stimulants."),
            "$.interactionGroups[0]",
            "additionalProperties",
        ),
        case(
            "interaction-group-id-not-a-slug",
            _put(g, ["interactionGroups", 0, "id"], "Stimulants"),
            "$.interactionGroups[0].id",
            "pattern",
        ),
        case(
            "interaction-group-members-not-a-list",
            _put(g, ["interactionGroups", 0, "members"], "Amphetamine"),
            "$.interactionGroups[0].members",
            "type",
        ),
        case(
            "interactions-missing-uncertain",
            _cut(t, [*_S, "interactions", "uncertain"]),
            f"{_SP}.interactions",
            "required",
        ),
        case(
            "interactions-unknown-severity",
            _put(t, [*_S, "interactions", "safe"], []),
            f"{_SP}.interactions",
            "additionalProperties",
        ),
        case("interaction-target-not-an-object", _put(t, _T, "Ritonavir"), _TP, "oneOf"),
        case("interaction-target-missing-kind", _cut(t, [*_T, "kind"]), _TP, "oneOf"),
        case(
            "interaction-target-group-missing-kind",
            _put(t, _T, {"groupId": "stimulants"}),
            _TP,
            "oneOf",
        ),
        case(
            "interaction-target-kind-not-in-the-list",
            _put(t, [*_T, "kind"], "class"),
            _TP,
            "oneOf",
        ),
        case("other-target-missing-name", _put(t, _T, {"kind": "other"}), _TP, "required"),
        case(
            "other-target-unknown-property",
            _put(t, [*_T, "note"], "CYP3A4 inhibitor"),
            _TP,
            "additionalProperties",
        ),
        case("other-target-name-empty", _put(t, [*_T, "name"], ""), f"{_TP}.name", "pattern"),
        case(
            "substance-target-missing-name",
            _put(t, _T, {"kind": "substance"}),
            _TP,
            "required",
        ),
        case(
            "substance-target-unknown-property-group-id",
            _put(t, _T, {"kind": "substance", "name": "1P-LSD", "groupId": "psychedelics"}),
            _TP,
            "additionalProperties",
        ),
        case(
            "substance-target-name-not-a-string",
            _put(t, _T, {"kind": "substance", "name": ["1P-LSD"]}),
            f"{_TP}.name",
            "type",
        ),
        case(
            "group-target-missing-group-id",
            _put(t, _T, {"kind": "group"}),
            _TP,
            "required",
        ),
        case(
            "group-target-unknown-property-name",
            _put(t, _T, {"kind": "group", "groupId": "stimulants", "name": "Stimulants"}),
            _TP,
            "additionalProperties",
        ),
        case(
            "group-target-group-id-is-a-display-name",
            _put(t, _T, {"kind": "group", "groupId": "Stimulants"}),
            f"{_TP}.groupId",
            "pattern",
        ),
    ]


# ---- manifest.json


def _manifest() -> Any:
    return {
        "datasetVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "minAppVersion": "1.0.0",
        "sha256": "a2300bea9bf8013fc97c4279eeb7393f1800766ec55455ac117502a1208a666f",
        "date": "2026-11-16",
        "attribution": [
            {
                "name": "PsychonautWiki",
                "url": "https://psychonautwiki.org",
                "license": "CC-BY-SA-4.0",
            }
        ],
    }


def manifest_valid() -> dict[str, Any]:
    """Return the valid documents by fixture name."""
    newer = _put(_put(_manifest(), ["schemaVersion"], "2.1.0"), ["minAppVersion"], "3.0.0")
    return {"release": _manifest(), "newer-schema-major": newer}


def manifest_invalid() -> list[InvalidCase]:
    """Return the invalid documents, one per rule."""
    case = InvalidCase
    m = _manifest()
    sha256: str = m["sha256"]
    return [
        case("missing-sha256", _cut(m, ["sha256"]), "$", "required"),
        case(
            "unknown-property",
            _put(m, ["signature"], "c2lnbmF0dXJl"),
            "$",
            "additionalProperties",
        ),
        case(
            "dataset-version-not-semver",
            _put(m, ["datasetVersion"], "1.0"),
            "$.datasetVersion",
            "pattern",
        ),
        case(
            "schema-version-not-semver",
            _put(m, ["schemaVersion"], "1"),
            "$.schemaVersion",
            "pattern",
        ),
        case(
            "min-app-version-not-semver",
            _put(m, ["minAppVersion"], "1.0.0+42"),
            "$.minAppVersion",
            "pattern",
        ),
        case("sha256-uppercase", _put(m, ["sha256"], sha256.upper()), "$.sha256", "pattern"),
        case("sha256-too-short", _put(m, ["sha256"], sha256[:63]), "$.sha256", "pattern"),
        case("sha256-not-a-string", _put(m, ["sha256"], 0), "$.sha256", "type"),
        case("sha256-trailing-newline", _put(m, ["sha256"], sha256 + "\n"), "$.sha256", "pattern"),
        case(
            "dataset-version-trailing-newline",
            _put(m, ["datasetVersion"], "1.0.0\n"),
            "$.datasetVersion",
            "pattern",
        ),
        case(
            "attribution-url-trailing-newline",
            _put(m, ["attribution", 0, "url"], "https://psychonautwiki.org\n"),
            "$.attribution[0].url",
            "pattern",
        ),
        case("date-trailing-newline", _put(m, ["date"], "2026-11-16\n"), "$.date", "format"),
        case("date-not-iso-8601", _put(m, ["date"], "16/11/2026"), "$.date", "format"),
        case("date-with-time", _put(m, ["date"], "2026-11-16T10:00:00Z"), "$.date", "format"),
        case("date-not-a-calendar-day", _put(m, ["date"], "2026-02-30"), "$.date", "format"),
        case("attribution-empty", _put(m, ["attribution"], []), "$.attribution", "minItems"),
        case(
            "attribution-missing-license",
            _cut(m, ["attribution", 0, "license"]),
            "$.attribution[0]",
            "required",
        ),
        case(
            "attribution-unknown-property",
            _put(m, ["attribution", 0, "author"], "Someone"),
            "$.attribution[0]",
            "additionalProperties",
        ),
        case(
            "attribution-url-not-https",
            _put(m, ["attribution", 0, "url"], "ftp://psychonautwiki.org"),
            "$.attribution[0].url",
            "pattern",
        ),
        case(
            "text-only-whitespace",
            _put(m, ["attribution", 0, "name"], "  "),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-leading-whitespace",
            _put(m, ["attribution", 0, "name"], " PsychonautWiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-trailing-whitespace",
            _put(m, ["attribution", 0, "name"], "PsychonautWiki\n"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "text-null-character",
            _put(m, ["attribution", 0, "name"], "Psychonaut\u0000Wiki"),
            "$.attribution[0].name",
            "pattern",
        ),
        case(
            "attribution-license-empty",
            _put(m, ["attribution", 0, "license"], ""),
            "$.attribution[0].license",
            "pattern",
        ),
    ]


# ---- files

VALID = {"substances": substances_valid, "manifest": manifest_valid}
INVALID = {"substances": substances_invalid, "manifest": manifest_invalid}


def _text(document: object) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render() -> dict[str, str]:
    """Return every fixture file as text, keyed by its path relative to the fixture root."""
    files: dict[str, str] = {}
    for schema, valid in VALID.items():
        for name, document in valid().items():
            files[f"{schema}/valid/{name}.json"] = _text(document)
        for case in INVALID[schema]():
            files[f"{schema}/invalid/{case.name}.json"] = _text(case.document)
    return files


def write(root: Path = FIXTURES) -> None:
    """Replace the fixture files under the root with the rendered ones."""
    shutil.rmtree(root, ignore_errors=True)
    for relative, text in render().items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    write()
    print(f"wrote {len(render())} fixture files to {FIXTURES}")
