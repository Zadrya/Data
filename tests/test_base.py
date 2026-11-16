# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the vendored base file and its typed loader."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from zadrya_data.base import (
    BaseBioavailability,
    BaseCategory,
    BaseDose,
    BaseDuration,
    BaseDurationRange,
    BaseFile,
    BaseFormatError,
    BaseInteractions,
    BaseRoute,
    BaseTolerance,
    load_base,
    parse_base,
)

BASE_FILE = Path(__file__).parents[1] / "sources" / "base" / "Substances.json"
FIXTURES = Path(__file__).parent / "fixtures" / "base"


@pytest.fixture(scope="module")
def base() -> BaseFile:
    return load_base(BASE_FILE)


def _minimal() -> Any:
    return json.loads((FIXTURES / "minimal.json").read_text(encoding="utf-8"))


def test_real_file_has_the_known_counts(base: BaseFile) -> None:
    routes = [route for substance in base.substances for route in substance.roas]

    assert len(base.categories) == 21
    assert len(base.substances) == 289
    assert len({substance.name for substance in base.substances}) == 289
    assert len(routes) == 401
    assert sum(route.dose is not None for route in routes) == 394
    assert sum(route.duration is not None for route in routes) == 387
    assert sum(route.bioavailability is not None for route in routes) == 12
    assert sum(substance.interactions is not None for substance in base.substances) == 205
    assert sum(substance.is_approved for substance in base.substances) == 266


def test_real_file_keeps_names_and_order(base: BaseFile) -> None:
    assert base.substances[0].name == "1,4-Butanediol"
    assert base.substances[-1].name == "Βk-2C-B"
    assert base.categories[0] == BaseCategory(
        name="common",
        description=(
            "Common drugs are those which are well known and widely used among the drug "
            "community. This doesn't necessarily mean they are safe, but it usually comes "
            "with a longer relative history of use in humans with which to establish a "
            "safety profile."
        ),
        color=4278876927,
        url=None,
    )


def test_real_file_route_names(base: BaseFile) -> None:
    names = Counter(route.name for substance in base.substances for route in substance.roas)

    assert names == {
        "oral": 255,
        "insufflated": 64,
        "smoked": 39,
        "sublingual": 18,
        "intravenous": 13,
        "rectal": 6,
        "inhaled": 2,
        "subcutaneous": 1,
        "transdermal": 1,
        "intramuscular": 1,
        "buccal": 1,
    }


def test_reference_case_lsd(base: BaseFile) -> None:
    """LSD, checked by hand against the file: its only route is sublingual."""
    lsd = next(substance for substance in base.substances if substance.name == "LSD")

    assert lsd.common_names == ("LSD", "LSD-25", "Lucy", "L", "Acid", "Cid", "Tabs", "Blotter")
    assert lsd.url == "https://psychonautwiki.org/wiki/LSD"
    assert lsd.is_approved is True
    assert lsd.tolerance == BaseTolerance(
        full="almost immediately after ingestion", half=None, zero="5 days"
    )
    assert lsd.cross_tolerances == ("psychedelics",)
    assert lsd.addiction_potential == "non-addictive with a low abuse potential"
    assert lsd.toxicities == ("extremely low toxicity relative to dose",)
    assert lsd.categories == ("psychedelic", "common")
    assert lsd.summary is not None and lsd.summary.startswith("LSD is a popular psychedelic")
    assert lsd.effects_summary is not None and lsd.general_risks is not None
    assert lsd.dosage_remark is None and lsd.longterm_risks is None
    assert lsd.safer_use is not None and len(lsd.safer_use) == 12
    assert lsd.safer_use[4] == "Dose low. Don't throw it if it doesn't work right away!"
    assert lsd.interactions == BaseInteractions(
        dangerous=("Lithium",),
        unsafe=("Tramadol", "Deliriant", "Tricyclic antidepressants", "Ritonavir"),
        uncertain=("Cannabis", "Stimulants"),
    )
    assert lsd.roas == (
        BaseRoute(
            name="sublingual",
            dose=BaseDose(units="µg", light_min=15, common_min=75, strong_min=150, heavy_min=300),
            duration=BaseDuration(
                onset=BaseDurationRange(min=15, max=30, units="minutes"),
                comeup=BaseDurationRange(min=45, max=90, units="minutes"),
                peak=BaseDurationRange(min=3, max=5, units="hours"),
                offset=BaseDurationRange(min=3, max=5, units="hours"),
                total=BaseDurationRange(min=8, max=12, units="hours"),
                afterglow=BaseDurationRange(min=12, max=48, units="hours"),
            ),
            bioavailability=BaseBioavailability(min=71, max=71),
        ),
    )


