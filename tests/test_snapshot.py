# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for writing and reading a snapshot. No network."""

import hashlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.api_fixtures import api_handler, recorded, replay
from zadrya_data import graphql, mediawiki
from zadrya_data import snapshot as snapshot_module
from zadrya_data.http import USER_AGENT
from zadrya_data.mediawiki import WikiPage
from zadrya_data.snapshot import (
    SnapshotError,
    dump_json,
    fetch_raw,
    load_snapshot,
    sort_substances,
    write_snapshot,
)

DAY = date(2026, 11, 16)
BASE_NAMES = ("Oxazepam", "LSD")
API_NAMES = ["2C-x", "Ayahuasca", "Clonidine", "Diphenidine", "LSD", "MDAI", "Phenylpiracetam"]


def _data() -> dict[str, object]:
    data: dict[str, object] = recorded("graphql.json")["data"]
    return data


def _fetched() -> tuple[dict[str, object], tuple[WikiPage, ...]]:
    return fetch_raw(replay(api_handler)[0], BASE_NAMES)


def _write(directory: Path, day: date = DAY) -> Path:
    data, pages = _fetched()
    write_snapshot(directory, data, pages, BASE_NAMES, day)
    return directory


def _files(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def test_dump_json_is_sorted_indented_utf_8_with_a_final_newline() -> None:
    assert dump_json({"b": [1, 2.5], "a": "µg"}) == (
        '{\n  "a": "µg",\n  "b": [\n    1,\n    2.5\n  ]\n}\n'
    )


def test_dump_json_refuses_nan() -> None:
    with pytest.raises(ValueError):
        dump_json({"min": float("nan")})


def test_fetch_raw_looks_up_the_names_of_both_sources() -> None:
    client, seen = replay(api_handler)

    data, pages = fetch_raw(client, BASE_NAMES)

    assert data == _data()
    assert [page.requested for page in pages] == sorted([*API_NAMES, "Oxazepam"])
    assert len(seen) == 2


def test_snapshot_round_trips(tmp_path: Path) -> None:
    data, pages = _fetched()

    written = write_snapshot(tmp_path / "s", data, pages, BASE_NAMES, DAY)
    loaded = load_snapshot(tmp_path / "s")

    assert loaded == written
    assert loaded.substances == graphql.parse_data(sort_substances(_data()))
    assert loaded.pages == pages
    assert loaded.base_names == ("LSD", "Oxazepam")
    assert loaded.fetched_on == DAY
    assert loaded.counts == {
        "substances": 7,
        "substancesWithoutRoutes": 1,
        "routes": 8,
        "titles": 8,
        "pagesMissing": 1,
        "pagesRedirected": 0,
    }


def test_graphql_file_holds_every_value_as_received(tmp_path: Path) -> None:
    text = (_write(tmp_path / "s") / "graphql.json").read_text(encoding="utf-8")
    written = json.loads(text)["substances"]
    received = _data()["substances"]
    assert isinstance(received, list)

    assert [entry["name"] for entry in written] == API_NAMES
    assert {entry["name"]: entry for entry in written} == {
        entry["name"]: entry for entry in received
    }
    assert text == dump_json(sort_substances(_data()))
    assert "μg" in text and "\\u" not in text


def test_substances_are_ordered_by_the_code_points_of_their_names() -> None:
    template = _data()["substances"]
    assert isinstance(template, list)
    names = ["b", "Zolpidem", "Βk-2C-B", "1cP-MiPLA", "B", "1P-ETH-LAD", "1,3-Butanediol"]
    data: dict[str, object] = {"substances": [template[0] | {"name": name} for name in names]}

    ordered = sort_substances(data)["substances"]

    assert isinstance(ordered, list)
    assert [entry["name"] for entry in ordered] == [
        "1,3-Butanediol",
        "1P-ETH-LAD",
        "1cP-MiPLA",
        "B",
        "Zolpidem",
        "b",
        "Βk-2C-B",
    ]
    assert data["substances"] != ordered  # the argument is left as it was


def test_info_file_records_provenance_and_the_hashes_of_the_other_files(tmp_path: Path) -> None:
    directory = _write(tmp_path / "s")
    info = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))

    assert info["formatVersion"] == 1
    assert info["fetchedOn"] == "2026-11-16"
    assert info["client"] == USER_AGENT
    assert info["baseNames"] == ["LSD", "Oxazepam"]
    assert info["graphql"] == {
        "endpoint": graphql.ENDPOINT,
        "query": graphql.QUERY,
        "sha256": hashlib.sha256((directory / "graphql.json").read_bytes()).hexdigest(),
    }
    assert info["mediawiki"] == {
        "endpoint": mediawiki.ENDPOINT,
        "titlesPerRequest": 50,
        "sha256": hashlib.sha256((directory / "mediawiki.json").read_bytes()).hexdigest(),
    }


