# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the release commands: ``manifest``, ``sign`` and ``verify``.

Keys are created here in memory, and written only under ``tmp_path``. No test
touches the network: ``verify --release`` runs against a mock transport.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.schema_cases import substances_valid
from zadrya_data import cli
from zadrya_data.cli import main
from zadrya_data.http import PoliteClient
from zadrya_data.manifest import parse_manifest, sha256_hex
from zadrya_data.signing import (
    KEY_FILE_VARIABLE,
    KEY_PASSWORD_VARIABLE,
    PinnedKey,
    decode_signature,
    verify,
)

PASSWORD = "throwaway test password"


def _public_pem(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _pin(directory: Path, **keys: Ed25519PrivateKey) -> Path:
    directory.mkdir(exist_ok=True)
    for name, key in keys.items():
        (directory / f"{name}.pem").write_bytes(_public_pem(key))
    return directory


def _key_file(
    path: Path, key: Ed25519PrivateKey, *, mode: int = 0o600, password: str | None = None
) -> Path:
    encryption: serialization.KeySerializationEncryption = serialization.NoEncryption()
    if password is not None:
        encryption = serialization.BestAvailableEncryption(password.encode())
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    )
    path.chmod(mode)
    return path


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


@pytest.fixture
def signer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    """A throwaway key, pinned in tmp_path/keys and named by the environment."""
    key = Ed25519PrivateKey.generate()
    _pin(tmp_path / "keys", current=key)
    monkeypatch.setenv(KEY_FILE_VARIABLE, str(_key_file(tmp_path / "signing.key", key)))
    monkeypatch.delenv(KEY_PASSWORD_VARIABLE, raising=False)
    return key


def _sign_args(substances: Path, output: Path, keys: Path, *extra: str) -> list[str]:
    return ["sign", str(substances), "--output", str(output), "--keys", str(keys), *extra]


def _assert_no_key_material(text: str, key: Ed25519PrivateKey, tmp_path: Path) -> None:
    private_pem = (tmp_path / "signing.key").read_bytes().decode()
    body = "".join(private_pem.splitlines()[1:-1])
    assert body not in text and body[:16] not in text
    assert "PRIVATE" not in text
    assert PASSWORD not in text


