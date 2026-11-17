# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the building blocks of normalization: numbers, text, the merge policy, the report."""

from fractions import Fraction

import pytest

from zadrya_data.normalize import text
from zadrya_data.normalize.blocks import Candidate, choose
from zadrya_data.normalize.numbers import exact, plain, rounded
from zadrya_data.normalize.report import Kind, Report

# ---- numbers


@pytest.mark.parametrize(
    ("value", "written"),
    [(15.0, 15), (15, 15), (0.1, 0.1), (2.5, 2.5), (0.0, 0), (1e-05, 1e-05)],
)
def test_numbers_are_written_whole_or_as_the_shortest_decimal(value: float, written: float) -> None:
    result = plain(exact(value))

    assert result == written and type(result) is type(written)


def test_exact_arithmetic_has_no_binary_noise() -> None:
    assert exact(0.1) + exact(0.2) == Fraction(3, 10)
    assert plain(exact(0.1) * 60) == 6
    assert plain(exact(45.0) / 60) == 0.75


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        (Fraction(1, 12), 0.0833),
        (Fraction(1, 3), 0.3333),
        (Fraction(2, 3), 0.6667),
        (Fraction(5, 100000), 0),
        (Fraction(15, 100000), 0.0002),
        (Fraction(3, 4), 0.75),
    ],
)
def test_rounding_keeps_four_decimal_places_half_to_even(value: Fraction, kept: float) -> None:
    assert plain(rounded(value)) == kept


# ---- text


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("  plain  ", "plain"),
        ("﻿ padded\n\t", "padded"),
        ("two  spaces", "two  spaces"),
        ("no break", "no break"),
        ("line\nbreak", None),
        ("", None),
        (" \n ", None),
        ("nul\u0000l", None),
    ],
)
def test_single_line_text(raw: str, cleaned: str | None) -> None:
    assert text.line(raw) == cleaned


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("\nOne.\nTwo.\n", "One.\nTwo."),
        ("One.\n\nTwo.", "One.\n\nTwo."),
        ("One.\r\nTwo.", None),
        ("One.\tTwo.", None),
        ("   ", None),
    ],
)
def test_text_of_paragraphs(raw: str, cleaned: str | None) -> None:
    assert text.paragraphs(raw) == cleaned


def test_rejected_text_is_described_printably() -> None:
    assert text.describe("a\tb\u0000") == "'a\\tb\\x00'"
    assert text.describe("   ") == "(empty)"
    assert len(text.describe("x" * 500)) == 42


# ---- the merge policy


def _choose(
    api: Candidate[str], base: Candidate[str], *, both: bool = True
) -> tuple[str | None, list[tuple[Kind, str]]]:
    report = Report()
    value = choose(
        api, base, what="dose", substance="LSD", route="oral", in_both_sources=both, report=report
    )
    return value, [(finding.kind, finding.detail) for finding in report.findings]


def test_a_consistent_api_block_wins_silently() -> None:
    assert _choose(Candidate("api"), Candidate("base")) == ("api", [])


def test_the_notes_of_the_chosen_candidate_are_reported_and_no_others() -> None:
    api = Candidate("api", notes=((Kind.UNIT_REPAIRED, "api note"),))
    base = Candidate("base", notes=((Kind.UNIT_NOT_MASS, "base note"),))

    assert _choose(api, base) == ("api", [(Kind.UNIT_REPAIRED, "dose: api note")])


def test_a_rejected_api_block_falls_back_to_the_base_block() -> None:
    value, findings = _choose(Candidate(problem="inverted"), Candidate("base"))

    assert value == "base"
    assert findings == [(Kind.API_BLOCK_REJECTED, "dose: inverted; the base block is used")]


def test_a_base_block_is_reported_only_when_the_api_has_the_route() -> None:
    assert _choose(Candidate(), Candidate("base"), both=False) == ("base", [])
    assert _choose(Candidate(), Candidate("base")) == (
        "base",
        [(Kind.BASE_BLOCK_USED, "dose: the API has none; the base block is used")],
    )


def test_a_weak_block_is_used_only_when_nothing_better_exists() -> None:
    weak_api, weak_base = Candidate("api units", weak=True), Candidate("base units", weak=True)

    assert _choose(weak_api, Candidate("base"))[0] == "base"
    assert _choose(weak_api, weak_base) == ("api units", [])
    assert _choose(Candidate(), weak_base, both=False) == ("base units", [])
    assert _choose(Candidate("api"), weak_base) == ("api", [])


def test_no_block_and_no_problem_is_silent() -> None:
    assert _choose(Candidate(), Candidate()) == (None, [])


def test_a_block_neither_source_has_consistently_is_dropped_with_both_reasons() -> None:
    value, findings = _choose(Candidate(problem="inverted"), Candidate(problem="no units"))

    assert value is None
    assert findings == [
        (Kind.BLOCK_DROPPED, "dose: no consistent block (API: inverted; base: no units)")
    ]


# ---- the report


def test_report_counts_are_sorted_by_kind() -> None:
    report = Report()
    report.add(Kind.UNIT_REPAIRED, "b", substance="LSD", route="oral")
    report.add(Kind.BASE_ONLY, "a", substance="LSD")
    report.add(Kind.UNIT_REPAIRED, "c")

    assert report.counts() == {"base-only": 1, "unit-repaired": 2}
    assert list(report.counts()) == ["base-only", "unit-repaired"]
    assert [finding.detail for finding in report.of(Kind.UNIT_REPAIRED)] == ["b", "c"]
