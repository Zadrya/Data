# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the dose, duration and bioavailability candidates of one route."""

import pytest

from zadrya_data.base import BaseDose
from zadrya_data.graphql import ApiDose, ApiRange
from zadrya_data.normalize.bioavailability import bioavailability
from zadrya_data.normalize.blocks import Candidate
from zadrya_data.normalize.dose import from_api, from_base
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
    dose = _api_dose(common=ApiRange(10.0, 20.0), strong=ApiRange(20.0, -5.0))

    candidate = from_api(dose, None)

    assert candidate.value == {"units": "mg", "commonMin": 10, "strongMin": 20}
    assert candidate.notes == (
        (
            Kind.DOSE_FILL_DISCARDED,
            "heavyMin is not filled from strong.max -5: it is negative or not finite",
        ),
    )


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
