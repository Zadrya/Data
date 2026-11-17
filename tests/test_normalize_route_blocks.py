# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the dose, duration and bioavailability candidates of one route."""

import pytest

from zadrya_data.base import BaseDose
from zadrya_data.graphql import ApiDose, ApiRange
from zadrya_data.normalize.bioavailability import bioavailability
from zadrya_data.normalize.blocks import Candidate
from zadrya_data.normalize.dose import (
    Dose,
    from_api,
    from_base,
    lost_upper_boundaries,
    require_upper_boundaries,
)
from zadrya_data.normalize.dose import changes as dose_changes
from zadrya_data.normalize.duration import changes as duration_changes
from zadrya_data.normalize.duration import phase
from zadrya_data.normalize.report import Kind


def _api_dose(**fields: object) -> ApiDose:
    values: dict[str, object] = {
        "units": "mg",
        "threshold": None,
        "heavy": None,
        "light": None,
        "common": None,
        "strong": None,
    }
    return ApiDose(**(values | fields))  # type: ignore[arg-type]


def test_an_absent_dose_is_no_candidate() -> None:
    assert from_api(None, None) == Candidate()
    assert from_base(None) == Candidate()
    assert from_api(_api_dose(units=None), None) == Candidate()


@pytest.mark.parametrize(
    ("dose", "problem"),
    [
        (_api_dose(threshold=-1.0), "thresholdMin is negative or not finite"),
        (_api_dose(heavy=float("inf")), "heavyMin is negative or not finite"),
        (_api_dose(threshold=float("nan")), "thresholdMin is negative or not finite"),
        (_api_dose(units="  ", threshold=1.0), "boundaries without usable units"),
        (_api_dose(units="mg\nTHC", threshold=1.0), "boundaries without usable units"),
        (_api_dose(units=None, light=ApiRange(None, 5.0)), "boundaries without usable units"),
        (_api_dose(common=ApiRange(10.0, 20.0), heavy=5.0), "commonMin 10 is above heavyMin 5"),
    ],
)
def test_inconsistent_api_doses(dose: ApiDose, problem: str) -> None:
    assert from_api(dose, None) == Candidate(problem=problem)


def test_a_fill_that_is_not_a_usable_number_is_discarded() -> None:
    dose = _api_dose(common=ApiRange(10.0, 20.0), strong=ApiRange(None, -5.0))

    candidate = from_api(dose, None)

    assert candidate.value == {"units": "mg", "commonMin": 10, "strongMin": 20}
    assert candidate.notes == (
        (Kind.DOSE_BOUNDARY_FILLED, "strongMin 20 filled from common.max"),
        (
            Kind.DOSE_FILL_DISCARDED,
            "heavyMin is not filled from strong.max -5: it is negative or not finite",
        ),
    )


@pytest.mark.parametrize("name", ["light", "common", "strong"])
def test_an_inverted_api_range_makes_the_block_inconsistent(name: str) -> None:
    dose = _api_dose(**{name: ApiRange(40.0, 20.0)}, threshold=1.0)

    assert from_api(dose, None) == Candidate(problem=f"{name}.min 40 is above {name}.max 20")


def test_a_range_with_equal_or_one_bound_is_not_inverted() -> None:
    dose = _api_dose(
        light=ApiRange(5.0, 5.0), common=ApiRange(None, 10.0), strong=ApiRange(20.0, None)
    )

    # commonMin has no direct value, so it is filled from light.max.
    assert from_api(dose, None).value == {
        "units": "mg",
        "lightMin": 5,
        "commonMin": 5,
        "strongMin": 20,
    }


# ---- upper boundaries and changes against the base


def _dose(**values: object) -> Candidate[Dose]:
    return Candidate({"units": "mg"} | values)  # type: ignore[arg-type]


