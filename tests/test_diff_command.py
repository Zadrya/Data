# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the ``diff`` command. No network."""

import json
from pathlib import Path

import pytest

from tests.diff_cases import BASE_FILE, FIXTURES
from zadrya_data import diff
from zadrya_data.cli import main
from zadrya_data.diff import load_base_dataset
from zadrya_data.diff_report import escape
from zadrya_data.normalize import NormalizationError

OLD, NEW = FIXTURES / "old.json", FIXTURES / "new.json"
GOLDEN = FIXTURES / "report.md"


def test_diff_writes_the_report_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    arguments = [str(OLD), str(NEW), "--old-label", "old.json", "--new-label", "new.json"]
    assert main(["diff", *arguments]) == 0
    assert capsys.readouterr().out == GOLDEN.read_text(encoding="utf-8")


def test_diff_writes_the_report_and_its_head_to_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output, head = tmp_path / "report.md", tmp_path / "head.md"
    code = main(["diff", str(OLD), str(NEW), "--output", str(output), "--head-output", str(head)])
    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert text.startswith(f"# Dataset diff report\n\nOld: {escape(str(OLD))}")
    assert text.startswith(head.read_text(encoding="utf-8"))
    assert (
        head.read_text(encoding="utf-8")
        .rstrip()
        .endswith("datasetVersion\\: 1\\.0\\.0 \\-\\> 1\\.1\\.0")
    )
    assert capsys.readouterr().out == f"{output}: diff report of {OLD} and {NEW}\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["head.md", "report.md"]


def test_diff_lists_the_changed_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = tmp_path / "paths.txt"
    paths.write_text("src/zadrya_data/diff.py\n\n.github/workflows/dataset-diff.yml\n", "utf-8")
    assert main(["diff", str(OLD), str(NEW), "--changed-paths", str(paths)]) == 0
    out = capsys.readouterr().out
    assert "touches 2 file(s) outside dataset/" in out
    assert "> - \\.github/workflows/dataset\\-diff\\.yml\n" in out


def test_diff_reports_unreadable_changed_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["diff", str(OLD), str(NEW), "--changed-paths", str(tmp_path / "missing")])
    assert code == 2
    assert "cannot read" in capsys.readouterr().err


def test_diff_compares_with_the_normalized_base_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = load_base_dataset(BASE_FILE) | {"datasetVersion": "1.0.0"}
    new = tmp_path / "new.json"
    new.write_text(json.dumps(document), encoding="utf-8")
    assert main(["diff", str(BASE_FILE), str(new), "--old-format", "base"]) == 0
    text = capsys.readouterr().out
    assert f"Old: {escape(str(BASE_FILE))} \\(base file, normalized\\)" in text
    assert "- Substances: 289 old, 289 new" in text
    assert "- Changed numbers and units: 0" in text
    assert "datasetVersion" not in text and "attribution" not in text


def test_diff_refuses_an_invalid_dataset(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    assert main(["diff", str(OLD), str(path)]) == 1
    assert "is not valid against the substances schema" in capsys.readouterr().err


def test_diff_refuses_a_dataset_that_breaks_an_invariant(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    document = json.loads(NEW.read_text(encoding="utf-8"))
    document["interactionGroups"][0]["members"].append("Not In The Catalog")
    path = tmp_path / "new.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["diff", str(OLD), str(path), "--output", str(tmp_path / "report.md")]) == 1
    assert "breaks the dataset invariants" in capsys.readouterr().err
    assert not (tmp_path / "report.md").exists()


def test_diff_reports_an_unreadable_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["diff", str(tmp_path / "missing.json"), str(NEW)]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_diff_refuses_a_base_file_that_normalization_rejects(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise NormalizationError("two substances end up with one name")

    monkeypatch.setattr(diff, "normalize", refuse)
    assert main(["diff", str(BASE_FILE), str(NEW), "--old-format", "base"]) == 1
    assert "two substances end up with one name" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["--output", "--head-output"])
def test_diff_never_writes_over_an_input(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, option: str
) -> None:
    new = tmp_path / "new.json"
    new.write_bytes(NEW.read_bytes())
    assert main(["diff", str(OLD), str(new), option, str(new)]) == 2
    assert f"cannot write {new}: it is an input file" in capsys.readouterr().err
    assert new.read_bytes() == NEW.read_bytes()


def test_diff_reports_an_output_directory_that_does_not_exist(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = tmp_path / "missing" / "report.md"
    assert main(["diff", str(OLD), str(NEW), "--output", str(output)]) == 2
    assert f"cannot write {output}" in capsys.readouterr().err


def test_diff_leaves_no_temporary_file_when_the_replace_fails(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = tmp_path / "report.md"
    output.mkdir()
    assert main(["diff", str(OLD), str(NEW), "--output", str(output)]) == 2
    assert f"cannot write {output}" in capsys.readouterr().err
    assert [path.name for path in tmp_path.iterdir()] == ["report.md"]


def test_diff_caps_sections_at_max_rows(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diff", str(OLD), str(NEW), "--max-rows", "1"]) == 0
    assert "more row(s) not shown." in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_diff_refuses_a_max_rows_below_one(value: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["diff", "a", "b", "--max-rows", value])
    assert exit_info.value.code == 2