def test_two_fetches_of_unchanged_data_give_the_same_bytes(tmp_path: Path) -> None:
    one = _files(_write(tmp_path / "one", DAY))
    two = _files(_write(tmp_path / "two", date(2027, 1, 1)))

    assert one["graphql.json"] == two["graphql.json"]
    assert one["mediawiki.json"] == two["mediawiki.json"]
    assert one["snapshot.json"] != two["snapshot.json"]


# ---- writing safely


def _other_fetch() -> tuple[dict[str, object], tuple[WikiPage, ...]]:
    """A second fetch with the same counts and different content."""
    data, pages = _fetched()
    entries = data["substances"]
    assert isinstance(entries, list)
    changed = [entry | {"summary": "Changed upstream."} for entry in entries]
    return {"substances": changed}, pages


def _leftovers(parent: Path) -> list[str]:
    return sorted(path.name for path in parent.iterdir() if path.name.startswith("."))


def test_a_new_snapshot_replaces_the_previous_one_completely(tmp_path: Path) -> None:
    directory = _write(tmp_path / "s")
    data, pages = _other_fetch()

    write_snapshot(directory, data, pages, BASE_NAMES, DAY)

    assert load_snapshot(directory).substances[0].summary == "Changed upstream."
    assert sorted(_files(directory)) == ["graphql.json", "mediawiki.json", "snapshot.json"]
    assert _leftovers(tmp_path) == []


def test_the_destination_and_its_parents_are_created(tmp_path: Path) -> None:
    directory = _write(tmp_path / "a" / "b" / "snapshot")

    assert len(load_snapshot(directory).substances) == 7


def test_a_write_that_fails_half_way_leaves_the_previous_snapshot_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _write(tmp_path / "s")
    before = _files(directory)
    data, pages = _other_fetch()
    original = Path.write_text
    written: list[str] = []

    def fail_on_the_second_file(self: Path, *args: Any, **kwargs: Any) -> int:
        written.append(self.name)
        if len(written) == 2:
            raise OSError("no space left on device")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_the_second_file)

    with pytest.raises(OSError, match="no space left"):
        write_snapshot(directory, data, pages, BASE_NAMES, DAY)

    assert written == ["graphql.json", "mediawiki.json"]
    assert _files(directory) == before
    assert _leftovers(tmp_path) == []


def test_a_write_that_does_not_read_back_leaves_the_previous_snapshot_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _write(tmp_path / "s")
    before = _files(directory)
    data, pages = _other_fetch()

    def refuse(staging: Path) -> None:
        raise SnapshotError(f"{staging}: not what was written")

    monkeypatch.setattr(snapshot_module, "load_snapshot", refuse)

    with pytest.raises(SnapshotError, match="not what was written"):
        write_snapshot(directory, data, pages, BASE_NAMES, DAY)

    assert _files(directory) == before
    assert _leftovers(tmp_path) == []