def test_sign_writes_a_signature_that_the_pinned_key_verifies(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "substances.json.sig"

    assert (
        main(_sign_args(substances, output, tmp_path / "keys", "--dataset-version", "1.0.0")) == 0
    )

    content = output.read_bytes()
    assert len(content) == 89 and content.endswith(b"\n")
    pinned = PinnedKey(name="current", public_key=signer.public_key())
    assert verify(substances.read_bytes(), decode_signature(content), [pinned]) == pinned
    captured = capsys.readouterr()
    assert captured.out.strip() == (
        f"{output}: signature of {substances} (sha256 {sha256_hex(substances.read_bytes())}), "
        "verified with the pinned key current"
    )
    _assert_no_key_material(captured.out + captured.err, signer, tmp_path)


def test_sign_names_the_pinned_key_that_matched_during_a_rotation(
    signer: Ed25519PrivateKey, substances: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    keys = _pin(tmp_path / "keys", a_old=Ed25519PrivateKey.generate())
    (keys / "current.pem").rename(keys / "z_new.pem")

    assert main(_sign_args(substances, tmp_path / "s.sig", keys)) == 0

    assert capsys.readouterr().out.strip().endswith("verified with the pinned key z_new")


def test_sign_refuses_to_write_a_signature_of_a_key_that_is_not_pinned(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stranger = _key_file(tmp_path / "signing.key", Ed25519PrivateKey.generate())
    monkeypatch.setenv(KEY_FILE_VARIABLE, str(stranger))
    output = tmp_path / "substances.json.sig"

    assert main(_sign_args(substances, output, tmp_path / "keys")) == 1

    assert not output.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(
        "error: signature not written: the signature does not verify with any pinned key (current)"
    )
    _assert_no_key_material(captured.err, signer, tmp_path)


def test_sign_signs_with_an_encrypted_key_and_its_password(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _key_file(tmp_path / "signing.key", signer, password=PASSWORD)
    monkeypatch.setenv(KEY_PASSWORD_VARIABLE, PASSWORD)

    assert main(_sign_args(substances, tmp_path / "s.sig", tmp_path / "keys")) == 0

    captured = capsys.readouterr()
    _assert_no_key_material(captured.out + captured.err, signer, tmp_path)


def test_sign_with_a_wrong_password_does_not_show_it(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _key_file(tmp_path / "signing.key", signer, password="another password")
    monkeypatch.setenv(KEY_PASSWORD_VARIABLE, PASSWORD)

    assert main(_sign_args(substances, tmp_path / "s.sig", tmp_path / "keys")) == 1

    captured = capsys.readouterr()
    assert "the password is wrong" in captured.err
    _assert_no_key_material(captured.out + captured.err, signer, tmp_path)


def test_sign_refuses_a_key_file_that_others_can_read(
    signer: Ed25519PrivateKey, substances: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "signing.key").chmod(0o644)

    assert main(_sign_args(substances, tmp_path / "s.sig", tmp_path / "keys")) == 1

    assert "its mode is 0644" in capsys.readouterr().err
    assert not (tmp_path / "s.sig").exists()


def test_sign_needs_the_key_file_variable(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(KEY_FILE_VARIABLE)

    assert main(_sign_args(substances, tmp_path / "s.sig", tmp_path / "keys")) == 1

    assert f"{KEY_FILE_VARIABLE} is not set" in capsys.readouterr().err


def test_sign_does_not_echo_a_key_put_in_the_variable(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(KEY_FILE_VARIABLE, (tmp_path / "signing.key").read_text())

    assert main(_sign_args(substances, tmp_path / "s.sig", tmp_path / "keys")) == 1

    captured = capsys.readouterr()
    assert "looks like the key itself" in captured.err
    _assert_no_key_material(captured.out + captured.err, signer, tmp_path)


def test_sign_without_pinned_keys_fails_before_reading_the_private_key(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(KEY_FILE_VARIABLE)
    empty = tmp_path / "empty-keys"
    empty.mkdir()

    assert main(_sign_args(substances, tmp_path / "s.sig", empty)) == 1

    assert "no pinned public keys" in capsys.readouterr().err


def test_sign_refuses_a_dataset_of_another_version_before_reading_the_key(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(KEY_FILE_VARIABLE)
    arguments = _sign_args(substances, tmp_path / "s.sig", tmp_path / "keys")

    assert main([*arguments, "--dataset-version", "2.0.0"]) == 1

    assert "states datasetVersion 1.0.0, and 2.0.0 was expected" in capsys.readouterr().err


def test_sign_refuses_a_dataset_that_breaks_the_schema(
    signer: Ed25519PrivateKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "substances.json"
    path.write_bytes(_dataset(schemaVersion="2.0.0"))

    assert main(_sign_args(path, tmp_path / "s.sig", tmp_path / "keys")) == 1

    assert "is not valid against the substances schema" in capsys.readouterr().err
    assert not (tmp_path / "s.sig").exists()


def test_sign_fails_on_a_missing_dataset(
    signer: Ed25519PrivateKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_sign_args(tmp_path / "absent.json", tmp_path / "s.sig", tmp_path / "keys")) == 2

    assert "error: signature not written: cannot read" in capsys.readouterr().err


def _release(tmp_path: Path, substances: Path) -> Path:
    """Write a complete release of the dataset with the commands themselves."""
    directory = tmp_path / "release"
    directory.mkdir()
    (directory / "substances.json").write_bytes(substances.read_bytes())
    assert main(_manifest_args(substances, directory / "manifest.json")) == 0
    sign_args = _sign_args(substances, directory / "substances.json.sig", tmp_path / "keys")
    assert main(sign_args) == 0
    return directory


def test_verify_accepts_a_release_and_says_what_it_checked(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    capsys.readouterr()
    keys = str(tmp_path / "keys")

    assert main(["verify", str(release), "--keys", keys, "--dataset-version", "1.0.0"]) == 0

    pinned = PinnedKey(name="current", public_key=signer.public_key())
    assert capsys.readouterr().out == (
        f"{release}: accepted\n"
        f"  signed by the pinned key current ({pinned.base64})\n"
        "  datasetVersion 1.0.0, schemaVersion 1.0.0 (signed)\n"
        f"  sha256 {sha256_hex(substances.read_bytes())}\n"
        "  minAppVersion 1.2.0 (unsigned, from the manifest)\n"
    )


def test_verify_rejects_a_dataset_changed_after_signing(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    (release / "substances.json").write_bytes(substances.read_bytes() + b"\n")
    capsys.readouterr()

    assert main(["verify", str(release), "--keys", str(tmp_path / "keys")]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(
        f"error: {release}: rejected: the signature does not verify with any pinned key"
    )


def test_verify_rejects_a_manifest_of_another_dataset(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    manifest = json.loads((release / "manifest.json").read_text())
    manifest["sha256"] = "0" * 64
    (release / "manifest.json").write_text(json.dumps(manifest))

    assert main(["verify", str(release), "--keys", str(tmp_path / "keys")]) == 1

    assert "rejected: the manifest states the SHA-256 0000" in capsys.readouterr().err


def test_verify_rejects_another_signed_version_than_expected(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    keys = str(tmp_path / "keys")

    assert main(["verify", str(release), "--keys", keys, "--dataset-version", "1.1.0"]) == 1

    assert capsys.readouterr().err.strip() == (
        f"error: {release}: rejected: the signed datasetVersion is 1.0.0, and 1.1.0 was expected"
    )


def test_verify_rejects_everything_without_pinned_keys(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    empty = tmp_path / "no-keys"
    empty.mkdir()

    assert main(["verify", str(release), "--keys", str(empty)]) == 1

    assert "rejected: no pinned public keys" in capsys.readouterr().err


def test_verify_reports_a_missing_file(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    (release / "substances.json.sig").unlink()

    assert main(["verify", str(release), "--keys", str(tmp_path / "keys")]) == 2

    assert f"not verified: cannot read {release / 'substances.json.sig'}" in (
        capsys.readouterr().err
    )


def test_verify_lets_an_unexpected_error_surface(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release(tmp_path, substances)

    def broken(**_: object) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(cli, "verify_release", broken)

    with pytest.raises(RuntimeError, match="a bug"):
        main(["verify", str(release), "--keys", str(tmp_path / "keys")])


RELEASES = "https://github.com/Zadrya/Data/releases"
TAG_URL = f"{RELEASES}/tag/dataset-v1.0.0"
DOWNLOAD_URL = f"{RELEASES}/download/dataset-v1.0.0"
ASSET_HOST = "https://release-assets.githubusercontent.com"
Handler = Callable[[httpx.Request], httpx.Response]


def _published(release: Path, *, tag: str = "dataset-v1.0.0") -> Handler:
    """Answer like GitHub: latest redirects to the tag, a download to the asset host."""

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{RELEASES}/latest":
            return httpx.Response(302, headers={"location": f"{RELEASES}/tag/{tag}"})
        prefix = f"{RELEASES}/download/{tag}/"
        if url.startswith(prefix):
            location = f"{ASSET_HOST}/asset/{url.removeprefix(prefix)}?token=t"
            return httpx.Response(302, headers={"location": location})
        if url.startswith(f"{ASSET_HOST}/asset/"):
            name = request.url.path.removeprefix("/asset/")
            return httpx.Response(200, content=(release / name).read_bytes())
        return httpx.Response(404)

    return handle


def _serve(monkeypatch: pytest.MonkeyPatch, handle: Handler) -> list[str]:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handle(request)

    client = PoliteClient(httpx.MockTransport(record), sleep=lambda _: None)
    monkeypatch.setattr(cli, "make_client", lambda: client)
    return seen


def _not_found(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404)


@pytest.mark.parametrize("requested", ["dataset-v1.0.0", "latest"])
def test_verify_release_downloads_and_accepts_a_published_release(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    requested: str,
) -> None:
    release = _release(tmp_path, substances)
    seen = _serve(monkeypatch, _published(release))
    capsys.readouterr()

    assert main(["verify", "--release", requested, "--keys", str(tmp_path / "keys")]) == 0

    out = capsys.readouterr().out
    assert out.startswith(f"{TAG_URL}: accepted\n  signed by the pinned key current")
    assert [url for url in seen if url.startswith(DOWNLOAD_URL)] == [
        f"{DOWNLOAD_URL}/substances.json",
        f"{DOWNLOAD_URL}/substances.json.sig",
        f"{DOWNLOAD_URL}/manifest.json",
    ]
    assert len(seen) == (7 if requested == "latest" else 6)


def test_verify_release_rejects_a_tag_that_is_not_the_signed_version(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    _serve(monkeypatch, _published(release, tag="dataset-v1.0.1"))

    assert main(["verify", "--release", "latest", "--keys", str(tmp_path / "keys")]) == 1

    assert capsys.readouterr().err.strip() == (
        f"error: {RELEASES}/tag/dataset-v1.0.1: rejected: the release dataset-v1.0.1 holds a "
        "signed dataset of version 1.0.0: a release is tagged with the version inside its "
        "dataset (dataset-v1.0.0)"
    )


def test_verify_release_rejects_another_version_than_expected(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    _serve(monkeypatch, _published(release))
    keys = str(tmp_path / "keys")

    assert (
        main(["verify", "--release", "latest", "--keys", keys, "--dataset-version", "2.0.0"]) == 1
    )

    assert capsys.readouterr().err.strip() == (
        f"error: {TAG_URL}: rejected: the signed datasetVersion is 1.0.0, and 2.0.0 was expected"
    )


def test_verify_release_rejects_a_tampered_asset(
    signer: Ed25519PrivateKey,
    substances: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _release(tmp_path, substances)
    (release / "substances.json").write_bytes(substances.read_bytes().replace(b"\n", b"\r\n"))
    _serve(monkeypatch, _published(release))

    assert main(["verify", "--release", "dataset-v1.0.0", "--keys", str(tmp_path / "keys")]) == 1

    assert "rejected: the signature does not verify" in capsys.readouterr().err


def test_verify_release_refuses_a_tag_of_another_form_before_any_request(
    signer: Ed25519PrivateKey,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen = _serve(monkeypatch, _not_found)

    assert main(["verify", "--release", "v1.0.0", "--keys", str(tmp_path / "keys")]) == 1

    assert seen == []
    assert "'v1.0.0' is not a dataset release tag" in capsys.readouterr().err


def test_verify_release_downloads_nothing_without_pinned_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _serve(monkeypatch, _not_found)
    empty = tmp_path / "keys"
    empty.mkdir()

    assert main(["verify", "--release", "latest", "--keys", str(empty)]) == 1

    assert seen == []
    assert "error: release latest: rejected: no pinned public keys" in capsys.readouterr().err


def test_verify_release_reports_a_failed_download(
    signer: Ed25519PrivateKey,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _serve(monkeypatch, _not_found)

    assert main(["verify", "--release", "dataset-v1.0.0", "--keys", str(tmp_path / "keys")]) == 2

    assert capsys.readouterr().err.strip() == (
        f"error: {TAG_URL}: not verified: download failed: {DOWNLOAD_URL}/substances.json: "
        "HTTP 404"
    )


def test_verify_release_refuses_a_download_redirected_to_another_host(
    signer: Ed25519PrivateKey,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def elsewhere(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://other.example.test/a"})

    seen = _serve(monkeypatch, elsewhere)

    assert main(["verify", "--release", "dataset-v1.0.0", "--keys", str(tmp_path / "keys")]) == 2

    assert seen == [f"{DOWNLOAD_URL}/substances.json"]
    assert "redirects to other.example.test, which is not an allowed download host" in (
        capsys.readouterr().err
    )


def test_verify_needs_a_directory_or_a_release(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["verify"])
    assert exit_info.value.code == 2

    with pytest.raises(SystemExit) as exit_info:
        main(["verify", "somewhere", "--release", "latest"])
    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
