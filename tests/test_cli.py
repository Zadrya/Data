# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the command line entry point."""

from pathlib import Path

import httpx
import pytest

from tests.schema_cases import FIXTURES
from zadrya_data import __version__
from tests.api_fixtures import api_handler, replay
from zadrya_data import cli
from zadrya_data.cli import main
from zadrya_data.snapshot import load_snapshot


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"zadrya-data {__version__}"


def test_no_arguments_exits_successfully() -> None:
    assert main([]) == 0


def test_validate_accepts_a_valid_dataset(capsys: pytest.CaptureFixture[str]) -> None:
    path = FIXTURES / "substances" / "valid" / "full.json"

    assert main(["validate", str(path)]) == 0
    assert capsys.readouterr().out.strip() == f"{path}: valid against the substances schema"


def test_validate_reports_every_violation_with_its_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = FIXTURES / "substances" / "invalid" / "dose-heavy-min-negative.json"

    assert main(["validate", str(path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{path}: $.substances[0].roas[0].dose.heavyMin: " in captured.err
    assert "(minimum)" in captured.err
    assert "1 violation(s) of the substances schema" in captured.err


def test_validate_checks_a_manifest_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    path = FIXTURES / "manifest" / "valid" / "release.json"

    assert main(["validate", "--schema", "manifest", str(path)]) == 0
    assert "valid against the manifest schema" in capsys.readouterr().out


def test_validate_uses_the_substances_schema_by_default() -> None:
    assert main(["validate", str(FIXTURES / "manifest" / "valid" / "release.json")]) == 1


def test_validate_fails_on_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(tmp_path / "absent.json")]) == 2
    assert "error: cannot read" in capsys.readouterr().err


def test_validate_fails_on_a_file_that_is_not_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schemaVersion": ', encoding="utf-8")

    assert main(["validate", str(path)]) == 2
    assert "error: cannot read" in capsys.readouterr().err


def test_validate_rejects_an_unknown_schema_name() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["validate", "--schema", "release", "dataset.json"])

    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('{"heavy": NaN}', "NaN is not a JSON number"),
        ('{"heavy": Infinity}', "Infinity is not a JSON number"),
        ('{"heavy": 1e999}', "the number 1e999 is out of range"),
        (
            '{"heavy": 9007199254740992}',
            "the integer 9007199254740992 is outside the safe range of a double",
        ),
        (
            '{"heavy": 1' + "0" * 399 + "}",
            "the integer 1" + "0" * 399 + " is outside the safe range of a double",
        ),
        ('{"name": "LSD", "name": "LSA"}', "the key 'name' appears twice in one object"),
        ("[" * 100_000, "the document is nested too deeply"),
        ("\ufeff{}", "not valid JSON"),
    ],
)
def test_validate_refuses_text_that_is_not_strict_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, reason: str
) -> None:
    path = tmp_path / "dataset.json"
    path.write_text(text, encoding="utf-8")

    assert main(["validate", str(path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"error: cannot read {path} as strict JSON: {reason}" in captured.err


def test_validate_refuses_bytes_that_are_not_utf_8(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dataset.json"
    path.write_bytes(b'{"name": "\xff"}')

    assert main(["validate", str(path)]) == 2
    assert "error: cannot read" in capsys.readouterr().err


BASE_FIXTURE = Path(__file__).parent / "fixtures" / "base" / "minimal.json"


def test_fetch_writes_a_snapshot_without_touching_the_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, seen = replay(api_handler)
    monkeypatch.setattr(cli, "make_client", lambda: client)
    output = tmp_path / "snapshot"

    assert main(["fetch", "--output", str(output), "--base", str(BASE_FIXTURE)]) == 0

    snapshot = load_snapshot(output)
    assert len(snapshot.substances) == 7
    assert "Examplamine" in [page.requested for page in snapshot.pages]
    assert sorted(path.name for path in output.iterdir()) == [
        "graphql.json",
        "mediawiki.json",
        "snapshot.json",
    ]
    assert len(seen) == 2
    assert capsys.readouterr().out.strip() == (
        f"{output}: 7 API entries (1 without routes, 8 routes), "
        "8 wiki titles (0 missing, 0 redirected), 2 requests"
    )


def test_fetch_writes_nothing_when_a_request_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = replay(lambda request: httpx.Response(404))
    monkeypatch.setattr(cli, "make_client", lambda: client)
    output = tmp_path / "snapshot"

    assert main(["fetch", "--output", str(output), "--base", str(BASE_FIXTURE)]) == 1

    assert not output.exists()
    assert (
        "error: fetch failed: https://api.psychonautwiki.org/: HTTP 404" in capsys.readouterr().err
    )


def test_fetch_fails_before_any_request_when_the_base_file_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, seen = replay(api_handler)
    monkeypatch.setattr(cli, "make_client", lambda: client)

    assert (
        main(["fetch", "--output", str(tmp_path / "s"), "--base", str(tmp_path / "no.json")]) == 1
    )

    assert seen == []
    assert "error: fetch failed" in capsys.readouterr().err


def test_fetch_keeps_the_previous_snapshot_when_a_later_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "snapshot"
    monkeypatch.setattr(cli, "make_client", lambda: replay(api_handler)[0])
    assert main(["fetch", "--output", str(output), "--base", str(BASE_FIXTURE)]) == 0
    before = {path.name: path.read_bytes() for path in output.iterdir()}

    monkeypatch.setattr(cli, "make_client", lambda: replay(lambda r: httpx.Response(404))[0])
    assert main(["fetch", "--output", str(output), "--base", str(BASE_FIXTURE)]) == 1

    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["snapshot"]


def test_fetch_refuses_a_directory_that_is_not_a_snapshot_before_any_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    client, seen = replay(api_handler)
    monkeypatch.setattr(cli, "make_client", lambda: client)

    assert main(["fetch", "--output", str(tmp_path), "--base", str(BASE_FIXTURE)]) == 1

    assert seen == []
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert "which is not a snapshot file" in capsys.readouterr().err


def test_fetch_replaces_a_snapshot_that_finder_has_visited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "snapshot"
    monkeypatch.setattr(cli, "make_client", lambda: replay(api_handler)[0])
    assert main(["fetch", "--output", str(output), "--base", str(BASE_FIXTURE)]) == 0
    (output / ".DS_Store").write_bytes(b"Bud1")

    assert main(["fetch", "--output", str(output), "--base", str(BASE_FIXTURE)]) == 0

    assert sorted(path.name for path in output.iterdir()) == [
        "graphql.json",
        "mediawiki.json",
        "snapshot.json",
    ]


def test_fetch_refuses_a_symbolic_link_as_output_before_any_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    client, seen = replay(api_handler)
    monkeypatch.setattr(cli, "make_client", lambda: client)

    assert main(["fetch", "--output", str(link), "--base", str(BASE_FIXTURE)]) == 1

    assert seen == []
    assert link.is_symlink() and list(target.iterdir()) == []
    assert f"{link}: a symbolic link, refusing to replace it" in capsys.readouterr().err


def test_fetch_help_states_the_number_of_requests(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["fetch", "--help"])

    text = " ".join(capsys.readouterr().out.split())
    assert "nine requests today" in text and "dozen" not in text


def test_fetch_requires_an_output_directory() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["fetch"])

    assert exit_info.value.code == 2


def test_the_real_client_is_the_polite_one() -> None:
    with cli.make_client() as client:
        assert client.request_count == 0


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b'{"categories": [], "substances": [{"name": "\xff"}]}', "not UTF-8 text"),
        (b'{"categories": [], "substances": [], "substances": []}', "appears twice"),
        (b'{"categories": []}', "missing key 'substances'"),
        (b"[", "not valid JSON"),
    ],
)
def test_fetch_exits_cleanly_when_the_base_file_cannot_be_read(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    reason: str,
) -> None:
    client, seen = replay(api_handler)
    monkeypatch.setattr(cli, "make_client", lambda: client)
    base = tmp_path / "Substances.json"
    base.write_bytes(content)

    assert main(["fetch", "--output", str(tmp_path / "s"), "--base", str(base)]) == 1

    assert seen == []
    captured = capsys.readouterr()
    assert captured.err.startswith("error: fetch failed: ")
    assert captured.out == ""
    assert reason in captured.err
    assert "Traceback" not in captured.err


def test_fetch_exits_cleanly_when_the_base_path_is_a_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", "--output", str(tmp_path / "s"), "--base", str(tmp_path)]) == 1
    assert "error: fetch failed" in capsys.readouterr().err
