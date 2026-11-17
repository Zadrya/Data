# 3. Dataset signature

- Status: accepted. One decision is pending with the owner: whether the manifest gets its own signature (see "Signing the manifest: owner decision pending"). The default is three assets, as the spec says.
- Date: 2026-11-16

## Context

The spec (`Application/docs/SPEC.md`, "Substance dataset") says that a release is `substances.json`, `substances.json.sig` and `manifest.json`, that the dataset is signed with Ed25519, that the app pins two public keys so they can be rotated, and that a downloaded dataset is accepted only with a valid signature, the correct SHA-256 and a compatible schema version. It does not say what the signature file contains, what exactly is signed, in which order the checks run, or how keys are stored.

The private key belongs to the owner. It is generated on the owner's machine, lives outside every repository, and is never generated, read or handled by an assistant. This repository holds public keys only.

The same checks run in two implementations: Python here (`cryptography`) and Dart in the app (`cryptography`). A rule the two read differently is a bug, so every format below has exactly one accepted spelling.

## Decision

### What is signed

The signature is pure Ed25519 (RFC 8032, no prehash and no context) over the exact bytes of `substances.json` as published. Nothing is normalized, parsed or re-serialized before signing or verifying: a single changed byte, including a trailing line feed, invalidates the signature. A test checks the verify path against test vector 1 of RFC 8032, section 7.1.

### Signature file

`substances.json.sig` is the standard base64 (RFC 4648 alphabet with `+` and `/`, with padding) of the 64 signature bytes, followed by one line feed: always 89 bytes. `decode_signature` accepts that spelling and no other. It rejects a missing or doubled line feed, a carriage return, spaces, the URL-safe alphabet, missing or misplaced padding, any other length, and a final character whose unused bits are set (a second spelling of the same bytes). Text was chosen over 64 raw bytes because it survives copy and paste and is readable in a release page; one spelling was chosen so that the two implementations cannot disagree.

### Verification order

`zadrya_data.release_check.verify_release` is the full acceptance check, and the app performs the same steps in the same order:

1. **Signature.** Decode the signature file and verify the bytes of `substances.json` with the pinned keys. Until this passes, no parser reads the dataset: the only untrusted input handled is a base64 string of fixed length.
2. **Hash.** Read the manifest as strict JSON and compare its `sha256` with the SHA-256 of the bytes.
3. **Schemas.** Validate the manifest and the dataset against their schemas. `substances.schema.json` accepts only `schemaVersion` 1.x.y, so a dataset of an unsupported major version is rejected here, and that version is inside the signed bytes.
4. **Consistency.** `schemaVersion`, `datasetVersion` and `attribution` in the manifest must equal those in the dataset.

Each failure has its own exception, and there is no partial acceptance. After step 1 the hash adds no security, because the signature already binds the bytes. It stays because the spec asks for it and because it detects a manifest and a dataset that come from different releases.

### Verification with several keys

`verify` takes the pinned keys and returns the one that verified, so a release log can say which key signed. It fails with a specific exception when there is no key (`NoPinnedKeysError`), when there are more than two (`TooManyPinnedKeysError`: the spec pins two, and a longer list is a rotation that was never finished), when a pinned key is a point of small order (`KeyLoadError`), when the signature is not 64 bytes, and when no key verifies. A tampered file, a tampered signature and a key that is not pinned are deliberately the same error: the verifier cannot tell them apart.

### Key formats