def test_an_api_block_without_an_upper_boundary_of_the_base_is_rejected() -> None:
    api = _dose(thresholdMin=1, commonMin=5, strongMin=10)
    base = _dose(thresholdMin=1, commonMin=5, strongMin=10, heavyMin=20)

    assert require_upper_boundaries(api, base) == Candidate(
        problem="missing upper boundaries the base has (heavyMin)"
    )
    assert require_upper_boundaries(_dose(heavyMin=20), base).problem == (
        "missing upper boundaries the base has (commonMin, strongMin)"
    )


@pytest.mark.parametrize(
    ("api", "base"),
    [
        (_dose(lightMin=2, commonMin=5), _dose(thresholdMin=1, commonMin=5)),
        (_dose(commonMin=5, heavyMin=9), _dose(commonMin=5)),
        (Candidate({"units": "mg"}, weak=True), _dose(heavyMin=9)),
        (_dose(commonMin=5), Candidate({"units": "mg"}, weak=True)),
        (_dose(commonMin=5), Candidate(problem="inverted")),
        (Candidate(problem="inverted"), _dose(heavyMin=9)),
    ],
)
def test_other_differences_keep_the_api_block(api: Candidate[Dose], base: Candidate[Dose]) -> None:
    assert require_upper_boundaries(api, base) is api


def test_lost_upper_boundaries() -> None:
    base = _dose(commonMin=5, strongMin=10, heavyMin=20)

    assert lost_upper_boundaries(base, {"units": "mg", "commonMin": 5}) == ["strongMin", "heavyMin"]
    assert lost_upper_boundaries(base, None) == ["commonMin", "strongMin", "heavyMin"]
    assert lost_upper_boundaries(base, base.value) == []
    assert lost_upper_boundaries(Candidate(problem="inverted"), None) == []
    assert lost_upper_boundaries(Candidate({"units": "mg"}, weak=True), None) == []


def test_dose_changes_name_each_boundary_and_its_direction() -> None:
    base: Dose = {
        "units": "mg",
        "thresholdMin": 1,
        "lightMin": 2,
        "commonMin": 5,
        "strongMin": 10,
        "heavyMin": 20,
    }
    chosen: Dose = {
        "units": "mg",
        "thresholdMin": 1,
        "lightMin": 3,
        "commonMin": 4,
        "strongMin": 12,
        "heavyMin": 25,
    }

    assert dose_changes(chosen, base) == [
        (Kind.DOSE_CHANGED, "lightMin 2 to 3 mg, higher"),
        (Kind.DOSE_CHANGED, "commonMin 5 to 4 mg, lower"),
        (
            Kind.DOSE_CHANGED,
            "strongMin 10 to 12 mg, HIGHER (risky): doses from 10 up to 12 mg now show as "
            "common instead of strong",
        ),
        (
            Kind.DOSE_CHANGED,
            "heavyMin 20 to 25 mg, HIGHER (risky): doses from 20 up to 25 mg now show as "
            "strong instead of heavy",
        ),
    ]
    assert dose_changes(base, base) == []


def test_dose_changes_in_other_units_are_listed_without_a_direction() -> None:
    chosen: Dose = {"units": "g", "commonMin": 1}
    base: Dose = {"units": "mg", "commonMin": 1000, "heavyMin": 5}

    assert dose_changes(chosen, base) == [
        (Kind.UNIT_CHANGED, "units 'mg' to 'g'"),
        (Kind.DOSE_CHANGED, "commonMin 1000 mg to 1 g, in other units: not compared"),
        (Kind.DOSE_BOUNDARY_NOT_IN_API, "heavyMin 5 mg, not in the API block"),
    ]


def test_base_boundaries_missing_from_the_api_dose_are_findings() -> None:
    chosen: Dose = {"units": "mg", "lightMin": 2, "commonMin": 5}
    base: Dose = {"units": "mg", "thresholdMin": 2, "commonMin": 5, "heavyMin": 20}

    assert dose_changes(chosen, base) == [
        (Kind.DOSE_BOUNDARY_NOT_IN_API, "thresholdMin 2 mg, not in the API block"),
        (Kind.DOSE_BOUNDARY_NOT_IN_API, "heavyMin 20 mg, not in the API block"),
    ]