def test_numbers_keep_their_value_and_type(base: BaseFile) -> None:
    lsd = next(substance for substance in base.substances if substance.name == "LSD")
    butanediol = base.substances[0]
    lsd_dose, butanediol_dose = lsd.roas[0].dose, butanediol.roas[0].dose

    assert lsd_dose is not None and type(lsd_dose.light_min) is int
    assert butanediol_dose is not None and butanediol_dose.light_min == 0.5
    assert type(butanediol_dose.light_min) is float


def test_absent_and_empty_are_kept_apart(base: BaseFile) -> None:
    by_name = {substance.name: substance for substance in base.substances}

    assert by_name["Poppers"].roas == ()
    assert by_name["Dextromethorphan"].safer_use == ()
    assert by_name["1,4-Butanediol"].safer_use is None
    assert by_name["3C-P"].common_names == ()


def test_one_sided_ranges_are_kept(base: BaseFile) -> None:
    by_name = {substance.name: substance for substance in base.substances}
    bromantane = by_name["Bromantane"].roas[0]
    duration = next(r for r in by_name["4-AcO-DMT"].roas if r.name == "insufflated").duration

    assert bromantane.bioavailability == BaseBioavailability(min=None, max=42)
    assert duration is not None
    assert duration.afterglow == BaseDurationRange(min=2, max=None, units="hours")


def test_missing_optional_fields_load_as_none() -> None:
    base = load_base(FIXTURES / "minimal.json")
    substance = base.substances[0]

    assert base.categories[0].url is None
    assert substance.tolerance is None
    assert substance.addiction_potential is None
    assert substance.summary is None
    assert substance.effects_summary is None
    assert substance.dosage_remark is None
    assert substance.general_risks is None
    assert substance.longterm_risks is None
    assert substance.safer_use is None
    assert substance.interactions is None
    assert substance.roas[0] == BaseRoute(
        name="oral", dose=None, duration=None, bioavailability=None
    )
    assert substance.roas[1] == BaseRoute(
        name="insufflated",
        dose=BaseDose(units="mg", light_min=None, common_min=None, strong_min=None, heavy_min=None),
        duration=BaseDuration(
            onset=None,
            comeup=None,
            peak=None,
            offset=None,
            total=BaseDurationRange(min=2, max=None, units="hours"),
            afterglow=None,
        ),
        bioavailability=BaseBioavailability(min=None, max=45),
    )


UNKNOWN_KEY_FIXTURES = [
    ("unknown-top-level-key", "$: unknown key(s) 'version'"),
    ("unknown-category-key", "$.categories[0]: unknown key(s) 'icon'"),
    ("unknown-substance-key", "$.substances[0]: unknown key(s) 'halfLife'"),
    ("unknown-tolerance-key", "$.substances[0].tolerance: unknown key(s) 'quarter'"),
    ("unknown-interactions-key", "$.substances[0].interactions: unknown key(s) 'safe'"),
    ("unknown-route-key", "$.substances[0].roas[0]: unknown key(s) 'halfLife'"),
    ("unknown-dose-key", "$.substances[0].roas[0].dose: unknown key(s) 'threshold'"),
    ("unknown-duration-key", "$.substances[0].roas[0].duration: unknown key(s) 'hangover'"),
    (
        "unknown-duration-range-key",
        "$.substances[0].roas[0].duration.onset: unknown key(s) 'note'",
    ),
    (
        "unknown-bioavailability-key",
        "$.substances[0].roas[0].bioavailability: unknown key(s) 'units'",
    ),
]


@pytest.mark.parametrize(("fixture", "message"), UNKNOWN_KEY_FIXTURES)
def test_unknown_keys_fail_loudly(fixture: str, message: str) -> None:
    with pytest.raises(BaseFormatError) as error:
        load_base(FIXTURES / f"{fixture}.json")

    assert str(error.value) == message


def test_every_unknown_key_fixture_is_tested() -> None:
    tested = {fixture for fixture, _ in UNKNOWN_KEY_FIXTURES}

    assert {path.stem for path in FIXTURES.glob("unknown-*.json")} == tested