def test_a_failed_move_into_place_restores_the_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _write(tmp_path / "s")
    before = _files(directory)
    data, pages = _other_fetch()
    original = Path.rename

    def fail_for_the_new_directory(self: Path, target: Path) -> Path:
        if ".new-" in self.name:
            raise OSError("cannot move")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", fail_for_the_new_directory)

    with pytest.raises(OSError, match="cannot move"):
        write_snapshot(directory, data, pages, BASE_NAMES, DAY)

    assert _files(directory) == before
    assert _leftovers(tmp_path) == []


def test_a_failed_move_of_a_first_snapshot_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, pages = _fetched()

    def fail(self: Path, target: Path) -> Path:
        raise OSError("cannot move")

    monkeypatch.setattr(Path, "rename", fail)

    with pytest.raises(OSError, match="cannot move"):
        write_snapshot(tmp_path / "s", data, pages, BASE_NAMES, DAY)

    assert list(tmp_path.iterdir()) == []


def test_a_directory_with_other_files_is_never_replaced(tmp_path: Path) -> None:
    directory = tmp_path / "project"
    directory.mkdir()
    (directory / "notes.txt").write_text("keep me", encoding="utf-8")
    data, pages = _fetched()

    with pytest.raises(SnapshotError) as error:
        write_snapshot(directory, data, pages, BASE_NAMES, DAY)

    assert "holds 'notes.txt', which is not a snapshot file" in str(error.value)
    assert _files(directory) == {"notes.txt": b"keep me"}


def test_a_file_is_not_a_destination(tmp_path: Path) -> None:
    path = tmp_path / "snapshot"
    path.write_text("", encoding="utf-8")
    data, pages = _fetched()

    with pytest.raises(SnapshotError, match="not a directory"):
        write_snapshot(path, data, pages, BASE_NAMES, DAY)


# ---- reading strictly


def test_a_file_swapped_in_from_another_fetch_with_equal_counts_is_rejected(
    tmp_path: Path,
) -> None:
    mine = _write(tmp_path / "mine")
    data, pages = _other_fetch()
    other = tmp_path / "other"
    write_snapshot(other, data, pages, BASE_NAMES, DAY)
    assert load_snapshot(other).counts == load_snapshot(mine).counts

    (mine / "graphql.json").write_bytes((other / "graphql.json").read_bytes())

    with pytest.raises(SnapshotError) as error:
        load_snapshot(mine)

    assert str(error.value) == (
        f"{mine / 'graphql.json'}: the SHA-256 is not the one in snapshot.json"
    )


def test_a_changed_mediawiki_file_is_rejected(tmp_path: Path) -> None:
    directory = _write(tmp_path / "s")
    path = directory / "mediawiki.json"
    path.write_text(path.read_text(encoding="utf-8").replace("1000", "1001"), encoding="utf-8")

    with pytest.raises(SnapshotError, match="mediawiki.json: the SHA-256 is not the one"):
        load_snapshot(directory)


