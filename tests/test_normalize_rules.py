# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for where normalization refuses to go on, and a few rules outside the reference cases."""

from typing import Any

import pytest

from tests.normalize_cases import CATEGORIES, build
from zadrya_data.normalize import Kind, NormalizationError, normalize
from zadrya_data.normalize.categories import CLASS_TO_CATEGORY

ROUTE = {"name": "oral", "duration": {"total": {"min": 1, "max": 2, "units": "hours"}}}


def _fails(base: list[dict[str, Any]], api: list[dict[str, Any]], **options: Any) -> str:
    base_file, snapshot = build(base, api, **options)
    with pytest.raises(NormalizationError) as error:
        normalize(base_file, snapshot)
    return str(error.value)


def test_a_route_outside_the_schema_stops_the_normalization() -> None:
    message = _fails([{"name": "LSD", "roas": [{"name": "sublabial"}]}], [])

    assert message == "'LSD' has the route 'sublabial' in the base file, which is not in the schema"


def test_a_route_listed_twice_in_one_source_stops_the_normalization() -> None:
    message = _fails([{"name": "LSD"}], [{"name": "LSD", "roas": [ROUTE, ROUTE]}])

    assert message == "'LSD' has the route 'oral' twice in the API"


def test_an_api_entry_that_matches_several_base_names_stops_the_normalization() -> None:
    message = _fails([{"name": "DXM"}, {"name": "Dxm"}], [{"name": "dxm", "roas": [ROUTE]}])

    assert message == "the API entry 'dxm' matches several base names"


def test_two_api_entries_for_one_base_substance_stop_the_normalization() -> None:
    api = [{"name": "DXM", "roas": [ROUTE]}, {"name": "dxm", "roas": [ROUTE]}]

    assert _fails([{"name": "DXM"}], api) == "two API entries match the base substance 'DXM'"


def test_two_substances_with_one_final_name_stop_the_normalization() -> None:
    """'Foo' is renamed to the wiki title 'Bar', which another base substance already has."""
    pages = {"foo": {"title": "Bar"}, "Bar": {"exists": False}}

    message = _fails(
        [{"name": "Foo"}, {"name": "Bar"}], [{"name": "foo", "roas": [ROUTE]}], pages=pages
    )

    assert message == "two substances end up with the name 'Bar'"


def test_an_allowed_api_entry_without_a_url_stops_the_normalization() -> None:
    base_file, snapshot = build([], [{"name": "Tizanidine", "roas": [ROUTE]}])
    entry = snapshot.substances[0]
    without_url = type(entry)(**{f: getattr(entry, f) for f in entry.__slots__} | {"url": None})
    broken = type(snapshot)(
        (without_url,), snapshot.pages, snapshot.base_names, snapshot.fetched_on, {}
    )

    with pytest.raises(NormalizationError, match="the API entry 'Tizanidine' has no url"):
        normalize(base_file, broken)


def test_a_url_the_schema_refuses_stops_the_normalization() -> None:
    message = _fails([{"name": "LSD", "url": "http://psychonautwiki.org/wiki/LSD"}], [])

    assert message == "'LSD' has a url the schema refuses: http://psychonautwiki.org/wiki/LSD"


@pytest.mark.parametrize(
    ("category", "reason"),
    [
        (
            {"name": "Research Chemical", "description": "x", "color": 1},
            "is not a slug or appears twice",
        ),
        (CATEGORIES[0], "is not a slug or appears twice"),
        (
            {"name": "tentative", "description": " \n ", "color": 1},
            "has a description that is not valid text",
        ),
    ],
)
def test_a_base_category_the_schema_refuses_stops_the_normalization(
    category: dict[str, object], reason: str
) -> None:
    assert reason in _fails([], [], categories=[*CATEGORIES, category])


# ---- small things


def test_a_class_that_is_not_valid_text_is_reported_and_dropped() -> None:
    api = [
        {
            "name": "LSD",
            "class": {"psychoactive": ["Psychedelic", "bad\nclass"], "chemical": ["\t"]},
        }
    ]
    result = normalize(*build([{"name": "LSD"}], api))

    assert result.document["substances"][0]["classes"] == {
        "psychoactive": ["Psychedelic"],
        "chemical": [],
    }
    assert [f.detail for f in result.report.of(Kind.TEXT_DROPPED)] == [
        "psychoactive class 'bad\\nclass' is not valid text",
        "chemical class (empty) is not valid text",
    ]


def test_the_class_mapping_only_names_real_categories_of_the_base_file() -> None:
    from tests.test_normalize_real import BASE_FILE
    from zadrya_data.base import load_base

    known = {category.name for category in load_base(BASE_FILE).categories}

    assert set(CLASS_TO_CATEGORY.values()) <= known
    for psychoactive, category in CLASS_TO_CATEGORY.items():
        assert psychoactive.casefold().rstrip("s") == category.rstrip("s")
