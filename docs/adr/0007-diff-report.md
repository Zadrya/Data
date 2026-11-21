# 7. Dataset diff report

- Status: accepted
- Date: 2026-11-21

## Context

The spec asks that every dataset change produces a readable diff for human review, and the plan makes it a Markdown report posted on the pull request. The git diff of `dataset/substances.json` is complete but hard to read: a lowered interaction or a risky dose change is one line among thousands. The spec does not say how substances are matched, what counts as an interaction change, what may be left out of a long report, or how a report built from untrusted pull request data is posted. This ADR records those choices, taking the most conservative option for safety where the spec is silent.

## Decision

### Inputs

`zadrya-data diff <old> <new>` reads two documents as strict JSON (`strict_json.loads`) and refuses either one unless it is valid against the substances schema and has no repeated substance name, group id or category id (the diff matches by them; the invariants check the rest). With `--old-format base`, `<old>` is `sources/base/Substances.json`, normalized alone (a snapshot with no API entry and a wiki page for every base name), so the first dataset pull request shows every change the API brought against the v11.11 base. The placeholder versions and attribution of the normalized base are never compared or shown. Exit codes: 0 written, 1 an input is not a valid dataset, 2 a file cannot be read or written.

### Matching substances

Substances are matched by canonical name. A removed and an added substance form a rename when their names are equal but for case, or one name is an alias of the other substance (without case), and only when the match is one to one: an ambiguous candidate stays added and removed, which is the conservative reading. A renamed substance is compared with its old self, and its old name is replaced by the new one in interaction targets and group members before comparing, so a rename alone never shows as removed and added interactions.

### Interactions

Two catalog substances form one pair whichever of them lists the other, with the higher severity of both directions, as the app reads it (ADR 5). A group target or a target outside the catalog forms a pair with the substance that lists it. Groups are not expanded into substance pairs (ADR 5): a change of group members is in the group section, so the two sections together miss no change of what the app warns about. Each pair is added, removed, raised or lowered. Lowered and removed pairs come first, are marked in bold, and a warning at the top of the report counts them.

### Numbers and texts

Per substance and route: dose units, each dose boundary, each bound of the six duration phases and of the bioavailability, and a route that appears or disappears, each with old and new value and a direction. As in ADR 4, a higher `strongMin` or `heavyMin` is marked risky, and so is a lost `commonMin`, `strongMin` or `heavyMin`; when the units differ the numbers are listed as not comparable. Tolerance texts and times are compared field by field. Categories, aliases, classes, the address and the free texts are reported only as changed, added or removed: a report that quotes them would be long and would repeat text the git diff already shows.

### What is never left out

Each section shows at most `--max-rows` rows (default 100) and states how many it left out. Rows a reviewer must never miss are always shown and do not count against the cap: removed substances, lowered and removed interactions, members removed from an interaction group, a removed group, a removed route, changed units and the risky dose changes.

### Output

The report is deterministic: everything is sorted (substances by code point, routes in schema order), nothing depends on hash order, and floats are written in their shortest exact form. Data is escaped so Markdown shows it as written: ASCII punctuation with a meaning in Markdown, GitHub tables or math gets a backslash; `@` and `#` are followed by a zero width space (`&#8203;`) so that a name never mentions a user or links an issue; line breaks and control characters become spaces; and an em dash in the data is written as `&#8212;`, so the raw report never contains one.

### Posting on pull requests

`.github/workflows/dataset-diff.yml` runs on `pull_request` (never `pull_request_target`) when `dataset/substances.json` changes. A `report` job with `contents: read` only checks out the merge commit without credentials, takes the old dataset from its first parent, the base branch (`git show`), or the base file with `--old-format base` when the base branch has no dataset yet, runs the diff and writes it to the job summary. It hands the comment body to the next job as a job output, so no artifact action is needed. A separate `comment` job with only `pull-requests: write`, no checkout and no code from the pull request creates or updates one comment with the preinstalled `gh`, found by a hidden marker in its first line and written by `github-actions[bot]`. Every value reaches a script through `env`. A pull request from a fork gets a read-only token, so the `comment` job is skipped and the job summary is the report. A report longer than a comment allows is replaced by a short comment that points to the job summary. Actions are pinned by SHA, the uv cache is off, and there are no secrets.

## Consequences

- The first dataset pull request is reviewed against the normalized base file, and later ones against the dataset on the base branch.
- The pair rule can hide a one-sided change that the app ignores (one direction lowered while the other still holds the higher severity). The git diff still shows it.
- The report trusts the schema and the uniqueness check, not the invariants: it can describe a dataset that the invariants would reject, which the build refuses anyway.