def test_several_unknown_keys_are_all_named() -> None:
    document = _minimal()
    document["substances"][0] |= {"zeta": 1, "alpha": 2}

    with pytest.raises(BaseFormatError, match=r"unknown key\(s\) 'alpha', 'zeta'"):
        parse_base(document)


def _set(path: list[str | int], value: object) -> Any:
    document = _minimal()
    target = document
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return document


def _without(path: list[str | int]) -> Any:
    document = _minimal()
    target = document
    for step in path[:-1]:
        target = target[step]
    del target[path[-1]]
    return document


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "$: expected an object, found a list"),
        (None, "$: expected an object, found null"),
        (_without(["categories"]), "$: missing key 'categories'"),
        (_without(["substances", 0, "isApproved"]), "$.substances[0]: missing key 'isApproved'"),
        (
            _without(["substances", 0, "roas", 1, "dose", "units"]),
            "$.substances[0].roas[1].dose: missing key 'units'",
        ),
        (
            _set(["substances", 0, "name"], 7),
            "$.substances[0].name: expected a string, found a number",
        ),
        (
            _set(["substances", 0, "summary"], None),
            "$.substances[0].summary: expected a value, found null",
        ),
        (
            _set(["substances", 0, "isApproved"], "yes"),
            "$.substances[0].isApproved: expected a boolean, found a string",
        ),
        (
            _set(["substances", 0, "commonNames"], "Example"),
            "$.substances[0].commonNames: expected a list, found a string",
        ),
        (
            _set(["substances", 0, "commonNames"], ["Example", {}]),
            "$.substances[0].commonNames[1]: expected a string, found an object",
        ),
        (
            _set(["substances", 0, "roas"], ["oral"]),
            "$.substances[0].roas[0]: expected an object, found a string",
        ),
        (
            _set(["categories", 0, "color"], True),
            "$.categories[0].color: expected an integer, found a boolean",
        ),
        (
            _set(["categories", 0, "color"], 1.5),
            "$.categories[0].color: expected an integer, found a number",
        ),
        (
            _set(["substances", 0, "roas", 1, "dose", "lightMin"], "5"),
            "$.substances[0].roas[1].dose.lightMin: expected a number, found a string",
        ),
        (
            _set(["substances", 0, "roas", 1, "dose", "lightMin"], float("nan")),
            "$.substances[0].roas[1].dose.lightMin: expected a finite number, found nan",
        ),
        (
            _set(["substances", 0, "roas", 1, "bioavailability", "max"], False),
            "$.substances[0].roas[1].bioavailability.max: expected a number, found a boolean",
        ),
    ],
)
def test_wrong_shapes_fail_with_the_path(document: object, message: str) -> None:
    with pytest.raises(BaseFormatError) as error:
        parse_base(document)

    assert str(error.value) == message


def test_a_file_that_is_not_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "Substances.json"
    path.write_text('{"categories": [', encoding="utf-8")

    with pytest.raises(BaseFormatError, match="not valid JSON"):
        load_base(path)


@pytest.mark.parametrize(
    ("number", "reason"),
    [
        ("NaN", "NaN is not a JSON number"),
        ("Infinity", "Infinity is not a JSON number"),
        ("-Infinity", "-Infinity is not a JSON number"),
    ],
)
def test_constants_that_are_not_json_numbers_fail(tmp_path: Path, number: str, reason: str) -> None:
    path = tmp_path / "Substances.json"
    text = (FIXTURES / "minimal.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"max": 45', f'"max": {number}'), encoding="utf-8")

    with pytest.raises(BaseFormatError, match=reason):
        load_base(path)


def test_a_float_out_of_range_fails_with_the_path(tmp_path: Path) -> None:
    path = tmp_path / "Substances.json"
    text = (FIXTURES / "minimal.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"max": 45', '"max": 1e999'), encoding="utf-8")

    with pytest.raises(BaseFormatError) as error:
        load_base(path)

    assert str(error.value) == (
        "$.substances[0].roas[1].bioavailability.max: expected a finite number, found inf"
    )


def test_a_repeated_key_fails_instead_of_keeping_the_last_value(tmp_path: Path) -> None:
    path = tmp_path / "Substances.json"
    text = (FIXTURES / "minimal.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"max": 45', '"max": 45, "max": 90'), encoding="utf-8")

    with pytest.raises(BaseFormatError, match="duplicate key 'max'"):
        load_base(path)
