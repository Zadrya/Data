# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for writing and reading a snapshot. No network."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from tests.api_fixtures import api_handler, recorded, replay
from zadrya_data import graphql, mediawiki
from zadrya_data.http import USER_AGENT, PoliteClient
from zadrya_data.mediawiki import WikiPage
from zadrya_data.snapshot import (
    SnapshotError,
    dump_json,
    fetch_raw,
    load_snapshot,
    write_snapshot,
)

DAY = date(2026, 11, 16)
PAGES = (
    WikiPage("Acid", "LSD", True, 7289, 169966, "2025-12-11T08:07:17Z"),
    WikiPage("LSD", "LSD", True, 7289, 169966, "2025-12-11T08:07:17Z"),
    WikiPage("Oxazepam", "Oxazepam", False, None, None, None),
)


def _client() -> PoliteClient:
    return replay(api_handler)[0]


def _data() -> dict[str, object]:
    data: dict[str, object] = recorded("graphql.json")["data"]
    return data


def test_dump_json_is_sorted_indented_utf_8_with_a_final_newline() -> None:
    assert (
        dump_json({"b": [1, 2.5], "a": "µg"})
        == '{\n  "a": "µg",\n  "b": [\n    1,\n    2.5\n  ]\n}\n'
    )


def test_dump_json_refuses_nan() -> None:
    with pytest.raises(ValueError):
        dump_json({"min": float("nan")})


def test_fetch_raw_looks_up_the_names_of_both_sources() -> None:
    client, seen = replay(api_handler)

    data, pages = fetch_raw(client, ["LSD", "Oxazepam"])

    assert data == _data()
    assert [page.requested for page in pages] == sorted(
        [
            "2C-x",
            "Ayahuasca",
            "Clonidine",
            "Diphenidine",
            "LSD",
            "MDAI",
            "Oxazepam",
            "Phenylpiracetam",
        ]
    )
    assert len(seen) == 2


def test_snapshot_round_trips(tmp_path: Path) -> None:
    written = write_snapshot(tmp_path, _data(), PAGES, DAY)
    loaded = load_snapshot(tmp_path)

    assert loaded == written
    assert loaded.substances == graphql.parse_data(_data())
    assert loaded.pages == PAGES
    assert loaded.fetched_on == DAY
    assert loaded.query == graphql.QUERY
    assert loaded.counts == {
        "substances": 7,
        "substancesWithoutRoutes": 1,
        "routes": 8,
        "titles": 3,
        "pagesMissing": 1,
        "pagesRedirected": 1,
    }


def test_graphql_file_is_the_data_member_unchanged(tmp_path: Path) -> None:
    write_snapshot(tmp_path, _data(), PAGES, DAY)
    text = (tmp_path / "graphql.json").read_text(encoding="utf-8")

    assert json.loads(text) == _data()
    assert text == dump_json(_data())
    assert "μg" in text and "\\u" not in text


def test_info_file_records_where_and_what_was_asked(tmp_path: Path) -> None:
    write_snapshot(tmp_path, _data(), PAGES, DAY)
    info = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))

    assert info["fetchedOn"] == "2026-11-16"
    assert info["client"] == USER_AGENT
    assert info["graphql"] == {"endpoint": graphql.ENDPOINT, "query": graphql.QUERY}
    assert info["mediawiki"] == {"endpoint": mediawiki.ENDPOINT, "titlesPerRequest": 50}
    assert info["formatVersion"] == 1


def test_two_fetches_of_unchanged_data_give_the_same_bytes(tmp_path: Path) -> None:
    for directory, day in ((tmp_path / "one", DAY), (tmp_path / "two", date(2027, 1, 1))):
        data, pages = fetch_raw(_client(), ["Oxazepam", "LSD"])
        write_snapshot(directory, data, pages, day)

    for name in ("graphql.json", "mediawiki.json"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    assert (tmp_path / "one" / "snapshot.json").read_bytes() != (
        tmp_path / "two" / "snapshot.json"
    ).read_bytes()


def _broken(tmp_path: Path, name: str, text: str) -> Path:
    write_snapshot(tmp_path, _data(), PAGES, DAY)
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def _info(**changes: object) -> str:
    info = {
        "formatVersion": 1,
        "fetchedOn": "2026-11-16",
        "graphql": {"query": graphql.QUERY},
        "counts": {
            "substances": 7,
            "substancesWithoutRoutes": 1,
            "routes": 8,
            "titles": 3,
            "pagesMissing": 1,
            "pagesRedirected": 1,
        },
    }
    return json.dumps(info | changes)


def _page(**changes: object) -> str:
    page = {
        "requested": "LSD",
        "title": "LSD",
        "exists": True,
        "pageId": 1,
        "revisionId": 2,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    return json.dumps({"pages": [page | changes]})


@pytest.mark.parametrize(
    ("name", "text", "reason"),
    [
        ("graphql.json", '{"substances": [{"name": "LSD"}]}', "missing key 'url'"),
        ("graphql.json", '{"substances": [], "substances": []}', "appears twice"),
        ("graphql.json", "{", "not valid JSON"),
        ("mediawiki.json", "[]", "expected an object with the key 'pages'"),
        ("mediawiki.json", '{"pages": {}}', "'pages' is not a list"),
        ("mediawiki.json", '{"pages": [{"requested": "LSD"}]}', "page 0 does not have exactly"),
        ("mediawiki.json", _page(pageId="1"), "page 0 has a value of the wrong type"),
        ("mediawiki.json", _page(exists=1), "page 0 has a value of the wrong type"),
        ("mediawiki.json", _page(revisionId=True), "page 0 has a value of the wrong type"),
        ("snapshot.json", "[]", "expected a snapshot of format version 1"),
        ("snapshot.json", _info(formatVersion=2), "expected a snapshot of format version 1"),
        ("snapshot.json", _info(counts={}), "the counts do not match the other two files"),
        ("snapshot.json", _info(graphql="query"), "missing the query or the fetch date"),
        ("snapshot.json", _info(fetchedOn=20261116), "missing the query or the fetch date"),
        ("snapshot.json", _info(fetchedOn="yesterday"), "fetchedOn is not a date: yesterday"),
    ],
)
def test_a_damaged_snapshot_fails_with_the_file_and_the_reason(
    tmp_path: Path, name: str, text: str, reason: str
) -> None:
    with pytest.raises(SnapshotError) as error:
        load_snapshot(_broken(tmp_path, name, text))

    assert str(tmp_path / name) in str(error.value)
    assert reason in str(error.value)


def test_a_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="graphql.json"):
        load_snapshot(tmp_path)
