# SPDX-License-Identifier: GPL-3.0-or-later
"""Build ``manifest.json`` for a release, and check a manifest against the dataset.

The manifest is not signed. Everything in it that also exists inside the signed
``substances.json`` (both versions and the attribution) is copied from there when
the manifest is built, and compared with it when the manifest is checked, so the
signed bytes decide. What only the manifest holds (``minAppVersion`` and ``date``)
is not protected by the signature: see ``docs/adr/0003-dataset-signature.md``.
"""

import datetime
import hashlib
import json
from collections.abc import Mapping

from zadrya_data import strict_json
from zadrya_data.errors import ReleaseRejectedError
from zadrya_data.schema import SchemaName, SchemaViolation, validate

# What the manifest repeats from the signed document.
_SIGNED_FIELDS = ("schemaVersion", "datasetVersion", "attribution")


class ManifestError(ReleaseRejectedError):
    """Base of every error of this module."""


class SubstancesDocumentError(ManifestError):
    """The bytes of ``substances.json`` cannot be read as the signed document."""


class ManifestFormatError(ManifestError):
    """The bytes of ``manifest.json`` are not a strict JSON object."""


class ManifestInvalidError(ManifestError):
    """A manifest breaks ``manifest.schema.json``."""

    def __init__(self, violations: list[SchemaViolation]) -> None:
        self.violations = violations
        details = "; ".join(str(violation) for violation in violations)
        super().__init__(f"the manifest is not valid: {details}")


class ManifestHashMismatchError(ManifestError):
    """The SHA-256 in the manifest is not the SHA-256 of ``substances.json``."""


class ManifestSchemaVersionMismatchError(ManifestError):
    """The manifest and ``substances.json`` state different schema versions."""


class ManifestDatasetVersionMismatchError(ManifestError):
    """The manifest and ``substances.json`` state different dataset versions."""


class ManifestAttributionMismatchError(ManifestError):
    """The manifest and ``substances.json`` state different attributions."""


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 of the exact bytes as 64 lowercase hexadecimal characters."""
    return hashlib.sha256(data).hexdigest()


def _strict_object(data: bytes, what: str, error: type[ManifestError]) -> dict[str, object]:
    try:
        document = strict_json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise error(f"{what} is not UTF-8 text") from None
    except strict_json.StrictJsonError as problem:
        raise error(f"{what} is not strict JSON: {problem}") from problem
    if not isinstance(document, dict):
        raise error(f"{what} is not a JSON object")
    return document


def parse_substances(substances_bytes: bytes) -> dict[str, object]:
    """Read the exact bytes of ``substances.json`` as a strict JSON object."""
    return _strict_object(substances_bytes, "substances.json", SubstancesDocumentError)


def parse_manifest(manifest_bytes: bytes) -> dict[str, object]:
    """Read the exact bytes of ``manifest.json`` as a strict JSON object."""
    return _strict_object(manifest_bytes, "manifest.json", ManifestFormatError)


def _signed_fields(substances_bytes: bytes) -> dict[str, object]:
    document = parse_substances(substances_bytes)
    missing = [key for key in _SIGNED_FIELDS if key not in document]
    if missing:
        raise SubstancesDocumentError(f"substances.json has no {', '.join(missing)}")
    return {key: document[key] for key in _SIGNED_FIELDS}


def _require_valid(manifest: Mapping[str, object]) -> None:
    violations = validate(dict(manifest), SchemaName.MANIFEST)
    if violations:
        raise ManifestInvalidError(violations)
    try:
        _text(manifest).encode("utf-8")
    except UnicodeEncodeError:
        # JSON can spell half of a surrogate pair ("\\ud800"), which is not text.
        raise ManifestFormatError(
            "the manifest holds text that is not valid Unicode (a lone surrogate)"
        ) from None


def _text(manifest: Mapping[str, object]) -> str:
    return json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)


def build_manifest(
    substances_bytes: bytes, *, min_app_version: str, date: datetime.date
) -> dict[str, object]:
    """Return the manifest of a release of the exact bytes of ``substances.json``.

    The versions and the attribution are read out of the document, and the hash is
    computed over the bytes as given. The result validates against the manifest
    schema, or ``ManifestInvalidError`` says why not (for example a version in the
    document, or ``min_app_version``, that is not ``MAJOR.MINOR.PATCH``).
    """
    manifest: dict[str, object] = {
        **_signed_fields(substances_bytes),
        "minAppVersion": min_app_version,
        "sha256": sha256_hex(substances_bytes),
        "date": date.isoformat(),
    }
    _require_valid(manifest)
    return manifest


def serialize_manifest(manifest: Mapping[str, object]) -> bytes:
    """Return the bytes of ``manifest.json``: the same manifest always gives the same bytes.

    Keys are sorted at every level, the indent is two spaces, text is UTF-8 and not
    escaped, and the file ends with one line feed. A manifest that breaks the schema
    (``ManifestInvalidError``) or holds text that is not valid Unicode
    (``ManifestFormatError``) is not written.
    """
    _require_valid(manifest)
    return (_text(manifest) + "\n").encode("utf-8")


def check_hash(manifest: Mapping[str, object], substances_bytes: bytes) -> None:
    """Raise ``ManifestHashMismatchError`` unless the manifest states the hash of the bytes."""
    stated = manifest.get("sha256")
    actual = sha256_hex(substances_bytes)
    if stated != actual:
        shown = stated if isinstance(stated, str) else "no text value"
        raise ManifestHashMismatchError(
            f"the manifest states the SHA-256 {shown}, and substances.json has {actual}"
        )


def check_versions(manifest: Mapping[str, object], substances_bytes: bytes) -> None:
    """Raise unless the manifest repeats what the signed document says about itself.

    ``ManifestSchemaVersionMismatchError``, ``ManifestDatasetVersionMismatchError``
    and ``ManifestAttributionMismatchError`` name the field that differs, in that
    order. A field that the manifest lacks differs.
    """
    signed = _signed_fields(substances_bytes)
    errors: dict[str, type[ManifestError]] = {
        "schemaVersion": ManifestSchemaVersionMismatchError,
        "datasetVersion": ManifestDatasetVersionMismatchError,
        "attribution": ManifestAttributionMismatchError,
    }
    for key, error in errors.items():
        if key not in manifest or not _same(manifest[key], signed[key]):
            raise error(
                f"{key} differs: the manifest states {_shown(manifest.get(key))}, and "
                f"substances.json states {_shown(signed[key])}"
            )


def check_manifest(manifest: Mapping[str, object], substances_bytes: bytes) -> None:
    """Check that the manifest describes exactly these bytes of ``substances.json``.

    The hash is checked first, then the schema version, the dataset version and the
    attribution, each with its own exception. This does not check the signature or
    the schemas: ``zadrya_data.release_check`` does all of it in the right order.
    """
    check_hash(manifest, substances_bytes)
    check_versions(manifest, substances_bytes)


def _same(left: object, right: object) -> bool:
    """Compare two JSON values, without Python's ``1 == 1.0 == True``."""
    return _canonical(left) == _canonical(right)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _shown(value: object) -> str:
    text = _canonical(value)
    return text if len(text) <= 80 else text[:77] + "..."
