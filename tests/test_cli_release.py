# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the release commands: ``manifest``, ``sign`` and ``verify``.

Keys are created here in memory, and written only under ``tmp_path``. No test
touches the network: ``verify --release`` runs against a mock transport.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.schema_cases import substances_valid
from zadrya_data.cli import main
from zadrya_data.manifest import parse_manifest, sha256_hex


def _dataset(**changes: object) -> bytes:
    document: dict[str, Any] = substances_valid()["full"]
    document.update(changes)
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


@pytest.fixture
def substances(tmp_path: Path) -> Path:
    path = tmp_path / "substances.json"
    path.write_bytes(_dataset())
    return path


def _manifest_args(substances: Path, output: Path, *extra: str) -> list[str]:
    return [
        "manifest",
        str(substances),
        "--min-app-version",
        "1.2.0",
        "--date",
        "2026-11-17",
        "--output",
        str(output),
        *extra,
    ]


def test_manifest_writes_the_manifest_of_the_exact_bytes(
    substances: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "manifest.json"

    assert main(_manifest_args(substances, output, "--dataset-version", "1.0.0")) == 0

    manifest = parse_manifest(output.read_bytes())
    digest = sha256_hex(substances.read_bytes())
    assert manifest["sha256"] == digest
    assert manifest["minAppVersion"] == "1.2.0"
    assert manifest["date"] == "2026-11-17"
    assert manifest["datasetVersion"] == "1.0.0"
    assert capsys.readouterr().out.strip() == (
        f"{output}: manifest of dataset 1.0.0 (schema 1.0.0), minAppVersion 1.2.0, "
        f"date 2026-11-17, sha256 {digest}"
    )
    assert sorted(path.name for path in tmp_path.iterdir()) == ["manifest.json", "substances.json"]


def test_manifest_gives_the_same_bytes_every_time(substances: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"

    assert main(_manifest_args(substances, first)) == 0
    assert main(_manifest_args(substances, second)) == 0

    assert first.read_bytes() == second.read_bytes()


def test_manifest_refuses_another_dataset_version(
    substances: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "manifest.json"

    assert main(_manifest_args(substances, output, "--dataset-version", "1.0.1")) == 1

    assert not output.exists()
    assert capsys.readouterr().err.strip() == (
        f"error: manifest not written: {substances} states datasetVersion 1.0.0, "
        "and 1.0.1 was expected"
    )


def test_manifest_refuses_a_dataset_that_breaks_the_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "substances.json"
    path.write_bytes(_dataset(substances="none"))

    assert main(_manifest_args(path, tmp_path / "manifest.json")) == 1

    error = capsys.readouterr().err
    assert "is not valid against the substances schema (1 violation(s)): $.substances" in error


def test_manifest_refuses_a_dataset_that_is_not_strict_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "substances.json"
    path.write_bytes(b'{"datasetVersion": "1.0.0", "datasetVersion": "1.0.0"}')

    assert main(_manifest_args(path, tmp_path / "manifest.json")) == 1

    assert "substances.json is not strict JSON" in capsys.readouterr().err


def test_manifest_fails_on_a_missing_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "absent.json"

    assert main(_manifest_args(path, tmp_path / "manifest.json")) == 2

    assert f"error: manifest not written: cannot read {path}" in capsys.readouterr().err


def test_manifest_never_writes_over_its_input(
    substances: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = substances.read_bytes()

    assert main(_manifest_args(substances, substances)) == 1

    assert substances.read_bytes() == before
    assert "is the input file" in capsys.readouterr().err


def test_manifest_fails_when_the_output_cannot_be_written(
    substances: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "missing-directory" / "manifest.json"

    assert main(_manifest_args(substances, output)) == 2

    assert f"cannot write {output}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--date", "2026-11-31"),
        ("--date", "20261117"),
        ("--date", "2026-W47-2"),
        ("--min-app-version", "1.2"),
        ("--min-app-version", "v1.2.0"),
        ("--min-app-version", "01.2.0"),
        ("--dataset-version", "1.0.0-rc.1"),
    ],
)
def test_manifest_refuses_malformed_arguments(
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
) -> None:
    arguments = _manifest_args(substances, tmp_path / "manifest.json")
    if option in arguments:
        arguments[arguments.index(option) + 1] = value
    else:
        arguments += [option, value]

    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
    assert f"{value!r} is not a" in capsys.readouterr().err


def test_manifest_has_no_default_date(substances: Path, tmp_path: Path) -> None:
    arguments = _manifest_args(substances, tmp_path / "manifest.json")
    del arguments[arguments.index("--date") : arguments.index("--date") + 2]

    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