def _edit_info(directory: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = directory / "snapshot.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    change(info)
    path.write_text(json.dumps(info), encoding="utf-8")


def _edit_data(directory: Path, name: str, change: Callable[[dict[str, Any]], None]) -> None:
    """Change one of the two data files and record its new hash, as a consistent forgery."""
    path = directory / name
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(dump_json(document), encoding="utf-8")
    _rehash(directory, name)


def _rehash(directory: Path, name: str) -> None:
    digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    _edit_info(directory, lambda info: info[name.removesuffix(".json")].update(sha256=digest))


def _set(*path: str | int, value: object) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        target: Any = document
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return change


def _drop(*path: str | int) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        target: Any = document
        for step in path[:-1]:
            target = target[step]
        del target[path[-1]]

    return change


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (_drop("client"), "expected exactly the keys"),
        (_set("note", value="hand edited"), "expected exactly the keys"),
        (_set("formatVersion", value=2), "expected a snapshot of format version 1"),
        (_set("formatVersion", value=True), "expected a snapshot of format version 1"),
        (_set("formatVersion", value=1.0), "expected a snapshot of format version 1"),
        (_set("fetchedOn", value=20261116), "fetchedOn is not a date of the form YYYY-MM-DD"),
        (_set("fetchedOn", value="20261116"), "fetchedOn is not a date of the form YYYY-MM-DD"),
        (_set("fetchedOn", value="2026-02-30"), "fetchedOn is not a date: 2026-02-30"),
        (_set("client", value=1), "client is not a string"),
        (_set("graphql", value="query"), "graphql does not have exactly the known keys"),
        (_set("graphql", "extra", value=1), "graphql does not have exactly the known keys"),
        (_drop("mediawiki", "endpoint"), "mediawiki does not have exactly the known keys"),
        (_set("graphql", "sha256", value="ABC"), "graphql.sha256 is not a SHA-256"),
        (_set("mediawiki", "sha256", value=7), "mediawiki.sha256 is not a SHA-256"),
        (
            _set("graphql", "endpoint", value="https://api.example.test/"),
            "graphql.endpoint is not the one this version of the code uses",
        ),
        (
            _set("graphql", "query", value="{ substances { name } }"),
            "graphql.query is not the one this version of the code uses",
        ),
        (
            _set("mediawiki", "endpoint", value="https://example.test/w/api.php"),
            "mediawiki.endpoint is not the one this version of the code uses",
        ),
        (
            _set("mediawiki", "titlesPerRequest", value=50.0),
            "mediawiki.titlesPerRequest is not the one this version of the code uses",
        ),
        (_set("baseNames", value="LSD"), "baseNames is not a list of strings"),
        (_set("baseNames", value=["LSD", 7]), "baseNames is not a list of strings"),
        (_set("baseNames", value=["Oxazepam", "LSD"]), "baseNames is not sorted"),
        (_set("baseNames", value=["LSD", "LSD", "Oxazepam"]), "baseNames is not sorted"),
        (
            _set("baseNames", value=["LSD"]),
            "the titles are not exactly the substance names of the API and of the base file",
        ),
        (
            _set("baseNames", value=["LSD", "Oxazepam", "Triazolam"]),
            "the titles are not exactly the substance names of the API and of the base file",
        ),
        (_set("counts", value={}), "the counts do not match the other two files"),
        (_set("counts", "pagesRedirected", value=False), "the counts do not match"),
        (_set("counts", "substances", value=7.0), "the counts do not match"),
        (_set("counts", "routes", value=9), "the counts do not match"),
        (_set("counts", "extra", value=0), "the counts do not match"),
    ],
)
def test_a_snapshot_file_that_says_something_else_is_rejected(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], reason: str
) -> None:
    directory = _write(tmp_path / "s")
    _edit_info(directory, change)

    with pytest.raises(SnapshotError) as error:
        load_snapshot(directory)

    assert reason in str(error.value)


