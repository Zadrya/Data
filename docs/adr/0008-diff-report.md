# 8. Dataset diff report

- Status: accepted
- Date: 2026-11-21

## Context

The spec asks that every dataset change produces a readable diff for human review, and the plan makes it a Markdown report posted on the pull request. The git diff of `dataset/substances.json` is complete but hard to read: a lowered interaction or a shorter duration is one line among thousands. The spec does not say how substances are matched, which changes a reviewer must never miss, what may be folded or left out of a long report, or how a report built from pull request data is posted. This ADR records those choices, taking the most conservative option for safety where the spec is silent.

## Decision

### Inputs

`zadrya-data diff <old> <new>` reads two documents as strict JSON (`strict_json.loads`) and refuses either one unless it is valid against the substances schema and has no repeated substance name, group id or category id (the diff matches by them). With `--old-format base`, `<old>` is `sources/base/Substances.json`, normalized alone (a snapshot with no API entry and a wiki page for every base name), so the first dataset pull request shows every change the API brought against the v11.11 base. The placeholder versions and attribution of the normalized base are never compared or shown. Exit codes: 0 written, 1 an input is not a valid dataset, 2 a file cannot be read or written, including an output path that is one of the inputs. Outputs are written through a temporary file made with `mkstemp` in the output directory and replaced in one step.

### Matching substances

Substances are matched by canonical name. A removed and an added substance are one renamed substance only when both have the same address (`url`) and the match is one to one. A name or alias match at another address is not a rename: the old substance stays removed, which is never left out, with a hint that names the possible new one. Only when either side has no address does a name or alias match (without case) count, and again only one to one. A renamed substance is compared with its old self, and its old name is replaced by the new one in interaction targets and group members before comparing, so a rename alone never shows as removed and added interactions. Every rename is listed in the warning.

### Interactions

Two catalog substances form one pair whichever of them lists the other, with the higher severity of both directions, as the app reads it (ADR 5). A group target or a target outside the catalog forms a pair with the substance that lists it. Groups are not expanded into substance pairs (ADR 5): a member removed from an interaction group lowers every pair it formed through that group, so it is a risk of its own.

### What a reviewer must never miss

Each such change carries a risk. A row with a risk is never left out by the cap, is shown first in its section in bold, and is counted by kind in a warning at the top of the report:

| Risk | Why |
| --- | --- |
| Interactions lowered, interactions removed | The app warns less, or not at all. |
| Members removed from interaction groups, groups removed | The pairs formed through the group are lowered or gone (ADR 5). |
| Substances removed, substances renamed | Logged ingestions and the interactions of the name change. |
| Routes removed | Every number of the route is gone. |
| Dose units changed | The numbers cannot be compared; the whole block is one row. |
| Risky dose changes | A higher `strongMin` or `heavyMin`, or a lost `commonMin`, `strongMin` or `heavyMin`: doses show in a lower class than before (ADR 4). |
| Risky duration changes | A lower or removed bound of `onset`, `comeup`, `peak`, `offset`, `total` or `afterglow`. A shorter timeline drops a substance from the interaction window sooner and lets the redose alert fire sooner (spec, "MVP functional scope": the interaction window of "Interactions" and the safe redose time alert of "Reminders and alerts"). |
| Tolerance values removed | A tolerance text or time that disappears. |
| Cross tolerances removed | A member removed from a cross tolerance group, or a group removed from a substance's `crossTolerances`. |

A higher `commonMin` shows light and common doses one class lower too, and is marked with a note, not a risk. Lower thresholds (`thresholdMin`, `lightMin`) are not marked. Longer durations, added values, bioavailability and changed texts carry no risk.

### Layout

The report has a head and a body. The head holds the labels, the files the change touches outside `dataset/`, the warning and the summary. The body holds the sections: substances (removed, renamed, added), numbers, interactions (lowered and removed first), groups and cross tolerance, and categories and texts. In each section the rows with a risk come first, then the other changes, then the additions. In the numbers and texts sections, which are long on real data, alike rows (same field, same kind of change, such as "dose lightMin added" on 363 routes) are folded into one collapsed `<details>` block each. Categories and texts are reported only as changed, added or removed, never quoted. Each section shows at most `--max-rows` other rows (default 100) and says how many it left out; the workflow passes a large value and relies on the size fallback below.

### Output

The report is deterministic: everything is sorted (substances by code point, routes in schema order), nothing depends on hash order, and floats are written in their shortest exact form. Text from the data is escaped so that Markdown shows it as written: ASCII punctuation with a meaning in Markdown, GitHub tables, math or emoji codes gets a backslash; a zero width space (`&#8203;`) follows `@` and `#` and goes inside `://`, `www.`, `GH-` and after every six characters of a run of seven or more hexadecimal digits, so that data never mentions a user or links an issue, an address or a commit; line breaks and characters that are not printable become spaces; and an em dash in the data is written as its character reference, so the raw report never contains one.

### Posting on pull requests

`.github/workflows/dataset-diff.yml` runs on `pull_request` (never `pull_request_target`) when `dataset/substances.json` changes. Top-level permissions are empty.

- The `report` job has `contents: read` only. It checks out the merge commit without credentials, takes the old dataset from its first parent, the base branch (`git show`), or the base file with `--old-format base` when the base branch has no dataset yet, and lists the paths outside `dataset/` that the pull request changes (`git diff --name-only HEAD^1 HEAD`). It writes the report to the job summary (only the head when the report is over 1 MiB, the limit of a summary), uploads the full report as the artifact `dataset-diff-report`, and hands the comment body to the next job as a job output.
- The comment body names the head commit. It holds the whole report when it fits in a comment, and otherwise always the head (warning and summary) followed by a pointer to the job summary and the artifact.
- The `comment` job has only `pull-requests: write`, no checkout and no code from the pull request. It creates or updates one comment, found by a hidden marker in its first line and written by `github-actions[bot]`. It also runs when the report job failed or was cancelled, and then replaces the comment with "report failed" and the head commit, so an older report is never left looking current.
- A pull request from a fork gets a read-only token, so the `comment` job is skipped and the job summary is the report.
- Every value reaches a script through `env`, actions are pinned by SHA, the uv cache is off, and there are no secrets.

## Consequences

- The first dataset pull request is reviewed against the normalized base file, and later ones against the dataset on the base branch.
- On `pull_request`, the workflow and the code that build the report come from the pull request itself. A pull request that changes them can change what the report says. The report therefore lists every changed path outside `dataset/` at its top, and a dataset pull request should change nothing else; any other path means the report must be checked against the git diff.
- The pair rule hides a one-sided change that the app ignores (one direction lowered while the other still holds the higher severity). The git diff still shows it.
- A wiki page that moves changes the address, so a substance renamed that way shows as removed and added with a hint, never as a quiet rename.
