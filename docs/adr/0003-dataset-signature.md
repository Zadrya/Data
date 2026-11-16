# 3. Dataset signature

- Status: accepted, with one open recommendation for the owner (see "Recommendation: sign the manifest too")
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

`verify` takes the pinned keys and returns the one that verified, so a release log can say which key signed. It fails with a specific exception when there is no key (`NoPinnedKeysError`), when there are more than two (`TooManyPinnedKeysError`: the spec pins two, and a longer list is a rotation that was never finished), when the signature is not 64 bytes, and when no key verifies. A tampered file, a tampered signature and a key that is not pinned are deliberately the same error: the verifier cannot tell them apart.

### Key formats

- **Private key**: a PEM file (PKCS#8), Ed25519 only, either unencrypted or encrypted with a password. The file is named by the environment variable `ZADRYA_SIGNING_KEY_FILE`; the password, when there is one, is in `ZADRYA_SIGNING_KEY_PASSWORD` (empty counts as unset). A password for an unencrypted key is an error, so a mistake is noticed. The module only reads the key. Its error messages name the file and the reason, never the content, and the exceptions of the parser are not chained, so a traceback cannot show more.
- **Public keys**: one `*.pem` file per key in `keys/` (SubjectPublicKeyInfo), read in the order of the file names, at most two. A file must be exactly the canonical PEM of an Ed25519 public key: comments, blank lines, carriage returns, a second key, another key type, a private key and the same key under two names are rejected. An empty `keys/` means "no pinned keys" and every verification fails.
- **In the app**: the raw 32 bytes of each key (RFC 8032 encoding), which `PinnedKey.raw` and `PinnedKey.base64` give.

### Rotation

A release is accepted when any one pinned key verifies, so keys are rotated without a gap: add the new public key, ship an app that pins both, start signing with the new key, later remove the old one. The steps, and what to do when a key is lost or exposed, are in `keys/README.md`. There is no revocation list: a key stops being trusted when an app version no longer pins it.

### Why the manifest is not signed separately, and what that leaves open

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

Two limits do not depend on the manifest at all, and the app must handle them:

- **Replay.** An old release, complete and correctly signed, verifies forever. The app must refuse a downloaded `datasetVersion` lower than the active one (the version is inside the signed bytes), and treat "restore the bundled dataset" as the only way back.
- **Freeze.** Nobody can prove that a newer release exists. Withholding updates cannot be detected without an expiry date, which the spec does not have.

### Recommendation: sign the manifest too

The design above is acceptable to ship, on two conditions for the app: it treats `minAppVersion` and `date` as unauthenticated hints (the signed `schemaVersion` is the compatibility gate, never `minAppVersion` alone), and it refuses downgrades.

The recommendation is still to **sign the manifest as well before the first signed release**, as a fourth asset `manifest.json.sig` in the same format and with the same keys. Reasons: `minAppVersion` is the one field the owner would use to keep old apps away from a dataset in an emergency, and it should not be the one field anyone can edit; the cost is one more call to `sign` in the release and one more call to `verify` in the app; and the formats are frozen at the first signed release, so adding it later needs a transition. The alternative of moving `minAppVersion` into `substances.json` was considered and is weaker: it changes the schema and ties a release decision to the dataset content.

It is not done in this slice because the spec lists exactly three release assets, and changing that is the owner's decision. If it is taken, one rule comes with it: the two signatures use the same key over different kinds of file, so each file must keep failing the schema of the other (true today, since both schemas reject unknown keys and require their own), which makes a signature of one useless as a signature of the other.

## Consequences

- The app must implement the same four steps in the same order, the same strict signature file format, the downgrade rule and the two conditions above. Its test vectors can be taken from `tests/test_signing.py` (RFC 8032 vector and a fixed signature file vector, public material only).
- Tests create their own throwaway keys in memory. No private key is committed, not even a test key, and `tests/test_no_private_keys.py` fails when any file of the repository contains the header of a PEM private key.
- The library never writes a key. The release workflow (a later slice) must put the `DATASET_SIGNING_KEY` secret into a file outside the checkout, readable by its user only, point `ZADRYA_SIGNING_KEY_FILE` at it, and remove it afterwards.
- `load_public_keys` takes the directory as an argument and has no default: `keys/` is not part of the installed package, so the command line (a later slice) decides where it is.
- Ed25519 implementations differ on some malformed signatures and on public keys of small order. That matters only when the signer is hostile, which is not the threat here: the keys are the owner's. If the app's library and this one ever disagree on a signature made by the real key, it is a bug in one of them, and the fixed vectors are there to find it.
- Until the owner provides the first public key, `keys/` holds only its README and every verification fails with `NoPinnedKeysError`. That is intended: nothing passes without a key.
