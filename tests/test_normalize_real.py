# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalization of the real base file with the recorded API answers. No network.

Two recordings are used: ``graphql.json`` (seven whole entries) and
``graphql-doses.json`` (the dose blocks of every substance whose dose normalization
does something worth pinning in the snapshot of 2026-11-16: a filled boundary, a label
difference, an inconsistent block or range, a change against the base file, a
repaired, qualified or non-mass unit).
"""

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.api_fixtures import recorded
from zadrya_data import graphql
from zadrya_data.base import BaseFile, load_base
from zadrya_data.mediawiki import WikiPage
from zadrya_data.normalize import Kind, NormalizationError, Normalized, normalize
from zadrya_data.normalize.routes import route_order
from zadrya_data.schema import SCHEMA_VERSION, SchemaName, validate
from zadrya_data.snapshot import Snapshot, dump_json

BASE_FILE = Path(__file__).parents[1] / "sources" / "base" / "Substances.json"
MISSING_PAGES = (
    "Apomorphine",
    "Bromazolam",
    "Chlordiazepoxide",
    "Cinolazepam",
    "Etomidate",
    "Oxazepam",
    "Phenazepam",
    "Tilidin",
    "Triazolam",
)


@pytest.fixture(scope="module")
def base() -> BaseFile:
    return load_base(BASE_FILE)


def _snapshot(base: BaseFile, recording: str) -> Snapshot:
    """Build a snapshot from a recorded answer, with a page for every name but the nine missing."""
    substances = graphql.parse_data(recorded(recording)["data"])
    names = sorted({s.name for s in base.substances} | {s.name for s in substances})
    pages = tuple(
        (
            WikiPage(name, name, False, None, None, None)
            if name in MISSING_PAGES
            else WikiPage(name, name, True, number, number, "2026-01-01T00:00:00Z")
        )
        for number, name in enumerate(names, start=1)
    )
    base_names = tuple(sorted(s.name for s in base.substances))
    return Snapshot(substances, pages, base_names, date(2026, 11, 16), {})


@pytest.fixture(scope="module")
def whole(base: BaseFile) -> Normalized:
    return normalize(base, _snapshot(base, "graphql.json"))


@pytest.fixture(scope="module")
def doses(base: BaseFile) -> Normalized:
    return normalize(base, _snapshot(base, "graphql-doses.json"))


def _by_name(result: Normalized) -> dict[str, dict[str, Any]]:
    return {substance["name"]: substance for substance in result.document["substances"]}


def _document(result: Normalized) -> dict[str, Any]:
    attribution = [
        {"name": "PsychonautWiki", "url": "https://psychonautwiki.org", "license": "CC-BY-SA-4.0"}
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "datasetVersion": "0.0.0",
        "attribution": attribution,
    } | result.document


@pytest.mark.parametrize("recording", ["whole", "doses"])
def test_output_validates_against_the_schema(
    recording: str, request: pytest.FixtureRequest
) -> None:
    result: Normalized = request.getfixturevalue(recording)

    assert validate(_document(result), SchemaName.SUBSTANCES) == []


def test_same_input_gives_the_same_bytes_and_the_same_report(base: BaseFile) -> None:
    one = normalize(base, _snapshot(base, "graphql.json"))
    two = normalize(base, _snapshot(base, "graphql.json"))

    assert dump_json(one.document) == dump_json(two.document)
    assert one.report.findings == two.report.findings


def test_every_base_substance_is_in_the_catalog(base: BaseFile, whole: Normalized) -> None:
    names = [substance["name"] for substance in whole.document["substances"]]

    assert len(names) == 289
    assert set(names) == {substance.name for substance in base.substances}
    assert names == sorted(names)


def test_categories_are_the_base_categories(base: BaseFile, whole: Normalized) -> None:
    categories = whole.document["categories"]

    assert [category["id"] for category in categories] == [c.name for c in base.categories]
    assert all(set(category) == {"id", "name", "description"} for category in categories)
    assert categories[0]["name"] == "common"
    assert categories[0]["description"].startswith("Common drugs are those which are well known")
    used = {c for substance in whole.document["substances"] for c in substance["categories"]}
    assert used <= {category["id"] for category in categories}
    assert whole.report.of(Kind.CATEGORY_UNKNOWN) == []


def test_routes_and_lists_are_in_their_documented_order(whole: Normalized) -> None:
    order = {route: index for index, route in enumerate(route_order())}

    for substance in whole.document["substances"]:
        routes = [order[route["route"]] for route in substance["roas"]]
        assert routes == sorted(routes)
        assert len(set(routes)) == len(routes)
        lowered = [alias.casefold() for alias in substance["aliases"]]
        assert len(set(lowered)) == len(lowered)
        assert substance["name"].casefold() not in lowered


def test_lsd_is_merged_from_both_sources(whole: Normalized) -> None:
    lsd = _by_name(whole)["LSD"]

    assert lsd["url"] == "https://psychonautwiki.org/wiki/LSD"
    assert lsd["aliases"] == ["LSD-25", "Lucy", "L", "Acid", "Cid", "Tabs", "Blotter"]
    assert lsd["categories"] == ["psychedelic", "common"]
    assert lsd["classes"] == {"psychoactive": ["Psychedelic"], "chemical": ["Lysergamides"]}
    assert lsd["summary"].startswith("LSD is a popular psychedelic")
    assert "\n" in lsd["generalRisks"]
    assert len(lsd["saferUse"]) == 12
    assert lsd["addictionPotential"] == "non-addictive with a low abuse potential"
    assert lsd["toxicities"] == ["extremely low toxicity relative to dose"]
    assert lsd["roas"] == [
        {
            "route": "sublingual",
            "dose": {
                "units": "µg",
                "thresholdMin": 15,
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
        }
    ]


def test_odd_values_of_the_recording_are_handled_and_reported(whole: Normalized) -> None:
    by_name = _by_name(whole)
    findings = {(f.kind, f.substance, f.route) for f in whole.report.findings}

    assert by_name["Clonidine"]["roas"][0]["dose"]["units"] == "µg"
    assert (Kind.UNIT_REPAIRED, "Clonidine", "oral") in findings
    assert (Kind.API_PHASE_IGNORED, "MDAI", "oral") in findings
    assert "duration" in by_name["MDAI"]["roas"][0]
    # Phenylpiracetam: a peak with the unit "hour" and no numbers is absent, not an error.
    assert by_name["Phenylpiracetam"]["roas"][0]["duration"] == {
        "onset": {"min": 30, "max": 60},
        "total": {"min": 120, "max": 180},
    }
    assert (Kind.API_ENTRY_DROPPED, "2C-x", None) in findings
    assert "2C-x" not in by_name


def test_substances_the_api_lacks_keep_their_base_data(whole: Normalized) -> None:
    by_name = _by_name(whole)
    base_only = {f.substance for f in whole.report.of(Kind.BASE_ONLY)}
    missing = {f.substance for f in whole.report.of(Kind.WIKI_PAGE_MISSING)}

    assert set(MISSING_PAGES) == missing
    assert missing <= base_only and len(base_only) == 289 - 6
    oxazepam = by_name["Oxazepam"]
    assert oxazepam["url"] == "https://psychonautwiki.org/wiki/Oxazepam"
    assert oxazepam["classes"] == {"psychoactive": [], "chemical": []}
    assert oxazepam["roas"][0]["dose"]["units"] == "mg"
    assert "lightMin" not in oxazepam["roas"][0]["dose"]


def test_summaries_come_from_the_base_file_only(base: BaseFile, whole: Normalized) -> None:
    without = {substance.name for substance in base.substances if substance.summary is None}
    reported = {f.substance for f in whole.report.of(Kind.NO_SUMMARY)}

    assert len(without) == 77 and reported == without
    for substance in whole.document["substances"]:
        assert ("summary" in substance) == (substance["name"] not in without)
        assert "Summary sheet" not in substance.get("summary", "")


def test_numbers_are_whole_or_short_decimals(whole: Normalized, doses: Normalized) -> None:
    def numbers(node: object) -> list[int | float]:
        if isinstance(node, dict):
            return [n for value in node.values() for n in numbers(value)]
        if isinstance(node, list):
            return [n for value in node for n in numbers(value)]
        return [node] if isinstance(node, (int, float)) and not isinstance(node, bool) else []

    found = numbers(whole.document["substances"]) + numbers(doses.document["substances"])

    assert len(found) > 3000
    for number in found:
        assert not (isinstance(number, float) and number.is_integer())
        assert number >= 0 and len(repr(number)) <= 8


# ---- dose boundaries on the real dose blocks


def test_dose_fills_of_the_recorded_snapshot(doses: Normalized) -> None:
    fills = Counter(f.detail.split()[1] for f in doses.report.of(Kind.DOSE_BOUNDARY_FILLED))

    assert fills == {"heavyMin": 41, "strongMin": 11}
    assert doses.report.of(Kind.DOSE_FILL_DISCARDED) == []
    assert len(doses.report.of(Kind.DOSE_LABEL_DIFFERS)) == 8


@pytest.mark.parametrize(
    ("name", "route", "dose"),
    [
        (
            "Fentanyl",
            "insufflated",
            {
                "units": "µg",
                "thresholdMin": 5,
                "lightMin": 10,
                "commonMin": 25,
                "strongMin": 50,
                "heavyMin": 75,
            },
        ),
        (
            "25I-NBOMe",
            "sublingual",
            {
                "units": "µg",
                "thresholdMin": 50,
                "lightMin": 200,
                "commonMin": 500,
                "strongMin": 700,
                "heavyMin": 1000,
            },
        ),
        (
            "PCP",
            "smoked",
            {
                "units": "mg",
                "thresholdMin": 1,
                "lightMin": 2,
                "commonMin": 4,
                "strongMin": 8,
                "heavyMin": 12,
            },
        ),
        (
            "Pentobarbital",
            "oral",
            {
                "units": "mg",
                "thresholdMin": 25,
                "lightMin": 50,
                "commonMin": 100,
                "strongMin": 200,
                "heavyMin": 300,
            },
        ),
        (
            "PMA",
            "oral",
            {"units": "mg", "thresholdMin": 10, "lightMin": 20, "commonMin": 40, "strongMin": 60},
        ),
        ("Naloxone", "intravenous", {"units": "mg", "commonMin": 0.4, "strongMin": 2}),
        (
            "1P-LSD",
            "oral",
            {
                "units": "µg",
                "thresholdMin": 15,
                "lightMin": 25,
                "commonMin": 75,
                "strongMin": 150,
                "heavyMin": 300,
            },
        ),
        (
            "25I-NBOMe",
            "insufflated",
            {
                "units": "µg",
                "thresholdMin": 50,
                "lightMin": 200,
                "commonMin": 500,
                "strongMin": 700,
            },
        ),
        (
            "Diphenidine",
            "smoked",
            {"units": "mg", "commonMin": 20, "strongMin": 40, "heavyMin": 55},
        ),
        (
            "4-HO-DET",
            "oral",
            {
                "units": "mg",
                "thresholdMin": 5,
                "lightMin": 10,
                "commonMin": 20,
                "strongMin": 30,
                "heavyMin": 45,
            },
        ),
        (
            "Oxycodone",
            "intravenous",
            {
                "units": "mg",
                "thresholdMin": 1,
                "lightMin": 2.5,
                "commonMin": 7.5,
                "strongMin": 12.5,
                "heavyMin": 15,
            },
        ),
    ],
)
def test_reference_doses(doses: Normalized, name: str, route: str, dose: dict[str, Any]) -> None:
    routes = {r["route"]: r for r in _by_name(doses)[name]["roas"]}

    assert routes[route]["dose"] == dose


def test_inconsistent_doses_are_dropped_and_reported(doses: Normalized) -> None:
    by_name = _by_name(doses)
    dropped = {(f.substance, f.route): f.detail for f in doses.report.of(Kind.BLOCK_DROPPED)}

    assert set(dropped) == {("Meclofenoxate", "oral"), ("Tizanidine", "oral")}
    assert "dose" not in by_name["Meclofenoxate"]["roas"][0]
    assert "strongMin 800 is above heavyMin 600" in dropped[("Meclofenoxate", "oral")]
    assert "thresholdMin 25 is above lightMin 2" in dropped[("Tizanidine", "oral")]


def test_an_allowed_api_entry_left_without_numbers_is_dropped(doses: Normalized) -> None:
    """In this recording Tizanidine has only its dose, which is inconsistent."""
    assert "Tizanidine" not in _by_name(doses)
    details = [
        f.detail for f in doses.report.of(Kind.API_ENTRY_DROPPED) if f.substance == "Tizanidine"
    ]
    assert details == [
        "not in the base file and no route with a number is left after normalization"
    ]


def test_real_dose_blocks_against_the_base_file(doses: Normalized) -> None:
    """The upper-boundary rule changes no real route; an inverted range and real changes are reported.

    Normalization itself stops if a base upper boundary is ever lost without a rejection
    (``test_the_guard_stops_a_route_that_lost_an_upper_boundary_of_the_base``), so a
    successful run over the real data is the regression guard.
    """
    rejected = {(f.substance, f.route): f.detail for f in doses.report.of(Kind.API_BLOCK_REJECTED)}
    changed = [(f.substance, f.route, f.detail) for f in doses.report.of(Kind.DOSE_CHANGED)]

    assert rejected == {
        ("HXE", "insufflated"): "dose: light.min 40 is above light.max 20; the base block is used"
    }
    assert {r["route"]: r for r in _by_name(doses)["HXE"]["roas"]}["insufflated"]["dose"] == {
        "units": "mg",
        "thresholdMin": 20,
        "commonMin": 40,
        "strongMin": 70,
        "heavyMin": 120,
    }
    assert changed == [
        ("Clonazolam", "oral", "dose: commonMin 200 to 125 µg, lower"),
        ("Clonazolam", "oral", "dose: strongMin 400 to 300 µg, lower"),
        ("Clonazolam", "oral", "dose: heavyMin 999 to 500 µg, lower"),
        ("N-Ethylhexedrone", "insufflated", "dose: commonMin 30 to 24 mg, lower"),
        ("N-Ethylhexedrone", "insufflated", "dose: strongMin 40 to 30 mg, lower"),
        ("N-Ethylhexedrone", "insufflated", "dose: heavyMin 50 to 40 mg, lower"),
    ]
    # The base threshold the API block lacks is reported on the eight routes that also
    # carry a label difference: the API states the same number as lightMin.
    not_in_api = sorted(
        (f.substance, f.route) for f in doses.report.of(Kind.DOSE_BOUNDARY_NOT_IN_API)
    )
    label = sorted((f.substance, f.route) for f in doses.report.of(Kind.DOSE_LABEL_DIFFERS))
    assert len(not_in_api) == 8 and not_in_api == label
    assert doses.report.of(Kind.UNIT_CHANGED) == []
    # Meclofenoxate oral is inconsistent in both sources, so it is dropped, not reported
    # as an inconsistent base block next to a used API block.
    assert doses.report.of(Kind.BASE_BLOCK_INCONSISTENT) == []
    assert doses.report.of(Kind.UNIT_QUALIFIER_NOT_ADOPTED) == []


def test_units_other_than_mass_are_reported_and_kept(doses: Normalized) -> None:
    found = sorted(
        (f.substance, f.route, f.detail.split("'")[1]) for f in doses.report.of(Kind.UNIT_NOT_MASS)
    )

    assert found == [
        ("1,4-Butanediol", "oral", "mL"),
        ("2M2B", "oral", "mL"),
        ("Apomorphine", "subcutaneous", "Mg#"),
        ("Cannabis", "oral", "mg THC"),
        ("Cannabis", "smoked", "mg THC"),
        ("GBL", "oral", "mL"),
        ("Ibogaine", "oral", "mg/kg of body weight"),
        ("LSA", "oral", "seeds"),
        ("LSA", "sublingual", "seeds"),
        ("Psilocybin mushrooms", "oral", "mg Psilocybin"),
    ]
    repaired = sorted((f.substance, f.route) for f in doses.report.of(Kind.UNIT_REPAIRED))
    assert repaired == [
        ("Clonidine", "oral"),
        ("Fentanyl", "insufflated"),
        ("Fentanyl", "sublingual"),
        ("Fentanyl", "transdermal"),
        ("Flubromazolam", "oral"),
        ("Sufentanil", "intravenous"),
    ]


def test_a_snapshot_fetched_with_another_base_file_is_refused(base: BaseFile) -> None:
    snapshot = _snapshot(base, "graphql.json")
    pages = tuple(page for page in snapshot.pages if page.requested != "LSD")
    other = Snapshot(snapshot.substances, pages, snapshot.base_names, snapshot.fetched_on, {})

    with pytest.raises(NormalizationError, match="no wiki record for 'LSD'"):
        normalize(base, other)
