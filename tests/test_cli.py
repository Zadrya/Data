# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the command line entry point."""

from pathlib import Path

import pytest

from tests.schema_cases import FIXTURES
from zadrya_data import __version__
from zadrya_data.cli import main


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
