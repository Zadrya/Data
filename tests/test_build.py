# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``build`` command and ``zadrya_data.build``. No network.

The inputs are the real base file and a snapshot written, in the real format, from
the recorded API answer ``graphql-relations.json`` (with a wiki page for every name).
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.api_fixtures import recorded
from tests.test_normalize_real import BASE_FILE
from zadrya_data import build as build_module
from zadrya_data.base import load_base
from zadrya_data.build import (
    ATTRIBUTION,
    BuildError,
    DatasetInvalidError,
    build_dataset,
    check_bytes,
    report_tsv,
    write_verified,
)
from zadrya_data.cli import main, run_validate
from zadrya_data.graphql import parse_data
from zadrya_data.invariants import InvariantError
from zadrya_data.mediawiki import WikiPage
from zadrya_data.normalize import Kind, NormalizationError, Normalized, Report, normalize
from zadrya_data.schema import SCHEMA_VERSION, SchemaName
from zadrya_data.snapshot import load_snapshot, write_snapshot

VERSION = "1.2.3"


@pytest.fixture(scope="module")
def snapshot_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    data = recorded("graphql-relations.json")["data"]
    base_names = sorted(substance.name for substance in load_base(BASE_FILE).substances)
    names = sorted({s.name for s in parse_data(data)} | set(base_names))
    pages = [
        WikiPage(name, name, True, number, number, "2026-01-01T00:00:00Z")
        for number, name in enumerate(names, start=1)
    ]
    directory = tmp_path_factory.mktemp("inputs") / "snapshot"
    write_snapshot(directory, data, pages, base_names, date(2026, 11, 16))
    return directory


def _build(snapshot: Path, output: Path, *extra: str) -> int:
    return main(
        [
            "build",
            "--dataset-version",
            VERSION,
            "--base",
            str(BASE_FILE),
            "--snapshot",
            str(snapshot),
            "--output",
            str(output),
            *extra,
        ]
    )


def _leftovers(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir() if path.name.startswith("."))


