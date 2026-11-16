# SPDX-License-Identifier: GPL-3.0-or-later
"""Ed25519 signatures of the dataset, and the keys they are made and checked with.

The signature covers the exact bytes of ``substances.json``. It is stored next to
the file as ``substances.json.sig``: the standard base64 (with padding) of the 64
signature bytes, followed by one line feed. The format and the reasons are in
``docs/adr/0003-dataset-signature.md``.

Two rules hold for everything in this module:

- Nothing fails open. Every function returns a result or raises a ``SigningError``.
- The private key is only ever read. Its content never reaches a message, a log or
  a file: errors about it name the file and the reason, never the bytes, and the
  exceptions of the parser are not chained.
"""

import base64
import binascii
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SIGNATURE_LENGTH = 64
PUBLIC_KEY_LENGTH = 32

# The spec pins two public keys in the app, so that they can be rotated: the
# current one and, during a rotation, the next one.
MAX_PINNED_KEYS = 2

KEY_FILE_VARIABLE = "ZADRYA_SIGNING_KEY_FILE"
KEY_PASSWORD_VARIABLE = "ZADRYA_SIGNING_KEY_PASSWORD"

_ENCODED_SIGNATURE_LENGTH = 89  # 88 base64 characters and the line feed


class SigningError(Exception):
    """Base of every error of this module."""


class SignatureFormatError(SigningError):
    """A signature, raw or encoded, does not have the one accepted form."""


class SignatureMismatchError(SigningError):
    """No pinned key made this signature over these bytes."""


class NoPinnedKeysError(SigningError):
    """There is no pinned public key to verify with."""


class TooManyPinnedKeysError(SigningError):
    """More public keys are pinned than a rotation needs."""


class KeyLoadError(SigningError):
    """A key file cannot be used."""


class SigningKeyNotConfiguredError(SigningError):
    """The environment does not say where the private key is."""


@dataclass(frozen=True)
class PinnedKey:
    """A public key that signatures are accepted from, with the name it is pinned under."""

    name: str
    public_key: Ed25519PublicKey

    @property
    def raw(self) -> bytes:
        """The 32 bytes of the key, which is what the app pins."""
        return public_key_raw(self.public_key)

    @property
    def base64(self) -> str:
        """The standard base64 of the 32 bytes of the key."""
        return public_key_base64(self.public_key)


def public_key_raw(public_key: Ed25519PublicKey) -> bytes:
    """Return the 32 bytes of the public key (RFC 8032 encoding)."""
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_key_base64(public_key: Ed25519PublicKey) -> str:
    """Return the standard base64, with padding, of the 32 bytes of the public key."""
    return base64.b64encode(public_key_raw(public_key)).decode("ascii")


def public_key_from_raw(raw: bytes) -> Ed25519PublicKey:
    """Return the public key that the 32 bytes encode."""
    if len(raw) != PUBLIC_KEY_LENGTH:
        raise KeyLoadError(
            f"an Ed25519 public key is {PUBLIC_KEY_LENGTH} bytes, found {len(raw)} bytes"
        )
    return Ed25519PublicKey.from_public_bytes(raw)


