# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the GraphQL client and reader, on recorded answers. No network."""

import copy
import json
from typing import Any

import httpx
import pytest

from tests.api_fixtures import recorded, replay
from zadrya_data.graphql import (
    ENDPOINT,
    QUERY,
    ApiClasses,
    ApiDose,
    ApiDuration,
    ApiDurationRange,
    ApiFormatError,
    ApiQueryError,
    ApiRange,
    ApiRoute,
    ApiTolerance,
    fetch_data,
    parse_data,
)
from zadrya_data.http import FetchError


def _data() -> Any:
    return copy.deepcopy(recorded("graphql.json")["data"])


def _by_name() -> dict[str, Any]:
    return {substance.name: substance for substance in parse_data(_data())}


def test_fetch_posts_the_query_and_returns_the_data_member_unchanged() -> None:
    client, seen = replay(lambda request: httpx.Response(200, json=recorded("graphql.json")))

    data = fetch_data(client)

    assert data == recorded("graphql.json")["data"]
    assert len(seen) == 1
    assert str(seen[0].url) == ENDPOINT
    assert json.loads(seen[0].content) == {"query": QUERY}


def test_query_asks_for_every_substance_in_one_request() -> None:
    assert "substances(limit: 2000)" in QUERY
    for field in ("systematicName", "bioavailability", "dangerousInteractions", "afterglow"):
        assert field in QUERY


def test_reference_case_lsd_is_kept_exactly_as_received() -> None:
    lsd = _by_name()["LSD"]

    assert lsd.url == "https://psychonautwiki.org/wiki/LSD"
    assert lsd.featured is True
    assert lsd.summary == "Summary sheet: LSD LSD"
    assert lsd.systematic_name is None
    assert lsd.common_names == ("LSD", "LSD-25", "Lucy", "L", "Acid", "Cid", "Tabs", "Blotter")
    assert lsd.toxicity == ("extremely low toxicity relative to dose",)
    assert lsd.cross_tolerances == ("psychedelics",)
    assert lsd.classes == ApiClasses(chemical=("Lysergamides",), psychoactive=("Psychedelic",))
    assert lsd.tolerance == ApiTolerance(
        full="almost immediately after ingestion", half=None, zero="5 days"
    )
    assert lsd.uncertain_interactions == ("Cannabis", "Stimulants")
    assert lsd.unsafe_interactions == (
        "Tramadol",
        "Deliriants",
        "Tricyclic antidepressants",
        "Ritonavir",
    )
    assert lsd.dangerous_interactions == ("Lithium",)
    assert lsd.roas == (
        ApiRoute(
            name="sublingual",
            dose=ApiDose(
                units="µg",
                threshold=15.0,
                heavy=300.0,
                light=ApiRange(min=15.0, max=75.0),
                common=ApiRange(min=75.0, max=150.0),
                strong=ApiRange(min=150.0, max=300.0),
            ),
            duration=ApiDuration(
                onset=ApiDurationRange(min=15.0, max=30.0, units="minutes"),
                comeup=ApiDurationRange(min=45.0, max=90.0, units="minutes"),
                peak=ApiDurationRange(min=3.0, max=5.0, units="hours"),
                offset=ApiDurationRange(min=3.0, max=5.0, units="hours"),
                total=ApiDurationRange(min=8.0, max=12.0, units="hours"),
                afterglow=ApiDurationRange(min=12.0, max=48.0, units="hours"),
                duration=None,
            ),
            bioavailability=ApiRange(min=71.0, max=71.0),
        ),
    )


def test_a_class_page_without_routes_is_kept() -> None:
    page = _by_name()["2C-x"]

    assert page.roas is None
    assert page.classes is None and page.tolerance is None and page.common_names is None
    assert page.dangerous_interactions is not None


def test_odd_values_are_not_cleaned() -> None:
    by_name = _by_name()
    clonidine_dose = by_name["Clonidine"].roas[0].dose
    mdai_duration = by_name["MDAI"].roas[0].duration
    phenylpiracetam_duration = by_name["Phenylpiracetam"].roas[0].duration
    diphenidine_doses = [route.dose for route in by_name["Diphenidine"].roas]

    assert clonidine_dose.units == "μg"  # the Greek letter mu, not the micro sign
    assert mdai_duration.duration == ApiDurationRange(min=4.0, max=6.0, units=None)
    assert phenylpiracetam_duration.peak.units == "hour"
    assert ApiRange(min=None, max=20.0) in [dose.light for dose in diphenidine_doses]
    assert by_name["Ayahuasca"].classes == ApiClasses(chemical=None, psychoactive=("Psychedelic",))


def test_a_graphql_errors_member_fails() -> None:
    client, _ = replay(lambda request: httpx.Response(200, json=recorded("graphql-errors.json")))

    with pytest.raises(ApiQueryError) as error:
        fetch_data(client)

    assert 'Cannot query field "dosage" on type "Substance".' in str(error.value)