def test_base_bounds_missing_from_the_api_phase_are_findings() -> None:
    assert duration_changes("total", {"min": 60}, {"min": 60, "max": 240}) == [
        (Kind.DURATION_BOUND_NOT_IN_API, "total max 240 minutes, not in the API phase"),
    ]
    assert duration_changes("onset", {"max": 30}, {"min": 10, "max": 30}) == [
        (Kind.DURATION_BOUND_NOT_IN_API, "onset min 10 minutes, not in the API phase"),
    ]


def test_duration_changes_name_each_bound_and_its_direction() -> None:
    assert duration_changes("total", {"min": 60, "max": 300}, {"min": 120, "max": 240}) == [
        (Kind.DURATION_CHANGED, "total min 120 to 60 minutes, lower"),
        (Kind.DURATION_CHANGED, "total max 240 to 300 minutes, higher"),
    ]
    assert duration_changes("peak", {"min": 60}, {"max": 90}) == [
        (Kind.DURATION_BOUND_NOT_IN_API, "peak max 90 minutes, not in the API phase"),
    ]
    assert duration_changes("peak", {"min": 0.75}, {"min": 0.75}) == []


def test_a_label_difference_needs_a_lowest_base_boundary() -> None:
    dose = _api_dose(light=ApiRange(1.0, 2.0))

    assert from_api(dose, BaseDose("mg", None, 5, None, None)).notes == (
        (Kind.DOSE_BOUNDARY_FILLED, "commonMin 2 filled from light.max"),
    )
    assert [kind for kind, _ in from_api(dose, BaseDose("mg", 1, None, None, None)).notes] == [
        Kind.DOSE_BOUNDARY_FILLED,
        Kind.DOSE_LABEL_DIFFERS,
    ]


def test_a_base_dose_with_units_only_is_weak() -> None:
    assert from_base(BaseDose("mg", None, None, None, None)) == Candidate(
        {"units": "mg"}, weak=True
    )
    assert (
        from_base(BaseDose("mg", 5, 4, None, None)).problem == "thresholdMin 5 is above commonMin 4"
    )


@pytest.mark.parametrize(
    ("low", "high", "units", "problem"),
    [
        (-1.0, 2.0, "hours", "min is negative or not finite"),
        (1.0, float("inf"), "hours", "max is negative or not finite"),
        (3.0, 2.0, "hours", "min 3 is above max 2 hours"),
        (1.0, 2.0, None, "numbers with no unit"),
        (1.0, None, "weeks", "numbers with the unknown unit 'weeks'"),
    ],
)
def test_inconsistent_phases(
    low: float | None, high: float | None, units: str | None, problem: str
) -> None:
    assert phase(low, high, units) == Candidate(problem=problem)


def test_phase_units_match_without_case_and_with_padding() -> None:
    assert phase(1.0, 2.0, " HOURS ").value == {"min": 60, "max": 120}
    assert phase(1.0, None, "Day").value == {"min": 1440}
    assert phase(None, None, "fortnights") == Candidate()


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (None, None, Candidate()),
        (71.0, 71.0, Candidate({"min": 71, "max": 71})),
        (None, 100.0, Candidate({"max": 100})),
        (0.0, None, Candidate({"min": 0})),
        (-1.0, 50.0, Candidate(problem="min -1 is not within 0 to 100")),
        (50.0, 100.5, Candidate(problem="max 100.5 is not within 0 to 100")),
        (60.0, 50.0, Candidate(problem="min 60 is above max 50")),
    ],
)
def test_bioavailability(
    low: float | None, high: float | None, expected: Candidate[dict[str, float]]
) -> None:
    assert bioavailability(low, high) == expected
