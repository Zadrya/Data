# CLAUDE.md

The Zadrya substance dataset and the Python pipeline that builds, validates and signs it. The specification is `Application/docs/SPEC.md`, section "Substance dataset".

## Commands

- `make setup`: install the git hooks (lefthook), once per clone.
- `make check`: lint, license metadata and tests. Run before every commit.
- `make ci`: everything CI runs, including authorship and commitlint. Run before opening a pull request.
- `uv run zadrya-data --help`: the pipeline command line. Python 3.12 and all dependencies are managed by `uv` (`uv sync`); never use a global `pip` or `python`.
- `uv run pytest tests/test_cli.py`: run one test file. `uv run black .` formats, `uv run mypy` type-checks (strict).

Local tools (Homebrew): `uv`, `lefthook actionlint yamllint markdownlint-cli2 zizmor reuse shellcheck`, plus Node for commitlint.

## Rules

- **Authorship.** Sklyvan is the only author and committer. Never add `Co-Authored-By`, `Claude-Session:` or "Generated with Claude Code" to commits, pull requests or code. The `commit-msg` hook and the `authorship` CI check reject them.
- **Small commits.** One logical change per commit, conventional commit messages, refactors separate from features.
- **Branches.** `feature/<description>` or `fix/<description>`, one pull request per slice (ideally under 400 lines of diff), rebase merge once CI is green and the `reviewer` agent approves. Never push to `main`.
- **Language.** Everything is in English. Use commas, colons or parentheses instead of the em dash (`make lint` fails on U+2014).
- **Secrets.** Only in environment variables or GitHub Secrets, never in the repository, the chat or logs.
- **Licenses.** Original code carries the SPDX header `GPL-3.0-or-later`. Files without a comment syntax are covered by `REUSE.toml`.
- **Signing key.** The private Ed25519 key is never generated, read or handled by Claude. The signing script reads its path from an environment variable, and CI uses the `DATASET_SIGNING_KEY` secret.
- **No release without review.** Every dataset change is opened as a pull request with a readable diff, and only Sklyvan approves a release.

## Gotchas

- Tests never touch the network and must keep coverage at 90 % or higher (`pyproject.toml`).
- `uv.lock` is committed and CI installs with `--locked`: after changing dependencies run `uv lock` and commit the lock file in the same commit.
- The schemas in `schema/` are the only copy: `src/zadrya_data/schemas/` holds symbolic links to them, which the build resolves into the wheel. A new schema file needs its link.
- Schema fixtures are generated: edit `tests/schema_cases.py`, run `uv run python -m tests.schema_cases` and commit the files. A mutation test (`tests/test_schema_mutations.py`, about 10 seconds) fails when removing one constraint of a schema changes no fixture result, so a new rule needs a fixture that breaks it. Python and Dart read regular expressions differently: end every pattern with `$(?![\s\S])` and avoid `\s` (`schema/README.md`).
- Data derived from PsychonautWiki is CC BY-SA 4.0 (text) and CC BY 4.0 (semantic data), while code is GPL-3.0-or-later. Keep `REUSE.toml` accurate when data files are added.
- Actions must be pinned by full commit SHA: the organization enforces it and unpinned workflows do not start.
- The shared scripts in `scripts/` and the base workflows are duplicated in all four Zadrya repositories on purpose, so that each repository can run `make ci` on its own. When you change one, change it in all four.
- The `authorship` and `commitlint` checks run the scripts from the pull request head, so a pull request that edits `scripts/check-*.sh`, the `Makefile` or those workflows validates itself: review such diffs with extra care.
- Tool versions are pinned in `scripts/install-ci-tools.sh` and the `Makefile`, and Dependabot does not track them: bump them by hand. The same goes for uv: its version and checksum in `.github/workflows/ci.yml` (twice) and the `uv_build` range in `pyproject.toml`.
- Dependency review (license allowlist in `.github/workflows/licenses.yml`) only runs in CI, so `make ci` cannot tell you that a new dependency has a license outside the list.
- Dependabot pull requests fail the `authorship` check by design: re-commit the bump as Sklyvan on a branch and close the Dependabot pull request (see `Application/docs/adr/0002-dependabot-and-authorship.md`).
- Before every push: `git log --format='%an <%ae>%n%B' origin/main..HEAD`.