EXISTING = 0  # 2C-x, the first page record
MISSING = 6  # Oxazepam


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda document: document.update(extra=1), "expected an object with the key 'pages'"),
        (_set("pages", value={}), "'pages' is not a list"),
        (_drop("pages", EXISTING, "title"), "page 0 does not have exactly the known keys"),
        (_set("pages", EXISTING, value="2C-x"), "page 0 does not have exactly the known keys"),
        (_set("pages", EXISTING, "requested", value=7), "page 0 has a value of the wrong type"),
        (_set("pages", EXISTING, "exists", value=1), "page 0 has a value of the wrong type"),
        (_set("pages", EXISTING, "pageId", value=None), "page 0 must have positive ids"),
        (_set("pages", EXISTING, "pageId", value=0), "page 0 must have positive ids"),
        (_set("pages", EXISTING, "pageId", value=True), "page 0 must have positive ids"),
        (_set("pages", EXISTING, "revisionId", value="1000"), "page 0 must have positive ids"),
        (_set("pages", EXISTING, "revisionId", value=-1), "page 0 must have positive ids"),
        (
            _set("pages", EXISTING, "timestamp", value="2026-01-01 00:00:00"),
            "page 0 must have positive ids and a UTC timestamp",
        ),
        (_set("pages", EXISTING, "timestamp", value=None), "page 0 must have positive ids"),
        (_set("pages", MISSING, "pageId", value=5), "page 6 must have positive ids"),
        (
            _set("pages", MISSING, "timestamp", value="2026-01-01T00:00:00Z"),
            "page 6 must have positive ids",
        ),
        (
            lambda document: document["pages"].reverse(),
            "the requested titles are not sorted and free of repeats",
        ),
        (
            lambda document: document["pages"].insert(1, dict(document["pages"][0])),
            "the requested titles are not sorted and free of repeats",
        ),
        (
            _drop("pages", MISSING),
            "the titles are not exactly the substance names of the API and of the base file",
        ),
        (
            lambda document: document["pages"].append(
                document["pages"][MISSING] | {"requested": "Zolpidem", "title": "Zolpidem"}
            ),
            "the titles are not exactly the substance names of the API and of the base file",
        ),
    ],
)
def test_a_forged_mediawiki_file_is_rejected_even_with_a_matching_hash(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], reason: str
) -> None:
    directory = _write(tmp_path / "s")
    _edit_data(directory, "mediawiki.json", change)

    with pytest.raises(SnapshotError) as error:
        load_snapshot(directory)

    assert str(directory / "mediawiki.json") in str(error.value)
    assert reason in str(error.value)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda document: document["substances"].reverse(), "not ordered by name"),
        (_set("substances", 0, "halfLife", value=3), "unknown key(s) 'halfLife'"),
        (_set("substances", value=[]), "the list is empty"),
        (_set("substances", 1, "name", value="2C-x"), "second entry named '2C-x'"),
    ],
)
def test_a_forged_graphql_file_is_rejected_even_with_a_matching_hash(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], reason: str
) -> None:
    directory = _write(tmp_path / "s")
    _edit_data(directory, "graphql.json", change)

    with pytest.raises(SnapshotError) as error:
        load_snapshot(directory)

    assert str(directory / "graphql.json") in str(error.value)
    assert reason in str(error.value)


@pytest.mark.parametrize(
    ("name", "content", "reason"),
    [
        ("graphql.json", b'{"substances": [], "substances": []}', "appears twice"),
        ("graphql.json", b"{", "not valid JSON"),
        ("mediawiki.json", b'{"pages": [\xff]}', "codec can't decode"),
        ("mediawiki.json", b"[]", "expected an object with the key 'pages'"),
    ],
)
def test_a_data_file_that_is_not_strict_json_is_rejected(
    tmp_path: Path, name: str, content: bytes, reason: str
) -> None:
    directory = _write(tmp_path / "s")
    (directory / name).write_bytes(content)
    _rehash(directory, name)

    with pytest.raises(SnapshotError) as error:
        load_snapshot(directory)

    assert str(directory / name) in str(error.value)
    assert reason in str(error.value)


def test_an_info_file_that_is_not_json_is_rejected(tmp_path: Path) -> None:
    directory = _write(tmp_path / "s")
    (directory / "snapshot.json").write_text("[", encoding="utf-8")

    with pytest.raises(SnapshotError, match="snapshot.json: not valid JSON"):
        load_snapshot(directory)


@pytest.mark.parametrize("name", ["graphql.json", "mediawiki.json", "snapshot.json"])
def test_a_missing_file_fails(tmp_path: Path, name: str) -> None:
    directory = _write(tmp_path / "s")
    (directory / name).unlink()

    with pytest.raises(SnapshotError, match=name):
        load_snapshot(directory)
