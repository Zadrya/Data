# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for building, writing and checking the release manifest."""

import datetime
import hashlib
import json
from typing import Any

import pytest

from tests.schema_cases import substances_valid
from zadrya_data.manifest import (
    ManifestAttributionMismatchError,
    ManifestDatasetVersionMismatchError,
    ManifestError,
    ManifestFormatError,
    ManifestHashMismatchError,
    ManifestInvalidError,
    ManifestSchemaVersionMismatchError,
    SubstancesDocumentError,
    build_manifest,
    check_hash,
    check_manifest,
    check_versions,
    parse_manifest,
    parse_substances,
    serialize_manifest,
    sha256_hex,
)
from zadrya_data.schema import SchemaName, validate

DATE = datetime.date(2026, 11, 16)


def _document(**changes: object) -> dict[str, Any]:
    document: dict[str, Any] = substances_valid()["full"]
    document.update(changes)
    return document


def _bytes(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


SUBSTANCES = _bytes(_document(datasetVersion="1.4.2"))


def _manifest(**changes: object) -> dict[str, object]:
    manifest = build_manifest(SUBSTANCES, min_app_version="1.2.0", date=DATE)
    manifest.update(changes)
    return manifest


# ---- build


def test_manifest_takes_versions_and_attribution_from_the_signed_document() -> None:
    document = _document(datasetVersion="1.4.2")

    manifest = build_manifest(SUBSTANCES, min_app_version="1.2.0", date=DATE)

    assert manifest == {
        "schemaVersion": document["schemaVersion"],
        "datasetVersion": "1.4.2",
        "attribution": document["attribution"],
        "minAppVersion": "1.2.0",
        "sha256": hashlib.sha256(SUBSTANCES).hexdigest(),
        "date": "2026-11-16",
    }
    assert validate(manifest, SchemaName.MANIFEST) == []


def test_hash_is_lowercase_hex_of_the_exact_bytes() -> None:
    # SHA-256 of the empty input and of "abc" (FIPS 180-4 examples).
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_the_same_document_with_other_bytes_has_another_hash() -> None:
    compact = json.dumps(json.loads(SUBSTANCES), ensure_ascii=False).encode()

    first = build_manifest(SUBSTANCES, min_app_version="1.0.0", date=DATE)
    second = build_manifest(compact, min_app_version="1.0.0", date=DATE)

    assert first["sha256"] != second["sha256"]
    assert {**first, "sha256": ""} == {**second, "sha256": ""}


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        pytest.param(b"\xff\xfe", "is not UTF-8 text", id="not-utf-8"),
        pytest.param(b"{", "is not strict JSON", id="not-json"),
        pytest.param(b'{"a": 1, "a": 2}', "appears twice", id="repeated-key"),
        pytest.param(b'{"a": NaN}', "is not strict JSON", id="nan"),
        pytest.param(b"\xef\xbb\xbf{}", "is not strict JSON", id="byte-order-mark"),
        pytest.param(b"[]", "is not a JSON object", id="list"),
        pytest.param(b"", "is not strict JSON", id="empty"),
    ],
)
def test_bytes_that_are_not_a_strict_json_object_are_refused(data: bytes, reason: str) -> None:
    with pytest.raises(SubstancesDocumentError, match=f"substances.json {reason}|{reason}"):
        build_manifest(data, min_app_version="1.0.0", date=DATE)
    with pytest.raises(SubstancesDocumentError):
        parse_substances(data)
    with pytest.raises(ManifestFormatError, match="manifest.json"):
        parse_manifest(data)


def test_a_document_without_its_versions_is_refused() -> None:
    data = _bytes({"attribution": []})

    with pytest.raises(
        SubstancesDocumentError, match="substances.json has no schemaVersion, datasetVersion"
    ):
        build_manifest(data, min_app_version="1.0.0", date=DATE)


@pytest.mark.parametrize(
    ("document", "min_app_version", "path"),
    [
        pytest.param(_document(), "1.0", r"\$\.minAppVersion", id="min-app-version"),
        pytest.param(_document(), "1.0.0\n", r"\$\.minAppVersion", id="trailing-newline"),
        pytest.param(
            _document(datasetVersion="1.0.0-rc1"), "1.0.0", r"\$\.datasetVersion", id="dataset"
        ),
        pytest.param(_document(schemaVersion=1), "1.0.0", r"\$\.schemaVersion", id="schema"),
        pytest.param(_document(attribution=[]), "1.0.0", r"\$\.attribution", id="attribution"),
    ],
)
def test_a_manifest_that_would_break_its_schema_is_not_built(
    document: dict[str, Any], min_app_version: str, path: str
) -> None:
    with pytest.raises(ManifestInvalidError, match=path) as caught:
        build_manifest(_bytes(document), min_app_version=min_app_version, date=DATE)

    assert len(caught.value.violations) == 1


# ---- serialize


def test_manifest_bytes_are_deterministic_and_readable() -> None:
    manifest = _manifest()
    shuffled = dict(reversed(list(manifest.items())))

    data = serialize_manifest(manifest)

    assert data == serialize_manifest(shuffled)
    assert data.endswith(b"\n}\n") and not data.endswith(b"\n\n")
    assert data.startswith(b'{\n  "attribution": [\n    {\n      "license": ')
    top_level = [line.split('"')[1] for line in data.decode().splitlines() if line[:3] == '  "']
    assert top_level == sorted(manifest)
    assert parse_manifest(data) == manifest