- **Private key**: a PEM file (PKCS#8), Ed25519 only, either unencrypted or encrypted with a password. The file holds exactly one key and nothing else (trailing data, a second key and the traditional or OpenSSH forms are refused), and it must not be accessible to the group or to others (mode 0600 or stricter). The file is named by the environment variable `ZADRYA_SIGNING_KEY_FILE`; the password, when there is one, is in `ZADRYA_SIGNING_KEY_PASSWORD` (empty counts as unset). A password for an unencrypted key is an error, so a mistake is noticed. The module only reads the key. Its error messages name the file and the reason, never the content, the password or the value of the path variable (the likely mistake is to put the key itself in it). Reading and parsing happen in a helper that returns a reason, so the error that is raised has no cause, no context and no frame that holds the key. That limits what a traceback or an error report can show; it is not a defense against a debugger or a memory dump of the signing process.
- **Public keys**: one `*.pem` file per key in `keys/` (SubjectPublicKeyInfo), read in the order of the file names, at most two. A file must be exactly the canonical PEM of an Ed25519 public key: comments, blank lines, carriage returns, a second key, another key type, a private key, a point of small order and the same key under two names are rejected. An empty `keys/` means "no pinned keys" and every verification fails.
- **In the app**: the raw 32 bytes of each key (RFC 8032 encoding), which `PinnedKey.raw` and `PinnedKey.base64` give.

### Rotation

A release is accepted when any one pinned key verifies, so keys are rotated without a gap: add the new public key, ship an app that pins both, start signing with the new key, later remove the old one. The steps, and what to do when a key is lost or exposed, are in `keys/README.md`. There is no revocation list: a key stops being trusted by an app only when an app version that no longer pins it is installed. A lost key is therefore harmless, and an exposed key is not, until that update.

### What the unsigned manifest leaves open

The manifest has no signature of its own. Everything in it that matters for trust is either derived from the signed bytes or compared with them:

| Manifest field | Protection |
| --- | --- |
| `sha256` | Compared with the hash of the signed bytes (step 2). |
| `schemaVersion`, `datasetVersion` | Copied from the signed dataset when the manifest is built, compared with it when checked (step 4). |
| `attribution` | Same as the versions: the app shows it, and a license statement should not be alterable. |
| `minAppVersion` | **None.** It exists only in the manifest. |
| `date` | **None.** It exists only in the manifest, so that the dataset stays reproducible. |

An attacker who can alter the manifest but cannot sign (a compromised release asset, a compromised account without the key, or a broken transport) therefore:

- **cannot** make the app accept a dataset the owner did not sign, change a single byte of the content, or make the app believe another dataset version, schema version or attribution than the signed one;
- **can lower `minAppVersion`**, so that an app older than the owner intended accepts a correctly signed dataset. The schema major version, which is signed, still stops a dataset the app cannot read, so what is lost is the owner's ability to exclude old apps within one schema major version;
- **can raise `minAppVersion`**, so that apps refuse a good update and stay on what they have. Deleting or corrupting any of the three files has the same effect, with or without a signed manifest;
- **can change `date`**, which is display only.

Two limits do not depend on the manifest at all:

- **Replay.** An old release, complete and correctly signed, verifies forever.
- **Freeze.** Nobody can prove that a newer release exists. Withholding updates cannot be detected without an expiry date, which the spec does not have.

`VerifiedRelease` reflects this: `dataset_version` and `schema_version` are read from the signed bytes, and the manifest value is named `unsigned_min_app_version`. The date is not exposed.

### Signing the manifest: owner decision pending

**Status: pending. The default, and what is implemented, is three assets as the spec says.** Both positions are recorded so that the owner can decide.

**Keep three assets (the security review's assessment, and the default).**

- The design is not unsafe. Nothing that decides what the app trusts is unprotected, as long as the app follows the rules of the next section.
- The gain of a signed manifest is small: it protects `minAppVersion` and `date` only, and it does nothing about replay or freeze, which are the larger limits.
- It costs a change to the spec (a fourth release asset) and puts a second kind of file under the same key, which needs a rule to keep the two kinds apart.
- It can be added later without a transition: an app that knows about `manifest.json.sig` can require it from the release that first ships it, and older apps ignore an asset they do not download.

**Sign the manifest now (the position of the first version of this ADR).**

- It makes `minAppVersion` an enforceable kill switch: the one field the owner would use to keep old apps away from a dataset in an emergency would no longer be the one field anyone can edit.
- The cost in code is one more call to `sign` in the release and one more call to `verify` in the app.
- If this is chosen, the manifest signature must be domain separated: sign a fixed prefix followed by the manifest bytes (for example the ASCII line `zadrya-manifest-v1` and a line feed), so that a signature of a manifest can never be presented as a signature of a dataset or the reverse, whatever the two files contain. Relying on each file failing the schema of the other is true today and is not a property to build on.

The question that decides it: should `minAppVersion` be able to make an app accept something (then it must be signed), or only to make an app refuse (then it need not be)? With the rules below it can only refuse, which is why three assets is a defensible default.

### What the app must do in either case

These rules hold with or without a signed manifest, and no file format can enforce them:

- **Compatibility is decided by the signed `schemaVersion`.** The app accepts a dataset only if the major version inside the signed bytes is one it supports. `minAppVersion` can only add a refusal (the app is older than the stated minimum); it is never a reason to accept, and never replaces the schema check.
- **Verify at every startup, not only at download.** The stored downloaded dataset and its signature are checked against the pinned keys each time the app starts, before the dataset is used: the files in the app's storage can change after the download (a restored backup, another process, a damaged write). On any failure the app uses the bundled dataset, and it does not delete the downloaded files until the user is told.
- **No downgrade.** The app refuses a downloaded dataset whose `datasetVersion` is lower than the active one, and also lower than the bundled one, using the version inside the signed bytes and not the one in the manifest. "Restore the bundled dataset" is the only way back.
- **Versions are compared as numbers.** `datasetVersion` and `schemaVersion` are compared as semantic versions, component by component as integers (`1.10.0` is higher than `1.9.0`), never as text. The schema allows only `MAJOR.MINOR.PATCH` without pre-release or build parts, so there is no other rule to implement.
- **`date` is display only.** No decision depends on it.
- **Length before verification.** The app checks that the decoded signature is exactly 64 bytes before it calls the Dart verifier, which throws `StateError` on another length instead of returning false.
- **Every exception is a rejection.** Any error from decoding, hashing, parsing, validating or verifying means the release is not accepted and the active dataset stays.
- **No small-order keys.** The app refuses to pin, and refuses to verify with, a public key that is one of the eight points of small order (the fourteen encodings in `tests/test_signing.py`), as `zadrya_data.signing` does.
- **Same order, same strictness.** The four steps in the order above, the one spelling of the signature file, and strict JSON (no repeated keys, no `NaN`).

### Interoperability

Verified: the verify path accepts the RFC 8032 section 7.1 vectors 1, 2, 3 and SHA(abc) (key derivation, signing and verification are tested here), a signature whose S is not below the group order is rejected, and the security review of this slice confirmed interoperability with OpenSSL, Go and the Dart `cryptography` package 2.9.0.

Not verified yet, to be checked when the app implements the download:

- the platform-native path of `cryptography_flutter` (the review used the pure Dart implementation);
- the exact version of the Dart package that the app will pin;
- that Dart's base64 decoding is as strict as `decode_signature` (padding, alphabet, unused bits), or that the app adds the same re-encoding check;
- that the app's JSON reading is as strict as `strict_json` (repeated keys, numbers out of range, lone surrogates).

## Consequences

- The app must implement the section "What the app must do in either case". Its test vectors can be taken from `tests/test_signing.py`: the RFC 8032 vectors, a fixed signature file vector, the non-canonical S case and the small-order encodings (public material and published test seeds only).
- Points of small order are refused wherever a public key enters (`public_key_from_raw`, `load_public_keys` and `verify`). With the neutral point pinned, one fixed signature verifies for every message; the library underneath accepts such keys, so the check is ours. For honestly generated keys nothing changes.
- Tests create their own throwaway keys in memory. No private key is committed, not even a test key, and `tests/test_no_private_keys.py` fails when a file of the working tree or the staged content of the index contains the header of a PEM private key. It is a safety net: it does not see DER or re-encoded keys, ignored files or the history.
- The library never writes a key. The release workflow (a later slice) must put the `DATASET_SIGNING_KEY` secret into a file outside the checkout with mode 0600, point `ZADRYA_SIGNING_KEY_FILE` at that file (never at the key itself), and remove it afterwards.
- Every refusal derives from `zadrya_data.errors.ReleaseRejectedError`, so a command catches one class. Errors about the private key carry no key material, but a debugger or a memory dump of the signing process would: the signing job must not run with tracing or core dumps enabled.
- `load_public_keys` takes the directory as an argument and has no default: `keys/` is not part of the installed package, so the command line (a later slice) decides where it is.
- Ed25519 implementations differ on some malformed signatures. That matters only when the signer is hostile, which is not the threat here: the keys are the owner's. If the app's library and this one ever disagree on a signature made by the real key, it is a bug in one of them, and the fixed vectors are there to find it.
- There is no revocation. An exposed key stays usable against every app that still pins it until that app is updated (`keys/README.md`, "When a key is exposed").
- Until the owner provides the first public key, `keys/` holds only its README and every verification fails with `NoPinnedKeysError`. That is intended: nothing passes without a key.
