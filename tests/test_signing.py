# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for signing, verification, the signature file format and key loading.

Every private key here is created by the test that uses it and lives in memory or
in the temporary directory of that test. No private key is ever committed, and the
committed vectors are public material only (public keys, messages, signatures).
"""

import base64
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from zadrya_data.signing import (
    KEY_FILE_VARIABLE,
    KEY_PASSWORD_VARIABLE,
    KeyLoadError,
    NoPinnedKeysError,
    PinnedKey,
    SignatureFormatError,
    SignatureMismatchError,
    SigningKeyNotConfiguredError,
    TooManyPinnedKeysError,
    decode_signature,
    encode_signature,
    is_small_order,
    load_private_key,
    load_public_keys,
    private_key_path_from_env,
    public_key_base64,
    public_key_from_raw,
    public_key_raw,
    sign,
    verify,
)

KEYS_DIRECTORY = Path(__file__).parents[1] / "keys"

DATA = b'{"substances": []}\n'

# RFC 8032, section 7.1, test 1: public key, message (empty) and signature.
RFC_8032_PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
RFC_8032_MESSAGE = b""
RFC_8032_SIGNATURE = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46b"
    "d25bf5f0595bbe24655141438e7a100b"
)

# Made once with a key that was never stored: the public key as the app pins it
# (base64 of the 32 bytes), a message, and the content of the signature file.
VECTOR_PUBLIC_KEY_BASE64 = "VsSDXcblStZYUVXAXtuLVLgyOUWHrAHPhIuLQtUlEz8="
VECTOR_MESSAGE = b'{"zadrya": "signature format test vector"}\n'
VECTOR_SIGNATURE_FILE = (
    b"9OCpXV8BXM20aFaB7Rf0iopgidcGnOx7p2+ZM+ypABn+FL5ezWkVeGer9pO/FHLC/LxW20M8y8NjgC6/6Z6PCA==\n"
)


def _pinned(name: str, private_key: Ed25519PrivateKey) -> PinnedKey:
    return PinnedKey(name=name, public_key=private_key.public_key())


def _private_pem(private_key: Ed25519PrivateKey | ec.EllipticCurvePrivateKey) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _encrypted_pem(private_key: Ed25519PrivateKey, password: bytes) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )


def _public_pem(private_key: Ed25519PrivateKey | ec.EllipticCurvePrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


# ---- sign and verify


def test_a_signature_verifies_with_its_key_and_says_which() -> None:
    private_key = Ed25519PrivateKey.generate()
    signature = sign(DATA, private_key)

    assert len(signature) == 64
    assert verify(DATA, signature, [_pinned("current", private_key)]).name == "current"


@pytest.mark.parametrize("position", [0, 1])
def test_either_of_two_pinned_keys_is_accepted_and_reported(position: int) -> None:
    keys = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    pinned = [_pinned("current", keys[0]), _pinned("next", keys[1])]

    matched = verify(DATA, sign(DATA, keys[position]), pinned)

    assert matched is pinned[position]


def test_a_key_that_is_not_pinned_is_rejected() -> None:
    signature = sign(DATA, Ed25519PrivateKey.generate())
    pinned = [_pinned("current", Ed25519PrivateKey.generate())]

    with pytest.raises(SignatureMismatchError, match=r"any pinned key \(current\)"):
        verify(DATA, signature, pinned)


def test_every_single_bit_flip_of_the_data_is_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    signature = sign(DATA, private_key)
    pinned = [_pinned("current", private_key)]

    for index in range(len(DATA)):
        tampered = bytearray(DATA)
        tampered[index] ^= 0x01
        with pytest.raises(SignatureMismatchError):
            verify(bytes(tampered), signature, pinned)


def test_appended_and_removed_bytes_are_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    signature = sign(DATA, private_key)
    pinned = [_pinned("current", private_key)]

    for tampered in (DATA + b"\n", DATA[:-1], b""):
        with pytest.raises(SignatureMismatchError):
            verify(tampered, signature, pinned)


def test_a_tampered_signature_is_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    signature = bytearray(sign(DATA, private_key))
    signature[10] ^= 0x01

    with pytest.raises(SignatureMismatchError):
        verify(DATA, bytes(signature), [_pinned("current", private_key)])


@pytest.mark.parametrize("length", [0, 1, 32, 63, 65, 128])
def test_a_signature_of_another_length_is_rejected(length: int) -> None:
    private_key = Ed25519PrivateKey.generate()
    signature = (sign(DATA, private_key) * 2)[:length]

    with pytest.raises(SignatureFormatError, match=f"64 bytes, found {length} bytes"):
        verify(DATA, signature, [_pinned("current", private_key)])


def test_an_empty_key_set_is_rejected_even_for_a_good_signature() -> None:
    signature = sign(DATA, Ed25519PrivateKey.generate())

    with pytest.raises(NoPinnedKeysError):
        verify(DATA, signature, [])


def test_more_keys_than_a_rotation_needs_are_rejected() -> None:
    keys = [Ed25519PrivateKey.generate() for _ in range(3)]
    pinned = [_pinned(f"key-{index}", key) for index, key in enumerate(keys)]

    with pytest.raises(TooManyPinnedKeysError, match="3 public keys are pinned, at most 2"):
        verify(DATA, sign(DATA, keys[0]), pinned)


def test_sign_refuses_a_key_of_another_type() -> None:
    other = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(KeyLoadError, match="not an Ed25519 private key"):
        sign(DATA, other)  # type: ignore[arg-type]


def test_verification_is_plain_ed25519_rfc_8032_test_vector_1() -> None:
    pinned = [PinnedKey(name="rfc-8032", public_key=public_key_from_raw(RFC_8032_PUBLIC_KEY))]

    assert verify(RFC_8032_MESSAGE, RFC_8032_SIGNATURE, pinned).name == "rfc-8032"
    with pytest.raises(SignatureMismatchError):
        verify(b"\x00", RFC_8032_SIGNATURE, pinned)


# ---- signature file


def test_signature_file_format_is_pinned_by_a_fixed_vector() -> None:
    public_key = public_key_from_raw(base64.b64decode(VECTOR_PUBLIC_KEY_BASE64))
    pinned = [PinnedKey(name="vector", public_key=public_key)]

    signature = decode_signature(VECTOR_SIGNATURE_FILE)

    assert verify(VECTOR_MESSAGE, signature, pinned).name == "vector"
    assert encode_signature(signature) == VECTOR_SIGNATURE_FILE
    assert public_key_base64(public_key) == VECTOR_PUBLIC_KEY_BASE64


def test_signature_file_is_88_base64_characters_and_a_line_feed() -> None:
    signature = sign(DATA, Ed25519PrivateKey.generate())

    encoded = encode_signature(signature)

    assert encoded == base64.b64encode(signature) + b"\n"
    assert len(encoded) == 89 and encoded.endswith(b"==\n")
    assert decode_signature(encoded) == signature


@pytest.mark.parametrize("length", [0, 63, 65])
def test_encode_refuses_a_signature_of_another_length(length: int) -> None:
    with pytest.raises(SignatureFormatError, match=f"found {length} bytes"):
        encode_signature(b"\x01" * length)


_GOOD = base64.b64encode(bytes(range(64)))


@pytest.mark.parametrize(
    "encoded",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\n", id="only-a-line-feed"),
        pytest.param(_GOOD, id="no-line-feed"),
        pytest.param(_GOOD + b"\n\n", id="two-line-feeds"),
        pytest.param(_GOOD + b"\r\n", id="carriage-return"),
        pytest.param(b" " + _GOOD + b"\n", id="leading-space"),
        pytest.param(_GOOD + b" \n", id="trailing-space"),
        pytest.param(_GOOD[:-4] + b"\n", id="truncated"),
        pytest.param(_GOOD[:44] + b"\n" + _GOOD[44:], id="line-feed-inside"),
        pytest.param(_GOOD[:40] + b"\n" + _GOOD[40:87] + b"\n", id="line-feed-instead-of-data"),
        pytest.param(_GOOD[:-1] + b" ", id="space-instead-of-line-feed"),
        pytest.param(b"!" + _GOOD[1:] + b"\n", id="not-base64"),
        pytest.param(_GOOD + b"A\n", id="too-long"),
        pytest.param(base64.urlsafe_b64encode(b"\xff" * 64) + b"\n", id="url-safe-alphabet"),
        pytest.param(_GOOD[:-2] + b"\n", id="no-padding"),
        pytest.param(_GOOD[:-3] + b"===\n", id="misplaced-padding"),
        pytest.param(base64.b64encode(bytes(65))[:88] + b"\n", id="65-bytes-in-88-characters"),
        pytest.param(_GOOD[:-3] + b"/==\n", id="unused-bits-set"),
        pytest.param(bytes(64), id="raw-signature"),
        pytest.param(bytes(range(64)).hex().encode("ascii"), id="hexadecimal"),
    ],
)
def test_decode_refuses_everything_but_the_one_spelling(encoded: bytes) -> None:
    with pytest.raises(SignatureFormatError):
        decode_signature(encoded)


def test_unused_bits_case_really_is_a_second_spelling_of_the_same_bytes() -> None:
    lenient = base64.b64decode(_GOOD[:-3] + b"/==")

    assert lenient == bytes(range(64))


# ---- public key forms


def test_raw_and_base64_forms_of_a_public_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    pinned = _pinned("current", private_key)

    assert len(pinned.raw) == 32
    assert pinned.raw == public_key_raw(private_key.public_key())
    assert pinned.base64 == base64.b64encode(pinned.raw).decode("ascii")
    assert public_key_raw(public_key_from_raw(pinned.raw)) == pinned.raw


@pytest.mark.parametrize("length", [0, 31, 33])
def test_a_raw_public_key_of_another_length_is_rejected(length: int) -> None:
    with pytest.raises(KeyLoadError, match=f"32 bytes, found {length} bytes"):
        public_key_from_raw(bytes(length))


# ---- points of small order

_P = 2**255 - 19
_D = -121665 * pow(121666, -1, _P) % _P

# Every encoding of the eight points of small order: the seven y values (two of
# them, p and p + 1, are non-canonical spellings of 0 and 1), each with both signs.
SMALL_ORDER_Y = [
    0,
    1,
    _P - 1,
    _P,
    _P + 1,
    int.from_bytes(
        bytes.fromhex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"), "little"
    ),
    int.from_bytes(
        bytes.fromhex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"), "little"
    ),
]
SMALL_ORDER_ENCODINGS = [
    (y | (sign << 255)).to_bytes(32, "little") for y in SMALL_ORDER_Y for sign in (0, 1)
]

# R is the neutral point and S is zero: with the neutral point as the public key,
# this "signature" verifies for every message.
FORGED_SIGNATURE = (1).to_bytes(32, "little") + bytes(32)


def _add(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int]:
    """Add two points of the twisted Edwards curve of Ed25519."""
    (x1, y1), (x2, y2) = first, second
    k = _D * x1 * x2 * y1 * y2 % _P
    return (
        (x1 * y2 + x2 * y1) * pow(1 + k, -1, _P) % _P,
        (y1 * y2 + x1 * x2) * pow(1 - k, -1, _P) % _P,
    )


def _x(y: int) -> int:
    """Recover an x coordinate of the point with this y (RFC 8032, section 5.1.3)."""
    x_squared = (y * y - 1) * pow(_D * y * y + 1, -1, _P) % _P
    x = pow(x_squared, (_P + 3) // 8, _P)
    if x * x % _P != x_squared:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    assert x * x % _P == x_squared
    return x


@pytest.mark.parametrize("y", SMALL_ORDER_Y)
def test_the_listed_points_really_have_small_order(y: int) -> None:
    point = (_x(y % _P), y % _P)
    multiple, order = point, 1
    while multiple != (0, 1):
        multiple, order = _add(multiple, point), order + 1
        assert order <= 8

    assert order in (1, 2, 4, 8)


def test_the_forgery_works_against_the_library_without_the_check() -> None:
    """Why the check exists: the library accepts the key and the forged signature."""
    neutral = Ed25519PublicKey.from_public_bytes((1).to_bytes(32, "little"))

    neutral.verify(FORGED_SIGNATURE, b"any message")
    neutral.verify(FORGED_SIGNATURE, DATA)


@pytest.mark.parametrize(
    "raw", SMALL_ORDER_ENCODINGS, ids=lambda raw: raw.hex()[:8] + raw.hex()[-2:]
)
def test_a_point_of_small_order_is_refused_wherever_a_key_enters(
    tmp_path: Path, raw: bytes
) -> None:
    assert is_small_order(raw)
    with pytest.raises(KeyLoadError, match="point of small order"):
        public_key_from_raw(raw)

    key = Ed25519PublicKey.from_public_bytes(raw)
    (tmp_path / "current.pem").write_bytes(
        key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    with pytest.raises(KeyLoadError, match="current.pem is a point of small order"):
        load_public_keys(tmp_path)

    honest = _pinned("current", Ed25519PrivateKey.generate())
    with pytest.raises(KeyLoadError, match="the pinned key weak is a point of small order"):
        verify(DATA, FORGED_SIGNATURE, [honest, PinnedKey(name="weak", public_key=key)])


def test_the_forged_signature_is_rejected_for_real_keys() -> None:
    pinned = [_pinned("current", Ed25519PrivateKey.generate())]

    with pytest.raises(SignatureMismatchError):
        verify(DATA, FORGED_SIGNATURE, pinned)


def test_real_keys_are_not_points_of_small_order() -> None:
    assert not is_small_order(RFC_8032_PUBLIC_KEY)
    assert not is_small_order(base64.b64decode(VECTOR_PUBLIC_KEY_BASE64))
    assert len(set(SMALL_ORDER_ENCODINGS)) == 14


# ---- pinned public keys


def test_public_keys_are_loaded_sorted_by_name(tmp_path: Path) -> None:
    first, second = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    (tmp_path / "next.pem").write_bytes(_public_pem(second))
    (tmp_path / "current.pem").write_bytes(_public_pem(first))
    (tmp_path / "README.md").write_text("not a key\n", encoding="utf-8")

    pinned = load_public_keys(tmp_path)

    assert [key.name for key in pinned] == ["current", "next"]
    assert pinned[0].raw == public_key_raw(first.public_key())
    assert verify(DATA, sign(DATA, second), pinned).name == "next"


def test_a_directory_with_only_the_readme_has_no_pinned_keys(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("no keys yet\n", encoding="utf-8")

    with pytest.raises(NoPinnedKeysError, match=r"holds no \*\.pem file"):
        load_public_keys(tmp_path)


def test_a_missing_directory_has_no_pinned_keys(tmp_path: Path) -> None:
    with pytest.raises(NoPinnedKeysError, match="is not a directory"):
        load_public_keys(tmp_path / "keys")


def test_the_keys_directory_of_the_repository_is_usable_or_empty() -> None:
    """Passes with no key (today) and with pinned keys: any other state fails."""
    assert (KEYS_DIRECTORY / "README.md").is_file()
    try:
        pinned = load_public_keys(KEYS_DIRECTORY)
    except NoPinnedKeysError:
        assert list(KEYS_DIRECTORY.glob("*.pem")) == []
    else:
        assert 1 <= len(pinned) <= 2


def test_three_public_keys_are_too_many(tmp_path: Path) -> None:
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.pem").write_bytes(_public_pem(Ed25519PrivateKey.generate()))

    with pytest.raises(TooManyPinnedKeysError, match="holds 3 public keys"):
        load_public_keys(tmp_path)


def test_the_same_public_key_twice_is_rejected(tmp_path: Path) -> None:
    pem = _public_pem(Ed25519PrivateKey.generate())
    (tmp_path / "current.pem").write_bytes(pem)
    (tmp_path / "next.pem").write_bytes(pem)

    with pytest.raises(KeyLoadError, match="next.pem and current.pem hold the same public key"):
        load_public_keys(tmp_path)


def test_a_public_key_of_another_type_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "current.pem").write_bytes(_public_pem(ec.generate_private_key(ec.SECP256R1())))

    with pytest.raises(KeyLoadError, match="does not hold an Ed25519 key"):
        load_public_keys(tmp_path)


def test_a_private_key_in_the_keys_directory_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "current.pem").write_bytes(_private_pem(Ed25519PrivateKey.generate()))

    with pytest.raises(KeyLoadError, match="is not a PEM .* public key"):
        load_public_keys(tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"not a key\n", id="text"),
        pytest.param(base64.b64encode(bytes(32)) + b"\n", id="raw-base64"),
    ],
)
def test_a_file_that_is_not_a_pem_public_key_is_rejected(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "current.pem").write_bytes(content)

    with pytest.raises(KeyLoadError, match="is not a PEM .* public key"):
        load_public_keys(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda pem: b"# current key\n" + pem, id="leading-comment"),
        pytest.param(lambda pem: pem + b"\n", id="trailing-blank-line"),
        pytest.param(lambda pem: pem.replace(b"\n", b"\r\n"), id="carriage-returns"),
        pytest.param(lambda pem: pem + pem, id="two-keys-in-one-file"),
    ],
)
def test_a_public_key_file_holds_the_key_and_nothing_else(
    tmp_path: Path, change: Callable[[bytes], bytes]
) -> None:
    (tmp_path / "current.pem").write_bytes(change(_public_pem(Ed25519PrivateKey.generate())))

    with pytest.raises(KeyLoadError, match="holds more than the key"):
        load_public_keys(tmp_path)


def test_an_unreadable_public_key_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "current.pem").mkdir()

    with pytest.raises(KeyLoadError, match="cannot read the public key file"):
        load_public_keys(tmp_path)


# ---- private key


def test_private_key_path_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "signing.pem"
    path.write_bytes(_private_pem(Ed25519PrivateKey.generate()))
    monkeypatch.setenv(KEY_FILE_VARIABLE, str(path))

    assert KEY_FILE_VARIABLE == "ZADRYA_SIGNING_KEY_FILE"
    assert private_key_path_from_env() == path


@pytest.mark.parametrize("value", [None, ""])
def test_an_unset_or_empty_key_path_variable_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(KEY_FILE_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(KEY_FILE_VARIABLE, value)

    with pytest.raises(SigningKeyNotConfiguredError, match="ZADRYA_SIGNING_KEY_FILE is not set"):
        private_key_path_from_env()


def test_a_key_path_that_is_not_a_file_fails_without_showing_the_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(KEY_FILE_VARIABLE, str(tmp_path / "missing-file.pem"))

    with pytest.raises(KeyLoadError) as caught:
        private_key_path_from_env()

    assert str(caught.value) == "ZADRYA_SIGNING_KEY_FILE does not name an existing file"
    assert "missing-file" not in repr(caught.value)


def _one_line(pem: bytes) -> bytes:
    return pem.replace(b"\n", b"")


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param(lambda key: _private_pem(key), id="plain"),
        pytest.param(lambda key: _encrypted_pem(key, b"throwaway test password"), id="encrypted"),
        pytest.param(lambda key: _one_line(_private_pem(key)), id="one-line"),
        pytest.param(
            lambda key: _one_line(_encrypted_pem(key, b"throwaway test password")),
            id="encrypted-one-line",
        ),
        pytest.param(lambda key: _private_pem(key).replace(b"\n", b"\\n"), id="escaped-breaks"),
        pytest.param(lambda key: _private_pem(key).replace(b"\n", b"\r\n"), id="carriage-returns"),
    ],
)
def test_a_key_put_in_the_path_variable_is_never_shown(
    monkeypatch: pytest.MonkeyPatch, spelling: Callable[[Ed25519PrivateKey], bytes]
) -> None:
    value = spelling(Ed25519PrivateKey.generate()).decode("ascii")
    monkeypatch.setenv(KEY_FILE_VARIABLE, value)

    with pytest.raises(KeyLoadError, match="looks like the key itself, not a path") as caught:
        private_key_path_from_env()

    error = caught.value
    shown = str(error) + repr(error) + repr(error.args) + repr(vars(error))
    # No run of eight characters of the value appears anywhere in the error.
    pieces = {value[start : start + 8] for start in range(len(value) - 7)}
    assert not [piece for piece in pieces if piece in shown]
    assert "BEGIN" not in shown and "\n" not in shown
    assert error.__cause__ is None and error.__context__ is None


def test_an_error_of_the_file_system_about_the_value_is_not_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some systems answer a very long name with an error that quotes it."""
    value = _one_line(_private_pem(Ed25519PrivateKey.generate())).decode("ascii")
    monkeypatch.setenv(KEY_FILE_VARIABLE, value)

    def too_long(self: Path) -> bool:
        raise OSError(63, "File name too long", str(self))

    monkeypatch.setattr(Path, "is_file", too_long)

    with pytest.raises(KeyLoadError, match="looks like the key itself") as caught:
        private_key_path_from_env()

    assert value[20:40] not in str(caught.value) + repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_key_body_alone_in_the_path_variable_is_not_shown_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the PEM lines there is nothing to recognize: no hint, and still no value."""
    body = _private_pem(Ed25519PrivateKey.generate()).splitlines()[1].decode("ascii")
    monkeypatch.setenv(KEY_FILE_VARIABLE, body)

    with pytest.raises(KeyLoadError) as caught:
        private_key_path_from_env()

    assert str(caught.value) == "ZADRYA_SIGNING_KEY_FILE does not name an existing file"
    assert body[:8] not in repr(caught.value)


def test_an_unencrypted_private_key_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = Ed25519PrivateKey.generate()
    path = tmp_path / "signing.pem"
    path.write_bytes(_private_pem(private_key))
    monkeypatch.delenv(KEY_PASSWORD_VARIABLE, raising=False)

    loaded = load_private_key(path)

    assert verify(DATA, sign(DATA, loaded), [_pinned("current", private_key)]).name == "current"


def test_an_encrypted_private_key_needs_its_password_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = Ed25519PrivateKey.generate()
    path = tmp_path / "signing.pem"
    path.write_bytes(_encrypted_pem(private_key, b"throwaway test password"))

    monkeypatch.setenv(KEY_PASSWORD_VARIABLE, "throwaway test password")
    loaded = load_private_key(path)
    assert verify(DATA, sign(DATA, loaded), [_pinned("current", private_key)]).name == "current"

    monkeypatch.setenv(KEY_PASSWORD_VARIABLE, "another password")
    with pytest.raises(KeyLoadError, match="or the password is wrong"):
        load_private_key(path)

    monkeypatch.delenv(KEY_PASSWORD_VARIABLE)
    with pytest.raises(KeyLoadError, match="encrypted and ZADRYA_SIGNING_KEY_PASSWORD is not set"):
        load_private_key(path)

    monkeypatch.setenv(KEY_PASSWORD_VARIABLE, "")
    with pytest.raises(KeyLoadError, match="encrypted and ZADRYA_SIGNING_KEY_PASSWORD is not set"):
        load_private_key(path)


def test_a_password_for_an_unencrypted_key_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "signing.pem"
    path.write_bytes(_private_pem(Ed25519PrivateKey.generate()))
    monkeypatch.setenv(KEY_PASSWORD_VARIABLE, "throwaway test password")

    with pytest.raises(KeyLoadError, match="is set and the key is not encrypted"):
        load_private_key(path)


def test_a_private_key_of_another_type_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "signing.pem"
    path.write_bytes(_private_pem(ec.generate_private_key(ec.SECP256R1())))
    monkeypatch.delenv(KEY_PASSWORD_VARIABLE, raising=False)

    with pytest.raises(KeyLoadError, match="does not hold an Ed25519 key"):
        load_private_key(path)


def test_a_missing_private_key_file_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY_PASSWORD_VARIABLE, raising=False)

    with pytest.raises(KeyLoadError, match="cannot read the private key file"):
        load_private_key(tmp_path / "missing.pem")


@pytest.mark.parametrize("damage", ["truncate", "corrupt", "public"])
def test_errors_about_a_private_key_never_show_its_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    private_key = Ed25519PrivateKey.generate()
    pem = _private_pem(private_key)
    body = pem.splitlines()[1]
    content = {
        "truncate": pem[:-30],
        "corrupt": pem.replace(body, body[:20] + b"!!!!" + body[24:]),
        "public": _public_pem(private_key),
    }[damage]
    path = tmp_path / "signing.pem"
    path.write_bytes(content)
    monkeypatch.delenv(KEY_PASSWORD_VARIABLE, raising=False)

    with pytest.raises(KeyLoadError) as caught:
        load_private_key(path)

    shown = str(caught.value) + repr(caught.value)
    assert str(path) in shown
    assert body[:16].decode("ascii") not in shown
    # The parser's own error is not chained, so a traceback cannot show more.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
