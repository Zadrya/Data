# 6. Release of the dataset

- Status: accepted, except "Release-please" below, which is pending the owner's decision.
- Date: 2026-11-17

## Context

The spec (`Application/docs/SPEC.md`) says that a release of `Data` is manual, needs the approval of the `release` environment, and consists of an Ed25519 signature, `manifest.json`, a GitHub Release and the verification of the published signature. It also says that release-please in `Data` produces "the semantic version, `CHANGELOG.md` and the tag from conventional commits". The library parts (signing, manifest, acceptance check) are in `docs/adr/0003-dataset-signature.md`. This ADR records what the spec leaves open: which version is which, the tag, which bytes are signed, how the key is handled in CI, the network use of the verification, and how release-please fits the single-author rule.

## Decision

### Two versions that are never confused

| Version | Where it lives | What changes it | Tag |
| --- | --- | --- | --- |
| Dataset (`datasetVersion`) | Inside the signed `substances.json`, repeated in `manifest.json` | The dataset pull request that the owner reviews | `dataset-vX.Y.Z` |
| Schema (`schemaVersion`) | Inside the signed `substances.json` and in `schema/` | A schema change, by its own rules (`schema/README.md`) | None: it is part of the dataset |
| Pipeline (`version` in `pyproject.toml`) | The Python package, shown by `zadrya-data --version` | Pipeline code; never published as a package | See "Release-please" |

- A dataset release is tagged `dataset-v` followed by the `datasetVersion` inside its signed bytes, and by nothing else. The prefix keeps it apart from the app's tags (`vX.Y.Z` in `Application`) and from any tag of the pipeline. `verify --release` rejects a release whose tag and signed version differ, so a release cannot be published or found under another number.
- The dataset version is chosen in the dataset pull request, where it is part of the reviewed bytes. The release workflow takes it as an input only to check it: if the input and the committed document disagree, nothing is signed.
- Dataset releases are the only GitHub Releases marked "latest", so `releases/latest` always leads to a dataset.

### Which bytes are signed

The release signs `dataset/substances.json` exactly as committed on `main`, at the commit the workflow runs on. It never rebuilds the dataset and never touches the network before signing: the build (`fetch`, normalization, diff) happens on a branch, the owner reviews the diff in a pull request, and the merge is what makes the bytes releasable. Rebuilding during the release would sign bytes that nobody reviewed, and would depend on the PsychonautWiki API being up and unchanged.

### Commands

`manifest`, `sign` and `verify` call `zadrya_data.manifest`, `zadrya_data.signing` and `zadrya_data.release_check` and reimplement nothing.

- `manifest` has no default date: the date is an argument, so the same inputs always give the same bytes and the manifest can be rebuilt and compared in a later job.
- `sign` refuses a dataset that is not valid against the schema or (with `--dataset-version`) states another version, reads the pinned keys before it reads the private key, and writes the signature only after a pinned key verifies it. Signing with the wrong key therefore fails before anything is written.
- `verify` runs `verify_release` and prints the pinned key that matched, both versions, the hash and the unsigned `minAppVersion`. It catches `ReleaseRejectedError` and unreadable files only: any other exception is a bug and surfaces as one.

### Network: a second, narrow path

`verify --release` is the second code path that uses the network, after `fetch`. It goes through `PoliteClient` (no proxy or certificate variables, size cap, deadline, retries, generic User-Agent) and reads only public data:

1. With `latest`, one request to `https://github.com/Zadrya/Data/releases/latest`, which is not followed: its redirect must point to `https://github.com/Zadrya/Data/releases/tag/dataset-vX.Y.Z`, and that tag is then used for all three files, so they come from the same release.
2. One request per asset to `https://github.com/Zadrya/Data/releases/download/<tag>/<name>`. GitHub answers with a redirect to its asset storage. Exactly one redirect is followed, only over HTTPS on the default port without a user name, and only to `release-assets.githubusercontent.com` (what GitHub uses today, checked on 2026-11-17) or `objects.githubusercontent.com` (what it used before). Any other target is an error. The target address is never printed, because it carries a temporary token.

No other host is contacted. The tag is checked against `dataset-vMAJOR.MINOR.PATCH` before any address is built from it.

### Release workflow

`.github/workflows/release.yml` runs only on `workflow_dispatch` from `main`, with the dataset version, the minimum app version and the date as inputs. Its jobs, in order:

1. **check** (no secret): checks the inputs, that the tag does not exist yet, that the version is higher than the latest dataset release, and builds the manifest of the committed dataset with `--dataset-version`, which validates the schema and the version. It fails before anyone is asked to approve.
2. **sign** (environment `release`, so it waits for the owner's approval): the only job that can read `DATASET_SIGNING_KEY`. The secret goes from the secrets context into the environment of the one step that writes it, with `printf` (a shell builtin, so it never appears in a process command line), to a file with mode 0600 in `$RUNNER_TEMP`. `ZADRYA_SIGNING_KEY_FILE` points at that file for the signing step only, core dumps are off in that step, and an `always()` step deletes the file. The job uses no cache of any kind and only `contents: read`. Its one output is the 89-byte signature file, which is public.
3. **publish** (`contents: write`, no access to the secret): rebuilds the manifest from the same commit and inputs, writes the signature, runs `zadrya-data verify` on the three files, and only then creates the tag and the GitHub Release with `gh release create` and the job's `GITHUB_TOKEN`. No third-party release action is used.
4. **verify-published** (`contents: read`, no secret): downloads the published assets with `zadrya-data verify --release dataset-vX.Y.Z` and `--release latest` against the pinned keys of the same commit.

Every action is pinned by commit, every job has `timeout-minutes`, and `concurrency` has one group for all releases and never cancels a running one, so two releases cannot interleave.

### Release-please: pending owner decision

**Recommendation: do not use release-please in `Data`.** It is not implemented; the owner decides, and if the recommendation is accepted the spec line about release-please in `Data` needs a change through a pull request in `Application`.

The reasons:

1. **Authorship.** Release-please opens its release pull request as `github-actions[bot]`, with commits by the bot. Like Dependabot (`Application/docs/adr/0002-dependabot-and-authorship.md`), it fails the `authorship` check by design. Re-committing it as Sklyvan on another branch does not work as it does for Dependabot: release-please creates the tag and the release only for its own merged pull request (it looks for its `autorelease: pending` label), so a re-committed copy is never released. The remaining option is to amend the bot's branch as Sklyvan and merge the bot's pull request, which still leaves a pull request that Sklyvan did not open, and release-please may force-push that branch again.
2. **Repository settings.** Release-please needs `contents: write` and `pull-requests: write`, and the setting "Allow GitHub Actions to create and approve pull requests". Pull requests opened with `GITHUB_TOKEN` do not start workflows, so its pull requests never get the required checks unless someone pushes to them.
3. **"latest".** Its GitHub Releases of the pipeline would compete with dataset releases for "latest", and `releases/latest` is what `verify --release latest` (and later the app's update check) reads.
4. **Nothing to version.** The pipeline package is not published anywhere; the version users and the app see is the dataset version, and that is chosen in the reviewed dataset pull request, not derived from commit messages.

What would replace it: the dataset version comes from the dataset pull request (as above); the release notes are written by the release workflow from the verified files (versions, hash, key, link to the commit); the pipeline version in `pyproject.toml` is bumped by hand in a `chore` commit when there is a reason. If a `CHANGELOG.md` is wanted, it can be generated locally from conventional commits and committed by Sklyvan.

If the owner prefers to keep release-please, the least bad form is: tags `pipeline-vX.Y.Z` (never `vX.Y.Z` or `dataset-v`), its releases created with "latest" turned off, and its pull requests amended as Sklyvan on the bot's own branch before merging, as an exception to the single-author rule for pull requests recorded in this ADR.

## Consequences

- Before the first release the owner must: create the `release` environment with himself as required reviewer and deployments limited to `main`; add `DATASET_SIGNING_KEY` as a secret of that environment (not of the repository, so that only the `sign` job can read it); and add the public key to `keys/` through a pull request. The `release-dataset` skill lists the steps.
- Until a key is in `keys/`, `sign` and every `verify` fail with "no pinned public keys", on purpose.
- The release tag points at the commit on `main` the workflow ran on, which holds the reviewed dataset and the keys that verified it.
- A published release can be checked by anyone at any time with `zadrya-data verify --release <tag>`.
- Nothing can stop someone with write access to the repository from creating a release by hand. The app does not trust a release because of where it is, only because of its signature, so such a release is rejected unless it was signed with a pinned key.