def sign(data: bytes, private_key: Ed25519PrivateKey) -> bytes:
    """Return the 64-byte Ed25519 signature of the exact bytes."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise KeyLoadError("the signing key is not an Ed25519 private key")
    return private_key.sign(data)


def verify(data: bytes, signature: bytes, public_keys: Sequence[PinnedKey]) -> PinnedKey:
    """Return the pinned key whose signature of the exact bytes this is.

    Raises ``NoPinnedKeysError`` when there is no key, ``TooManyPinnedKeysError``
    when there are more than ``MAX_PINNED_KEYS``, ``SignatureFormatError`` when the
    signature is not 64 bytes, and ``SignatureMismatchError`` when no key verifies:
    a tampered file, a tampered signature and a key that is not pinned look the same.
    """
    if len(public_keys) == 0:
        raise NoPinnedKeysError("no pinned public key was given, so nothing can be verified")
    if len(public_keys) > MAX_PINNED_KEYS:
        raise TooManyPinnedKeysError(
            f"{len(public_keys)} public keys are pinned, at most {MAX_PINNED_KEYS} are accepted"
        )
    if len(signature) != SIGNATURE_LENGTH:
        raise SignatureFormatError(
            f"an Ed25519 signature is {SIGNATURE_LENGTH} bytes, found {len(signature)} bytes"
        )
    for pinned in public_keys:
        try:
            pinned.public_key.verify(signature, data)
        except InvalidSignature:
            continue
        return pinned
    names = ", ".join(pinned.name for pinned in public_keys)
    raise SignatureMismatchError(
        f"the signature does not verify with any pinned key ({names}): the data or the "
        "signature was altered, or it was signed with a key that is not pinned"
    )


def encode_signature(signature: bytes) -> bytes:
    """Return the content of ``substances.json.sig`` for a 64-byte signature."""
    if len(signature) != SIGNATURE_LENGTH:
        raise SignatureFormatError(
            f"an Ed25519 signature is {SIGNATURE_LENGTH} bytes, found {len(signature)} bytes"
        )
    return base64.b64encode(signature) + b"\n"


def decode_signature(encoded: bytes) -> bytes:
    """Return the 64 signature bytes that the content of ``substances.json.sig`` holds.

    Exactly one spelling is accepted: 88 characters of the standard base64 alphabet
    (padding included) and one line feed. Anything else raises ``SignatureFormatError``.
    """
    if len(encoded) != _ENCODED_SIGNATURE_LENGTH:
        raise SignatureFormatError(
            f"a signature file is {_ENCODED_SIGNATURE_LENGTH} bytes (88 base64 characters "
            f"and one line feed), found {len(encoded)} bytes"
        )
    if not encoded.endswith(b"\n"):
        raise SignatureFormatError("a signature file ends with one line feed")
    try:
        signature = base64.b64decode(encoded[:-1], validate=True)
    except binascii.Error:
        raise SignatureFormatError("the signature is not standard base64") from None
    # 88 valid characters can still decode to another length (misplaced padding) or
    # spell the same bytes in a second way (unused bits set): one form only.
    if len(signature) != SIGNATURE_LENGTH or base64.b64encode(signature) != encoded[:-1]:
        raise SignatureFormatError("the signature is not the canonical base64 of 64 bytes")
    return signature


def private_key_path_from_env() -> Path:
    """Return the path of the private key file that ``ZADRYA_SIGNING_KEY_FILE`` names."""
    value = os.environ.get(KEY_FILE_VARIABLE, "")
    if value == "":
        raise SigningKeyNotConfiguredError(
            f"{KEY_FILE_VARIABLE} is not set: it must hold the path of the private key file "
            "(the key itself never goes in a variable of this name, nor in the repository)"
        )
    path = Path(value)
    if not path.is_file():
        raise KeyLoadError(f"{KEY_FILE_VARIABLE} names {path}, which is not an existing file")
    return path


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Read an Ed25519 private key from a PEM file (PKCS#8).

    An encrypted key needs its password in ``ZADRYA_SIGNING_KEY_PASSWORD``. Every
    failure raises ``KeyLoadError`` with the path and the reason, and nothing of the
    file content: the errors of the parser are deliberately not chained.
    """
    password = os.environ.get(KEY_PASSWORD_VARIABLE, "").encode("utf-8") or None
    try:
        content = path.read_bytes()
    except OSError as error:
        raise KeyLoadError(f"cannot read the private key file {path}: {error.strerror}") from None
    try:
        key = serialization.load_pem_private_key(content, password=password)
    except TypeError:
        if password is None:
            reason = f"it is encrypted and {KEY_PASSWORD_VARIABLE} is not set"
        else:
            reason = f"{KEY_PASSWORD_VARIABLE} is set and the key is not encrypted"
        raise KeyLoadError(f"cannot use the private key file {path}: {reason}") from None
    except (ValueError, UnsupportedAlgorithm):
        raise KeyLoadError(
            f"cannot use the private key file {path}: it is not a PEM (PKCS#8) private key, "
            "or the password is wrong"
        ) from None
    if not isinstance(key, Ed25519PrivateKey):
        raise KeyLoadError(f"the private key file {path} does not hold an Ed25519 key")
    return key


def _load_public_key(path: Path) -> Ed25519PublicKey:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise KeyLoadError(f"cannot read the public key file {path}: {error.strerror}") from None
    try:
        key = serialization.load_pem_public_key(content)
    except (ValueError, UnsupportedAlgorithm):
        raise KeyLoadError(
            f"the file {path} is not a PEM (SubjectPublicKeyInfo) public key"
        ) from None
    if not isinstance(key, Ed25519PublicKey):
        raise KeyLoadError(f"the public key file {path} does not hold an Ed25519 key")
    canonical = key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if content != canonical:
        raise KeyLoadError(
            f"the public key file {path} holds more than the key, or spells it in another "
            "way: it must be exactly the three lines of the PEM, with line feeds"
        )
    return key


def load_public_keys(directory: Path) -> tuple[PinnedKey, ...]:
    """Read the pinned public keys: every ``*.pem`` of the directory, sorted by name.

    Each file is one Ed25519 public key as PEM (SubjectPublicKeyInfo) and nothing
    else, and is named after its file without the extension. A directory without
    such a file raises ``NoPinnedKeysError``; a file that is not exactly such a
    key, and the same key twice, raise ``KeyLoadError``.
    """
    if not directory.is_dir():
        raise NoPinnedKeysError(f"no pinned public keys: {directory} is not a directory")
    paths = sorted(directory.glob("*.pem"), key=lambda path: path.name)
    if not paths:
        raise NoPinnedKeysError(f"no pinned public keys: {directory} holds no *.pem file")
    if len(paths) > MAX_PINNED_KEYS:
        raise TooManyPinnedKeysError(
            f"{directory} holds {len(paths)} public keys, at most {MAX_PINNED_KEYS} are "
            "accepted (the current one and the next one)"
        )
    pinned: list[PinnedKey] = []
    seen: dict[bytes, str] = {}
    for path in paths:
        key = _load_public_key(path)
        raw = public_key_raw(key)
        if raw in seen:
            raise KeyLoadError(f"{path.name} and {seen[raw]} hold the same public key")
        seen[raw] = path.name
        pinned.append(PinnedKey(name=path.stem, public_key=key))
    return tuple(pinned)
