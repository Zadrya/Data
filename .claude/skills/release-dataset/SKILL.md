---
name: release-dataset
description: Procedure for publishing a signed release of the Zadrya substance dataset (dataset-vX.Y.Z) from Zadrya/Data, and for verifying a published one. Use when the owner wants to release a merged dataset, asks whether a release is valid, or a release run failed.
---

# Release the dataset

The design is in `docs/adr/0006-release.md` (versions, tags, workflow) and `docs/adr/0003-dataset-signature.md` (signature, checks). Read both first.

## Who does what

- **Owner (Sklyvan) only:** holds the private key, sets up the `release` environment and its secret, merges the dataset pull request, starts the release workflow and approves its `sign` job.
- **You:** prepare and check, never sign. You never generate, read, print, copy or handle the private key, its password or the `DATASET_SIGNING_KEY` secret, and you never start the release workflow (`gh workflow run release.yml`) yourself. Give the owner the exact command instead.

## One-time setup (owner, before the first release)

1. Generate the key pair as `keys/README.md` says, on the owner's machine, and send only the public key. You add it as `keys/<name>.pem` in a pull request and print the raw form the app pins (`keys/README.md`, "The form the app pins").
2. Repository settings, Environments, New environment `release`: required reviewer Sklyvan, "Prevent self-review" off (he is the only reviewer), deployment branches limited to `main`.
3. In that environment (not in the repository secrets, so only the `sign` job can read it), set the secret `DATASET_SIGNING_KEY` to the unencrypted PEM of the private key, straight from a pipe so that no plaintext copy is ever written to disk or the clipboard:

   ```sh
   "$(brew --prefix openssl@3)/bin/openssl" pkey -in <encrypted.pem> \
     | gh secret set DATASET_SIGNING_KEY --env release --repo Zadrya/Data
   ```

   `openssl` asks for the key password once; `gh secret set` reads the value from standard input and needs a `gh` login with admin rights on the repository. Use OpenSSL 3 from Homebrew: the LibreSSL that macOS ships cannot read Ed25519 keys (`keys/README.md`). The workflow never sees a password.
4. Optional, recommended: turn on "Immutable releases" in the repository settings, so a published release cannot be edited.

## Each release

1. **The dataset is on `main`.** A pull request changed `dataset/substances.json`, including its `datasetVersion`, its diff was reviewed and the owner merged it. A release never rebuilds or edits the dataset.
2. **Choose the inputs.**
   - `dataset_version`: exactly the `datasetVersion` in the committed file, higher than every earlier `dataset-v*` release.
   - `min_app_version`: the lowest app version that can read this dataset (normally the one that first supports its `schemaVersion` major).
   - `date`: the release date, `YYYY-MM-DD`.
   - `dataset_pr`: the number of the merged dataset pull request. `check` refuses one that is not merged into the commit being released, and the release notes link it and its diff report as the changelog.
3. **Check locally** on an up-to-date `main` (no key needed):

   ```sh
   git switch main && git pull --ff-only
   uv run zadrya-data validate dataset/substances.json
   uv run zadrya-data manifest dataset/substances.json --dataset-version X.Y.Z \
     --min-app-version A.B.C --date YYYY-MM-DD --output "$(mktemp -d)/manifest.json"
   ```

4. **The owner starts the workflow** (Actions, Release, Run workflow on `main`, or):

   ```sh
   gh workflow run release.yml --repo Zadrya/Data --ref main \
     -f dataset_version=X.Y.Z -f min_app_version=A.B.C -f date=YYYY-MM-DD -f dataset_pr=N
   ```

5. **`check` runs** without the key: inputs, merged dataset pull request, new tag, higher version, schema and `datasetVersion` of the committed file. If it fails, nothing was signed: fix the cause and start again.
6. **The owner reads the `check` summary before approving** (the run page, below the jobs). It shows the commit, the SHA-256 and `datasetVersion` of `dataset/substances.json`, and the `git diff --stat` of `.github/workflows`, `keys`, `src`, `uv.lock` and `pyproject.toml` since the previous `dataset-v` tag ("first release" when there is none).
   - The SHA-256 must equal the hash of the dataset in the reviewed pull request: `git show <last commit of the pull request>:dataset/substances.json | shasum -a 256`.
   - Every file in the diff must be a change the owner reviewed and merged. An unexpected change to a workflow, a key or the signing code is a reason to reject.
7. **The owner approves** the pending deployment to `release` ("Review deployments"), or rejects it if anything above does not match. Only after approval does `sign` read the key, sign, verify the signature against `keys/` and delete the key file.
8. **`publish`** rebuilds the manifest, verifies the three files, creates the tag `dataset-vX.Y.Z` on the workflow's commit and the GitHub Release marked latest. **`verify-published`** downloads the assets and runs `zadrya-data verify --release dataset-vX.Y.Z` and `--release latest`.
9. **Verify independently** from a clean clone of `main`:

   ```sh
   uv run zadrya-data verify --release dataset-vX.Y.Z --dataset-version X.Y.Z
   uv run zadrya-data verify --release latest
   ```

   Report the printed key name, versions and SHA-256 to the owner.

## Signing locally instead (owner only)

If the owner prefers not to keep the key in GitHub, he runs on his own machine, from a clean `main`, with the encrypted key file (mode 0600, outside every repository). The password is typed without echo into the variable and removed right after signing; it never appears on a command line or in the shell history:

```sh
mkdir dist && cp dataset/substances.json dist/
read -rs ZADRYA_SIGNING_KEY_PASSWORD && export ZADRYA_SIGNING_KEY_PASSWORD
ZADRYA_SIGNING_KEY_FILE=<encrypted.pem> \
  uv run zadrya-data sign dist/substances.json --dataset-version X.Y.Z --output dist/substances.json.sig
unset ZADRYA_SIGNING_KEY_PASSWORD
uv run zadrya-data manifest dist/substances.json --dataset-version X.Y.Z \
  --min-app-version A.B.C --date YYYY-MM-DD --output dist/manifest.json
uv run zadrya-data verify dist --dataset-version X.Y.Z
gh release create dataset-vX.Y.Z dist/substances.json dist/substances.json.sig dist/manifest.json \
  --repo Zadrya/Data --target "$(git rev-parse HEAD)" --title "Dataset X.Y.Z" --latest
uv run zadrya-data verify --release dataset-vX.Y.Z --dataset-version X.Y.Z
```

## When something fails

- **`sign` says the signature does not verify with any pinned key:** the secret holds another key than the one in `keys/`. Nothing was written. The owner replaces the secret; never change `keys/` to make a release pass.
- **`sign` says the key file is not a PEM key:** the secret is incomplete or holds extra text. The owner sets it again with the pipe above.
- **`publish` or `verify-published` fails after the release exists:** stop and tell the owner. Do not delete or move tags or releases, and do not upload replacement assets: a published release is never changed. The fix is a new version.
- **Never re-run the `sign` job with debug logging enabled**, and never add steps that print the environment, `set -x` or upload `$RUNNER_TEMP` in the job that holds the key.

## Never

- Sign anything but the committed `dataset/substances.json` of `main`, or rebuild it during a release.
- Put the private key, or anything derived from it, in a file of a repository, a variable other than the one workflow step, a command line, a chat, an issue, a pull request or a log. If that happens, treat the key as exposed and follow `keys/README.md`, "When a key is exposed".
- Tag a dataset `vX.Y.Z`, or with a version other than its signed `datasetVersion`.