def test_manifest_text_is_utf_8_and_not_escaped() -> None:
    attribution = [{"name": "Wiki des Psychonautes é", "url": "https://x.org", "license": "CC0"}]
    data = _bytes(_document(attribution=attribution))

    written = serialize_manifest(build_manifest(data, min_app_version="1.0.0", date=DATE))

    assert "Psychonautes é".encode() in written


def test_an_invalid_manifest_is_not_written() -> None:
    with pytest.raises(ManifestInvalidError, match=r"\$\.sha256"):
        serialize_manifest(_manifest(sha256="ABC"))
    with pytest.raises(ManifestInvalidError, match="unexpected"):
        serialize_manifest(_manifest(unexpected=float("nan")))


# ---- check


def test_a_built_manifest_passes_its_own_check() -> None:
    check_manifest(_manifest(), SUBSTANCES)
    check_manifest(parse_manifest(serialize_manifest(_manifest())), SUBSTANCES)


def test_one_changed_byte_of_the_dataset_is_a_hash_mismatch() -> None:
    tampered = SUBSTANCES.replace(b'"1.4.2"', b'"1.4.3"')

    with pytest.raises(ManifestHashMismatchError, match="states the SHA-256 [0-9a-f]{64}, and"):
        check_manifest(_manifest(), tampered)


@pytest.mark.parametrize("stated", ["0" * 64, "", None, 7])
def test_a_wrong_or_unusable_hash_in_the_manifest_is_a_hash_mismatch(stated: object) -> None:
    with pytest.raises(ManifestHashMismatchError):
        check_hash(_manifest(sha256=stated), SUBSTANCES)


def test_a_manifest_without_a_hash_is_a_hash_mismatch() -> None:
    manifest = _manifest()
    del manifest["sha256"]

    with pytest.raises(ManifestHashMismatchError, match="no text value"):
        check_manifest(manifest, SUBSTANCES)


def test_an_uppercase_hash_is_a_hash_mismatch() -> None:
    upper = sha256_hex(SUBSTANCES).upper()

    with pytest.raises(ManifestHashMismatchError):
        check_hash(_manifest(sha256=upper), SUBSTANCES)


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("schemaVersion", "1.0.1", ManifestSchemaVersionMismatchError),
        ("schemaVersion", "2.0.0", ManifestSchemaVersionMismatchError),
        ("datasetVersion", "1.4.3", ManifestDatasetVersionMismatchError),
        ("datasetVersion", "0.9.0", ManifestDatasetVersionMismatchError),
        ("attribution", [], ManifestAttributionMismatchError),
        (
            "attribution",
            [{"name": "Someone else", "url": "https://example.org", "license": "CC0-1.0"}],
            ManifestAttributionMismatchError,
        ),
    ],
)
def test_each_field_the_manifest_repeats_must_equal_the_signed_one(
    key: str, value: object, error: type[ManifestError]
) -> None:
    with pytest.raises(error, match=f"{key} differs: the manifest states"):
        check_manifest(_manifest(**{key: value}), SUBSTANCES)


@pytest.mark.parametrize(
    ("key", "error"),
    [
        ("schemaVersion", ManifestSchemaVersionMismatchError),
        ("datasetVersion", ManifestDatasetVersionMismatchError),
        ("attribution", ManifestAttributionMismatchError),
    ],
)
def test_a_field_the_manifest_lacks_differs(key: str, error: type[ManifestError]) -> None:
    manifest = _manifest()
    del manifest[key]

    with pytest.raises(error, match=f"{key} differs: the manifest states null"):
        check_versions(manifest, SUBSTANCES)


def test_the_schema_version_is_reported_before_the_dataset_version() -> None:
    manifest = _manifest(schemaVersion="1.0.1", datasetVersion="9.9.9", attribution=[])

    with pytest.raises(ManifestSchemaVersionMismatchError):
        check_versions(manifest, SUBSTANCES)


def test_the_hash_is_checked_before_the_versions() -> None:
    manifest = _manifest(sha256="0" * 64, datasetVersion="9.9.9")

    with pytest.raises(ManifestHashMismatchError):
        check_manifest(manifest, SUBSTANCES)


def test_values_are_compared_as_json_not_as_python() -> None:
    data = _bytes(_document(schemaVersion=1))
    manifest = _manifest(schemaVersion=True, sha256=sha256_hex(data))

    with pytest.raises(ManifestSchemaVersionMismatchError, match="states true, and .* states 1"):
        check_manifest(manifest, data)
    with pytest.raises(ManifestSchemaVersionMismatchError, match=r"states 1\.0, and .* states 1"):
        check_versions({**manifest, "schemaVersion": 1.0}, data)


def test_a_long_value_is_shortened_in_the_message() -> None:
    with pytest.raises(ManifestAttributionMismatchError) as caught:
        check_versions(_manifest(attribution=["x" * 500]), SUBSTANCES)

    assert len(str(caught.value)) < 400 and "..." in str(caught.value)


def test_versions_cannot_be_checked_against_an_unreadable_dataset() -> None:
    with pytest.raises(SubstancesDocumentError):
        check_versions(_manifest(), b"{")
