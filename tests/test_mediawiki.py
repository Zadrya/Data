# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the MediaWiki client, on a recorded answer. No network."""

import copy
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from tests.api_fixtures import WIKI_TITLES, recorded, replay
from zadrya_data.mediawiki import (
    ENDPOINT,
    TITLES_PER_REQUEST,
    WikiFormatError,
    WikiPage,
    fetch_pages,
    parse_answer,
)


def _answer() -> Any:
    return copy.deepcopy(recorded("mediawiki-query.json"))


def _pages() -> dict[str, WikiPage]:
    return {page.requested: page for page in parse_answer(_answer(), WIKI_TITLES)}


def test_an_existing_page_has_its_last_revision() -> None:
    assert _pages()["LSD"] == WikiPage(
        requested="LSD",
        title="LSD",
        exists=True,
        page_id=7289,
        revision_id=169966,
        timestamp="2025-12-11T08:07:17Z",
    )


def test_a_redirect_resolves_to_the_canonical_title() -> None:
    pages = _pages()

    assert pages["Acid"].title == "LSD" and pages["Acid"].revision_id == 169966
    assert pages["DXM"].title == "Dextromethorphan" and pages["DXM"].exists


def test_a_normalized_title_is_followed_through_its_redirect() -> None:
    assert _pages()["lsd"] == WikiPage("lsd", "LSD", True, 7289, 169966, "2025-12-11T08:07:17Z")


def test_a_missing_page_is_recorded_as_missing() -> None:
    pages = _pages()

    assert pages["Oxazepam"] == WikiPage("Oxazepam", "Oxazepam", False, None, None, None)
    assert pages["No such page xyz"].exists is False


def test_a_title_outside_ascii_is_found() -> None:
    assert _pages()["Βk-2C-B"].page_id == 10807


def test_fetch_asks_for_revisions_and_redirects_in_one_request() -> None:
    client, seen = replay(lambda request: httpx.Response(200, json=_answer()))

    pages = fetch_pages(client, [*WIKI_TITLES, "LSD"])

    assert [page.requested for page in pages] == sorted(WIKI_TITLES)
    assert len(seen) == 1 and str(seen[0].url) == ENDPOINT
    fields = {key: values[0] for key, values in parse_qs(seen[0].content.decode()).items()}
    assert fields == {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "revisions",
        "rvprop": "ids|timestamp",
        "titles": "|".join(sorted(WIKI_TITLES)),
    }


def test_titles_are_sent_fifty_per_request() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        titles = parse_qs(request.content.decode())["titles"][0].split("|")
        pages = [{"ns": 0, "title": title, "missing": True} for title in titles]
        return httpx.Response(200, json={"batchcomplete": True, "query": {"pages": pages}})

    client, seen = replay(answer)

    pages = fetch_pages(client, [f"Substance {number:03}" for number in range(120)])

    assert TITLES_PER_REQUEST == 50
    assert [len(parse_qs(r.content.decode())["titles"][0].split("|")) for r in seen] == [50, 50, 20]
    assert len(pages) == 120 and not any(page.exists for page in pages)


def test_no_titles_means_no_request() -> None:
    client, seen = replay(lambda request: httpx.Response(500))

    assert fetch_pages(client, []) == ()
    assert seen == []


def _edit(path: list[str | int], value: object = None, *, remove: bool = False) -> Any:
    answer = _answer()
    target = answer
    for step in path[:-1]:
        target = target[step]
    if remove:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return answer


# Entry 3 of the recorded pages is LSD.
LSD: list[str | int] = ["query", "pages", 3]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ([], "$: expected an object, found list"),
        (_edit(["warnings"], {}), "$: unknown key(s) 'warnings'"),
        (
            {"error": {"code": "badvalue"}},
            "$: missing key 'batchcomplete'",
        ),
        (
            _edit(["batchcomplete"], False),
            "$.batchcomplete: expected true, the answer is not complete",
        ),
        (_edit(["query", "pages"], remove=True), "$.query: missing key 'pages'"),
        (_edit(["query", "interwiki"], []), "$.query: unknown key(s) 'interwiki'"),
        (_edit(["query", "pages"], {}), "$.query.pages: expected a list, found dict"),
        (_edit([*LSD, "protection"], []), "$.query.pages[3]: unknown key(s) 'protection'"),
        (_edit([*LSD, "title"], 7), "$.query.pages[3].title: expected a string, found int"),
        (
            _edit([*LSD, "pageid"], "7289"),
            "$.query.pages[3].pageid: expected an integer, found str",
        ),
        (
            _edit([*LSD, "revisions"], remove=True),
            "$.query.pages[3].revisions: expected a list, found NoneType",
        ),
        (
            _edit([*LSD, "revisions"], []),
            "$.query.pages[3].revisions: expected one revision, found 0",
        ),
        (
            _edit([*LSD, "revisions", 0, "revid"], True),
            "$.query.pages[3].revisions[0].revid: expected an integer, found bool",
        ),
        (
            _edit([*LSD, "revisions", 0, "user"], "Someone"),
            "$.query.pages[3].revisions[0]: unknown key(s) 'user'",
        ),
        (
            _edit(["query", "redirects", 0, "to"], None),
            "$.query.redirects[0].to: expected a string, found NoneType",
        ),
        (
            _edit(["query", "pages"], []),
            "$.query.pages: no page for the requested title 'LSD'",
        ),
    ],
)
def test_an_answer_of_another_shape_fails_with_the_path(answer: object, message: str) -> None:
    with pytest.raises(WikiFormatError) as error:
        parse_answer(answer, WIKI_TITLES)

    assert str(error.value) == message


def test_a_redirect_loop_ends() -> None:
    answer = {
        "batchcomplete": True,
        "query": {
            "redirects": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
            "pages": [
                {"ns": 0, "title": "A", "missing": True},
                {"ns": 0, "title": "B", "missing": True},
            ],
        },
    }

    assert [page.exists for page in parse_answer(answer, ["A"])] == [False]