def test_build_writes_a_checked_deterministic_dataset(
    snapshot_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "dataset" / "substances.json"

    assert _build(snapshot_dir, output) == 0

    data = output.read_bytes()
    text = data.decode("utf-8")
    document = json.loads(text)
    assert document["schemaVersion"] == SCHEMA_VERSION
    assert document["datasetVersion"] == VERSION
    assert document["attribution"] == list(ATTRIBUTION)
    assert "date" not in document
    assert "2026-11-16" not in text and "fetchedOn" not in text  # nothing from the clock
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert "\r" not in text
    assert "µg" in text  # UTF-8, not escaped
    assert text == json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    check_bytes(data)
    assert run_validate(output, SchemaName.SUBSTANCES) == 0
    assert _leftovers(output.parent) == []
    out = capsys.readouterr().out
    assert f"{output}: dataset {VERSION} (schema {SCHEMA_VERSION}), " in out
    assert f"{len(document['substances'])} substances" in out


def test_the_same_inputs_give_the_same_bytes_whatever_the_hash_seed(
    snapshot_dir: Path, tmp_path: Path
) -> None:
    outputs = []
    for seed in ("0", "4242"):
        output = tmp_path / seed / "substances.json"
        report = tmp_path / seed / "report.tsv"
        code = "import sys; from zadrya_data.cli import main; sys.exit(main(sys.argv[1:]))"
        arguments = [
            "build",
            "--dataset-version",
            VERSION,
            "--base",
            str(BASE_FILE),
            "--snapshot",
            str(snapshot_dir),
            "--output",
            str(output),
            "--report",
            str(report),
        ]
        environment = os.environ | {"PYTHONHASHSEED": seed}
        subprocess.run(
            [sys.executable, "-c", code, *arguments], env=environment, check=True, timeout=120
        )
        outputs.append((output.read_bytes(), report.read_bytes()))

    assert outputs[0] == outputs[1]


def test_the_report_is_tab_separated_one_finding_per_line(
    snapshot_dir: Path, tmp_path: Path
) -> None:
    output, report = tmp_path / "substances.json", tmp_path / "report.tsv"

    assert _build(snapshot_dir, output, "--report", str(report)) == 0

    lines = report.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "kind\tsubstance\troute\tdetail"
    assert lines[-1] == ""
    assert all(line.count("\t") == 3 for line in lines[1:-1])
    assert any(line.startswith("alias-shared\tAmphetamine\t\t") for line in lines)


def test_report_values_are_escaped() -> None:
    report = Report()
    report.add(Kind.TEXT_DROPPED, "a\tb\nc\\d\re", substance="X", route="oral")
    report.add(Kind.BASE_ONLY, "plain")

    assert report_tsv(report) == (
        b"kind\tsubstance\troute\tdetail\n"
        b"text-dropped\tX\toral\ta\\tb\\nc\\\\d\\re\n"
        b"base-only\t\t\tplain\n"
    )


def test_the_dataset_version_is_required_and_checked(tmp_path: Path) -> None:
    for arguments in (["build"], ["build", "--dataset-version", "1.2"]):
        with pytest.raises(SystemExit) as error:
            main([*arguments, "--output", str(tmp_path / "x.json")])
        assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_a_snapshot_whose_hash_does_not_match_is_refused(
    snapshot_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tampered = tmp_path / "snapshot"
    tampered.mkdir()
    for path in snapshot_dir.iterdir():
        (tampered / path.name).write_bytes(path.read_bytes())
    graphql = tampered / "graphql.json"
    graphql.write_bytes(graphql.read_bytes().replace(b'"mg"', b'"g"', 1))
    output = tmp_path / "out" / "substances.json"

    assert _build(tampered, output) == 2

    assert "SHA-256" in capsys.readouterr().err
    assert not output.parent.exists()


def test_an_unreadable_base_file_is_refused(tmp_path: Path, snapshot_dir: Path) -> None:
    output = tmp_path / "substances.json"

    code = main(
        [
            "build",
            "--dataset-version",
            VERSION,
            "--base",
            str(tmp_path / "missing.json"),
            "--snapshot",
            str(snapshot_dir),
            "--output",
            str(output),
        ]
    )

    assert code == 2
    assert not output.exists()


def _patch_document(monkeypatch: pytest.MonkeyPatch, change: Any) -> None:
    def patched(*arguments: Any) -> Normalized:
        result = normalize(*arguments)
        change(result.document)
        return result

    monkeypatch.setattr(build_module, "normalize", patched)


def _share_an_alias(document: dict[str, Any]) -> None:
    substances = document["substances"]
    substances[1]["aliases"].append(substances[0]["name"].upper() + "X")
    substances[2]["aliases"].append(substances[0]["name"].upper() + "X")


def test_a_dataset_that_breaks_an_invariant_is_not_written(
    snapshot_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "substances.json"
    output.write_bytes(b"previous")
    _patch_document(monkeypatch, _share_an_alias)

    assert _build(snapshot_dir, output, "--report", str(tmp_path / "r.tsv")) == 1

    assert output.read_bytes() == b"previous"
    assert not (tmp_path / "r.tsv").exists()
    err = capsys.readouterr().err
    assert "breaks its invariants in 2 place(s)" in err
    assert "(unique-alias)" in err


def test_a_dataset_that_breaks_the_schema_is_not_written(
    snapshot_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "substances.json"
    _patch_document(monkeypatch, lambda document: document.update(extra=True))

    assert _build(snapshot_dir, output) == 1

    assert not output.exists()
    assert "not valid against the substances schema (1 violation(s))" in capsys.readouterr().err


def test_a_normalization_error_is_a_refusal(
    snapshot_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any) -> Normalized:
        raise NormalizationError("two substances end up with the name 'X'")

    monkeypatch.setattr(build_module, "normalize", broken)

    assert _build(snapshot_dir, tmp_path / "substances.json") == 1


@pytest.mark.parametrize("target", ["base", "snapshot", "report"])
def test_outputs_never_overwrite_an_input_or_each_other(
    snapshot_dir: Path, tmp_path: Path, target: str, capsys: pytest.CaptureFixture[str]
) -> None:
    output = {
        "base": BASE_FILE,
        "snapshot": snapshot_dir / "substances.json",
        "report": tmp_path / "same.json",
    }[target]
    before = sorted(path.name for path in snapshot_dir.iterdir())

    code = _build(snapshot_dir, output, "--report", str(tmp_path / "same.json"))

    assert code == 1
    assert sorted(path.name for path in snapshot_dir.iterdir()) == before
    assert "error: dataset not written:" in capsys.readouterr().err


def test_an_output_that_cannot_be_written_is_reported(
    snapshot_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    assert _build(snapshot_dir, blocker / "substances.json") == 2

    assert "error: dataset not written:" in capsys.readouterr().err


def test_build_dataset_checks_what_it_returns(snapshot_dir: Path) -> None:
    built = build_dataset(load_base(BASE_FILE), load_snapshot(snapshot_dir), VERSION)

    assert check_bytes(built.data) == built.document
    assert built.report.of(Kind.ALIAS_SHARED)


def test_check_bytes_refuses_a_dataset_the_schema_accepts_and_an_invariant_refuses(
    snapshot_dir: Path,
) -> None:
    built = build_dataset(load_base(BASE_FILE), load_snapshot(snapshot_dir), VERSION)
    document = json.loads(built.data)
    _share_an_alias(document)

    with pytest.raises(InvariantError):
        check_bytes(json.dumps(document).encode())
    with pytest.raises(DatasetInvalidError):
        check_bytes(json.dumps(document | {"extra": 1}).encode())


@pytest.fixture
def target(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "out.json"
    path.write_bytes(b"previous")
    yield path
    assert _leftovers(tmp_path) == []


def test_write_verified_replaces_the_target_after_the_check(target: Path) -> None:
    seen: list[bytes] = []

    write_verified(target, b"new", seen.append)

    assert target.read_bytes() == b"new"
    assert seen == [b"new"]


def test_write_verified_leaves_the_target_when_the_check_fails(target: Path) -> None:
    def refuse(_: bytes) -> None:
        raise BuildError("refused")

    with pytest.raises(BuildError, match="refused"):
        write_verified(target, b"new", refuse)

    assert target.read_bytes() == b"previous"


def test_write_verified_checks_the_bytes_on_disk_not_those_in_memory(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Path.write_bytes

    def truncated(self: Path, data: bytes) -> int:
        return real(self, data[:-1])

    monkeypatch.setattr(Path, "write_bytes", truncated)

    with pytest.raises(BuildError, match="does not hold the bytes that were written"):
        write_verified(target, b"new", lambda _: None)

    monkeypatch.undo()
    assert target.read_bytes() == b"previous"