def test_errors_next_to_data_fail_too() -> None:
    answer = recorded("graphql.json") | {"errors": "partial failure"}
    client, _ = replay(lambda request: httpx.Response(200, json=answer))

    with pytest.raises(ApiQueryError, match="'partial failure'"):
        fetch_data(client)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ([], "$: expected an object, found a list"),
        ({"data": None}, "$.data: expected an object, found null"),
        ({"data": {"substances": []}, "extensions": {}}, "$: unknown key(s) 'extensions'"),
        ({"data": {"substances": None}}, "$.substances: expected a list, found null"),
        ({"data": {}}, "$: missing key 'substances'"),
    ],
)
def test_an_answer_of_another_shape_fails(answer: object, message: str) -> None:
    client, _ = replay(lambda request: httpx.Response(200, json=answer))

    with pytest.raises(ApiFormatError) as error:
        fetch_data(client)

    assert str(error.value) == message


def test_a_body_that_is_not_json_fails() -> None:
    client, _ = replay(lambda request: httpx.Response(200, text="<html>Bad gateway</html>"))

    with pytest.raises(FetchError, match="the answer is not JSON"):
        fetch_data(client)


def test_a_server_error_then_success_is_retried() -> None:
    answers = [httpx.Response(500), httpx.Response(200, json=recorded("graphql.json"))]
    client, seen = replay(lambda request: answers.pop(0))

    assert len(parse_data(fetch_data(client))) == 7
    assert len(seen) == 2


def _edit(path: list[str | int], value: object = None, *, remove: bool = False) -> Any:
    data = _data()
    target = data
    for step in path[:-1]:
        target = target[step]
    if remove:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


# LSD is entry 4 of the recorded answer.
LSD: list[str | int] = ["substances", 4]
ROUTE: list[str | int] = [*LSD, "roas", 0]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_edit([*LSD, "halfLife"], "3 hours"), "$.substances[4]: unknown key(s) 'halfLife'"),
        (_edit([*ROUTE, "halfLife"], 3), "$.substances[4].roas[0]: unknown key(s) 'halfLife'"),
        (
            _edit([*ROUTE, "dose", "lightMin"], 15),
            "$.substances[4].roas[0].dose: unknown key(s) 'lightMin'",
        ),
        (
            _edit([*ROUTE, "dose", "light", "units"], "mg"),
            "$.substances[4].roas[0].dose.light: unknown key(s) 'units'",
        ),
        (
            _edit([*ROUTE, "duration", "hangover"], None),
            "$.substances[4].roas[0].duration: unknown key(s) 'hangover'",
        ),
        (
            _edit([*ROUTE, "duration", "onset", "note"], "varies"),
            "$.substances[4].roas[0].duration.onset: unknown key(s) 'note'",
        ),
        (_edit([*LSD, "class", "legal"], []), "$.substances[4].class: unknown key(s) 'legal'"),
        (
            _edit([*LSD, "tolerance", "quarter"], "2 days"),
            "$.substances[4].tolerance: unknown key(s) 'quarter'",
        ),
        (
            _edit([*LSD, "dangerousInteractions", 0, "url"], "https://example.test"),
            "$.substances[4].dangerousInteractions[0]: unknown key(s) 'url'",
        ),
        (_edit([*LSD, "summary"], remove=True), "$.substances[4]: missing key 'summary'"),
        (_edit([*LSD, "name"], None), "$.substances[4].name: expected a string, found null"),
        (_edit([*LSD, "url"], 7), "$.substances[4].url: expected a string, found a number"),
        (
            _edit([*LSD, "featured"], "yes"),
            "$.substances[4].featured: expected a boolean or null, found a string",
        ),
        (
            _edit([*LSD, "commonNames"], "Acid"),
            "$.substances[4].commonNames: expected a list or null, found a string",
        ),
        (
            _edit([*LSD, "commonNames"], ["Acid", None]),
            "$.substances[4].commonNames[1]: expected a string, found null",
        ),
        (
            _edit([*ROUTE, "dose", "threshold"], "15"),
            "$.substances[4].roas[0].dose.threshold: expected a number or null, found a string",
        ),
        (
            _edit([*ROUTE, "dose", "heavy"], True),
            "$.substances[4].roas[0].dose.heavy: expected a number or null, found a boolean",
        ),
        (
            _edit([*LSD, "roas"], ["oral"]),
            "$.substances[4].roas[0]: expected an object, found a string",
        ),
        (_edit(["substances"], {}), "$.substances: expected a list or null, found an object"),
    ],
)
def test_unknown_keys_and_wrong_shapes_fail_with_the_path(data: object, message: str) -> None:
    with pytest.raises(ApiFormatError) as error:
        parse_data(data)

    assert str(error.value) == message


def test_errors_without_messages_are_shown_as_received() -> None:
    client, _ = replay(lambda request: httpx.Response(200, json={"errors": [{"code": 500}]}))

    with pytest.raises(ApiQueryError) as error:
        fetch_data(client)

    assert str(error.value) == "the API answered with errors: [{'code': 500}]"
