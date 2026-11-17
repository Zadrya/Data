# SPDX-License-Identifier: GPL-3.0-or-later
"""The full acceptance check of a release, as the app performs it.

A release is three files: ``substances.json``, ``substances.json.sig`` and
``manifest.json``. ``verify_release`` accepts them or raises, in this order:

1. Signature: the signature file has the one accepted form, and the signature of
   the exact bytes of ``substances.json`` verifies with a pinned key.
2. Hash: the manifest is a strict JSON object and states the SHA-256 of those bytes.
3. Schemas: the manifest and the dataset are each valid against their schema.
4. Consistency: the versions and the attribution in the manifest equal those in
   the signed dataset.

The signature comes first so that nothing of an unauthenticated dataset is parsed.
The order and its reasons are in ``docs/adr/0003-dataset-signature.md``.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from zadrya_data.errors import ReleaseRejectedError
from zadrya_data.manifest import (
    check_hash,
    check_versions,
    parse_manifest,
    parse_substances,
    sha256_hex,
)
from zadrya_data.schema import SchemaName, SchemaViolation, validate
from zadrya_data.signing import PinnedKey, decode_signature, verify


class ReleaseSchemaError(ReleaseRejectedError):
    """A file of the release breaks its schema."""

    def __init__(self, name: SchemaName, violations: list[SchemaViolation]) -> None:
        self.name = name
        self.violations = violations
        shown = "; ".join(str(violation) for violation in violations[:5])
        more = f" (and {len(violations) - 5} more)" if len(violations) > 5 else ""
        super().__init__(f"{name.value}.json is not valid: {shown}{more}")


@dataclass(frozen=True)
class VerifiedRelease:
    """What an accepted release is, and the pinned key that signed it.

    ``dataset_version``, ``schema_version`` and ``sha256`` are covered by the
    signature: they come from, or are computed over, the signed bytes.
    ``unsigned_min_app_version`` is not. It exists only in the manifest, which
    anyone who can replace that file can edit, so it may be used to refuse a
    release and never as the reason to accept one. The date of the manifest is
    not authenticated either and is not exposed here.
    """

    key: PinnedKey
    dataset_version: str
    schema_version: str
    unsigned_min_app_version: str
    sha256: str


def _require_valid(document: object, name: SchemaName) -> None:
    violations = validate(document, name)
    if violations:
        raise ReleaseSchemaError(name, violations)


def verify_release(
    *,
    substances: bytes,
    signature_file: bytes,
    manifest: bytes,
    public_keys: Sequence[PinnedKey],
) -> VerifiedRelease:
    """Accept the three files of a release, given as their exact bytes, or raise.

    Every refusal is a ``zadrya_data.errors.ReleaseRejectedError``: a
    ``zadrya_data.signing.SigningError`` for step 1, a
    ``zadrya_data.manifest.ManifestError`` for steps 2 and 4 (and for a file that is
    not strict JSON), and ``ReleaseSchemaError`` for step 3. There is no other
    outcome: a release is never partly accepted.
    """
    key = verify(substances, decode_signature(signature_file), public_keys)

    manifest_document = parse_manifest(manifest)
    check_hash(manifest_document, substances)

    _require_valid(manifest_document, SchemaName.MANIFEST)
    signed = parse_substances(substances)
    _require_valid(signed, SchemaName.SUBSTANCES)

    check_versions(manifest_document, substances)

    return VerifiedRelease(
        key=key,
        dataset_version=str(signed["datasetVersion"]),
        schema_version=str(signed["schemaVersion"]),
        unsigned_min_app_version=str(manifest_document["minAppVersion"]),
        sha256=sha256_hex(substances),
    )
