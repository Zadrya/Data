# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the full acceptance check of a release, and for its order.

The keys are created here, in memory, and are never stored.
"""

import datetime
import json
from dataclasses import dataclass, replace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.schema_cases import substances_valid
from zadrya_data import manifest as manifest_module
from zadrya_data import release_check, signing
from zadrya_data.errors import ReleaseRejectedError
from zadrya_data.manifest import (
    ManifestAttributionMismatchError,
    ManifestDatasetVersionMismatchError,
    ManifestError,
    ManifestFormatError,
    ManifestHashMismatchError,
    ManifestSchemaVersionMismatchError,
    SubstancesDocumentError,
    build_manifest,
    serialize_manifest,
    sha256_hex,
)
from zadrya_data.release_check import ReleaseSchemaError, verify_release
from zadrya_data.schema import SchemaName
from zadrya_data.signing import (
    NoPinnedKeysError,
    PinnedKey,
    SignatureFormatError,
    SignatureMismatchError,
    SigningError,
    encode_signature,
    sign,
)

DATE = datetime.date(2026, 11, 16)
CURRENT = Ed25519PrivateKey.generate()
NEXT = Ed25519PrivateKey.generate()
PINNED = (
    PinnedKey(name="current", public_key=CURRENT.public_key()),
    PinnedKey(name="next", public_key=NEXT.public_key()),
)


def _json(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


@dataclass(frozen=True)
class Release:
    """The three files of a release, and the keys to check them with."""

    substances: bytes
    signature_file: bytes
    manifest: bytes
    public_keys: tuple[PinnedKey, ...] = PINNED

    def verify(self) -> Any:
        return verify_release(
            substances=self.substances,
            signature_file=self.signature_file,
            manifest=self.manifest,
            public_keys=self.public_keys,
        )


def _release(
    document: object | None = None,
    *,
    key: Ed25519PrivateKey = CURRENT,
    manifest_changes: dict[str, object] | None = None,
    substances: bytes | None = None,
) -> Release:
    """Build a correctly signed release, whose manifest is then edited without checks."""
    if substances is None:
        substances = _json(substances_valid()["full"] if document is None else document)
    try:
        manifest: dict[str, object] = build_manifest(substances, min_app_version="1.2.0", date=DATE)
    except Exception:  # a dataset the manifest cannot be built from: state the hash only
        manifest = {"sha256": sha256_hex(substances)}
    manifest.update(manifest_changes or {})
    return Release(
        substances=substances,
        signature_file=encode_signature(sign(substances, key)),
        manifest=_json(manifest),
    )


def _document(**changes: object) -> dict[str, Any]:
    document: dict[str, Any] = substances_valid()["full"]
    document.update(changes)
    return document


# ---- acceptance


@pytest.mark.parametrize(("key", "name"), [(CURRENT, "current"), (NEXT, "next")])
def test_a_release_signed_with_a_pinned_key_is_accepted(key: Ed25519PrivateKey, name: str) -> None:
    release = _release(_document(datasetVersion="1.4.2"), key=key)

    verified = release.verify()

    assert verified.key.name == name
    assert verified.dataset_version == "1.4.2"
    assert verified.schema_version == "1.0.0"
    assert verified.min_app_version == "1.2.0"
    assert verified.sha256 == sha256_hex(release.substances)


def test_the_files_the_pipeline_writes_are_accepted() -> None:
    substances = _json(substances_valid()["minimal"])
    manifest = serialize_manifest(build_manifest(substances, min_app_version="1.0.0", date=DATE))
    signature_file = encode_signature(sign(substances, CURRENT))

    verified = verify_release(
        substances=substances,
        signature_file=signature_file,
        manifest=manifest,
        public_keys=PINNED[:1],
    )

    assert verified.key.name == "current"


# ---- step 1: signature


def test_a_changed_byte_of_the_dataset_is_rejected_by_the_signature() -> None:
    release = _release()
    tampered = replace(release, substances=release.substances.replace(b"1.0.0", b"1.0.1", 1))

    with pytest.raises(SignatureMismatchError):
        tampered.verify()


def test_a_key_that_is_not_pinned_is_rejected() -> None:
    with pytest.raises(SignatureMismatchError):
        _release(key=Ed25519PrivateKey.generate()).verify()


def test_no_pinned_keys_rejects_a_good_release() -> None:
    with pytest.raises(NoPinnedKeysError):
        replace(_release(), public_keys=()).verify()


@pytest.mark.parametrize("damage", ["empty", "truncated", "no-line-feed", "raw"])
def test_a_damaged_signature_file_is_rejected(damage: str) -> None:
    release = _release()
    signature_file = {
        "empty": b"",
        "truncated": release.signature_file[:40] + b"\n",
        "no-line-feed": release.signature_file[:-1],
        "raw": sign(release.substances, CURRENT),
    }[damage]

    with pytest.raises(SignatureFormatError):
        replace(release, signature_file=signature_file).verify()


def test_the_signature_of_the_manifest_is_not_the_signature_of_the_dataset() -> None:
    release = _release()
    swapped = replace(release, signature_file=encode_signature(sign(release.manifest, CURRENT)))

    with pytest.raises(SignatureMismatchError):
        swapped.verify()


# ---- step 2: hash


def test_a_manifest_with_another_hash_is_rejected() -> None:
    with pytest.raises(ManifestHashMismatchError):
        _release(manifest_changes={"sha256": "0" * 64}).verify()


@pytest.mark.parametrize("manifest", [b"", b"{", b"[]", b'{"sha256": 1, "sha256": 2}'])
def test_a_manifest_that_is_not_a_strict_json_object_is_rejected(manifest: bytes) -> None:
    with pytest.raises(ManifestFormatError):
        replace(_release(), manifest=manifest).verify()


# ---- step 3: schemas


def test_a_manifest_that_breaks_its_schema_is_rejected() -> None:
    release = _release(manifest_changes={"minAppVersion": "soon", "extra": 1})

    with pytest.raises(ReleaseSchemaError, match="manifest.json is not valid") as caught:
        release.verify()

    assert caught.value.name is SchemaName.MANIFEST
    assert len(caught.value.violations) == 2


def test_a_signed_dataset_that_breaks_its_schema_is_rejected() -> None:
    release = _release(_document(substances="none"))

    with pytest.raises(ReleaseSchemaError, match=r"substances.json is not valid: \$\.substances"):
        release.verify()


def test_a_signed_dataset_of_a_future_schema_major_is_rejected() -> None:
    release = _release(_document(schemaVersion="2.0.0"))

    with pytest.raises(ReleaseSchemaError, match=r"\$\.schemaVersion") as caught:
        release.verify()

    assert caught.value.name is SchemaName.SUBSTANCES


def test_a_signed_dataset_that_is_not_strict_json_is_rejected() -> None:
    release = _release(substances=b'{"schemaVersion": "1.0.0", "schemaVersion": "1.0.0"}')
    manifest = _json({**json.loads(_release().manifest), "sha256": sha256_hex(release.substances)})

    with pytest.raises(SubstancesDocumentError, match="appears twice"):
        replace(release, manifest=manifest).verify()


def test_a_long_list_of_violations_is_shortened_in_the_message() -> None:
    wrong = ("datasetVersion", "schemaVersion", "minAppVersion", "date", "attribution")
    changes: dict[str, object] = {key: 1 for key in (*wrong, "extra")}

    with pytest.raises(ReleaseSchemaError, match=r"\(and 1 more\)") as caught:
        _release(manifest_changes=changes).verify()

    assert len(caught.value.violations) == 6


# ---- step 4: consistency


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"schemaVersion": "1.0.1"}, ManifestSchemaVersionMismatchError),
        ({"datasetVersion": "9.0.0"}, ManifestDatasetVersionMismatchError),
        (
            {"attribution": [{"name": "Other", "url": "https://example.org", "license": "CC0"}]},
            ManifestAttributionMismatchError,
        ),
    ],
)
def test_a_valid_manifest_that_contradicts_the_signed_dataset_is_rejected(
    changes: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        _release(manifest_changes=changes).verify()


def test_what_only_the_manifest_holds_is_not_protected() -> None:
    """Documents the limit recorded in the ADR: the date and minAppVersion can be altered."""
    release = _release(manifest_changes={"minAppVersion": "0.0.1", "date": "1999-01-01"})

    assert release.verify().min_app_version == "0.0.1"


# ---- one base class


def _every_subclass(base: type) -> set[type]:
    found: set[type] = set(base.__subclasses__())
    return found | {deeper for subclass in found for deeper in _every_subclass(subclass)}


def test_every_refusal_has_the_same_base_class() -> None:
    rejected = _every_subclass(ReleaseRejectedError)

    assert {SigningError, ManifestError, ReleaseSchemaError} <= rejected
    for module in (signing, manifest_module, release_check):
        for name, member in vars(module).items():
            defined_here = getattr(member, "__module__", None) == module.__name__
            if isinstance(member, type) and issubclass(member, Exception) and defined_here:
                assert member in rejected | {ReleaseRejectedError}, name


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"signature_file": b""}, id="signature-format"),
        pytest.param({"substances": b"other bytes"}, id="signature"),
        pytest.param({"public_keys": ()}, id="no-keys"),
        pytest.param({"manifest": b"{"}, id="manifest-format"),
        pytest.param({"manifest": b'{"sha256": "x"}'}, id="hash"),
    ],
)
def test_one_except_clause_catches_every_refusal(broken: dict[str, Any]) -> None:
    with pytest.raises(ReleaseRejectedError):
        replace(_release(), **broken).verify()
    later: list[dict[str, object]] = [{"extra": 1}, {"datasetVersion": "9.0.0"}]
    for changes in later:
        with pytest.raises(ReleaseRejectedError):
            _release(manifest_changes=changes).verify()


# ---- order


def test_the_signature_is_checked_before_anything_is_parsed() -> None:
    """Everything is wrong at once: only the signature is reported."""
    release = _release(substances=b"not json at all")
    broken = replace(release, manifest=b"not json either", signature_file=b"")

    with pytest.raises(SignatureFormatError):
        broken.verify()
    with pytest.raises(SignatureMismatchError):
        replace(broken, signature_file=encode_signature(bytes(64))).verify()


def test_the_hash_is_checked_before_the_schemas() -> None:
    release = _release(
        _document(substances="none"), manifest_changes={"sha256": "0" * 64, "extra": 1}
    )

    with pytest.raises(ManifestHashMismatchError):
        release.verify()


def test_the_manifest_schema_is_checked_before_the_dataset_schema() -> None:
    release = _release(_document(substances="none"), manifest_changes={"extra": 1})

    with pytest.raises(ReleaseSchemaError) as caught:
        release.verify()

    assert caught.value.name is SchemaName.MANIFEST


def test_the_schemas_are_checked_before_the_versions() -> None:
    release = _release(manifest_changes={"datasetVersion": "9.0.0", "minAppVersion": "soon"})

    with pytest.raises(ReleaseSchemaError):
        release.verify()
