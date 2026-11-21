# 7. Dataset invariants and the build command

- Status: proposed
- Date: 2026-11-20

## Context

The schema checks shape only (ADR 1, "What the schema does not check"): increasing dose boundaries, minimum not above maximum, references that exist, symmetric interactions, unique names, aliases and list items are left to the pipeline. Normalization already produces data that keeps most of these rules (ADR 4 and 5), but it is the code under test. The signed bytes need a check that does not depend on it.

## Decision

### Invariants (`src/zadrya_data/invariants.py`)

The invariants are a second, independent check over the finished document. They import nothing from `normalize` and read only the document, so a bug in a normalization rule cannot also hide itself here. They assume a document the schema accepts: the build validates the schema first.

Names are compared by one **name key**, the rule of ADR 4: format characters (Unicode category Cf) removed, NFKC and case folding, runs of whitespace collapsed. The invariants have their own copy of it, so that they stay independent of normalization, and a test keeps the two copies in agreement. Each rule yields every place it is broken, with the substance (or `(catalog)` for the top-level lists) and the field, and `require` raises `InvariantError` with all of them, sorted, never only the first.

| Rule | What must hold |
| --- | --- |
| `dose-order` | The dose boundaries present in a route never decrease, in the order `thresholdMin`, `lightMin`, `commonMin`, `strongMin`, `heavyMin`. Equal neighbours are allowed (below). |
| `range` | `min` is not above `max` in every duration phase, every bioavailability and the tolerance times `half` and `zero`. |
| `target-exists` | A `substance` target is another substance of the catalog, never the substance itself. |
| `target-unique` | A target appears once across the three severities of a substance (`other` targets compared by the name key). |
| `interaction-symmetric` | When A lists the substance B, B lists A with the same severity. |
| `group-exists` | A `group` target is the id of an entry of `interactionGroups`. |
| `member-exists` | Every member of every interaction and cross tolerance group is a substance of the catalog. |
| `cross-tolerance` | A substance lists exactly the cross tolerance groups it is a member of, and each exists. |
| `category-exists` | A substance's categories are ids of `categories`. |
| `unique-id` | Ids are unique within `categories`, `interactionGroups` and `crossToleranceGroups`. |
| `unique-name` | Canonical names are unique, compared by the name key. |
| `unique-alias` | An alias leads to exactly one substance, compared by the name key: it is not the substance's own name, not another substance's name, not carried by another substance and not repeated. |
| `alias-not-group` | No alias is the name or the id of an interaction or cross tolerance group. |
| `name-not-group` | No substance name is the name or the id of an interaction or cross tolerance group. |
| `other-outside-catalog` | An `other` target is really outside the catalog: it is not a substance name, not an alias and not the name or id of an interaction or cross tolerance group. Otherwise a warning about a catalog substance or group would show only as text and never match an ingestion. |
| `unique-items` | No list holds an item twice: routes, categories, both class lists, cross tolerances, toxicities, safer use items and group members. |
| `mass-unit` | A dose unit never holds the Greek letter mu (U+03BC), and a unit that spells a mass another way (`MG`, `mcg`, `ug`, `grams`, full-width `ｍｇ`, compared by the name key) is refused: the only mass spellings are `µg` (micro sign U+00B5), `mg` and `g`. Every other unit (`mL`, `mg THC`, `seeds`, `Mg#`) stays opaque. |
| `finite` | No number anywhere is NaN or infinite. |

**Equal dose boundaries are allowed.** ADR 4 accepts equal neighbours and reports each one (`dose-equal-boundaries`, 100 in the snapshot of 2026-11-16: 98 a threshold equal to the light minimum, plus 4-MeO-PCP insufflated with `strongMin` and `heavyMin` both 150 and Theacrine insufflated with `thresholdMin` and `commonMin` both 25). The invariant enforces exactly that: boundaries never decrease. Equal boundaries are safe because the classification of ADR 1 takes each boundary as the start of its class, up to but not including the next one: between two equal boundaries the lower class is empty, and a dose at that value takes the higher class. A user who logs 150 mg of 4-MeO-PCP sees it as heavy, never as strong. A strict rule would have refused these real routes, or forced normalization to drop a boundary the wiki states.

**Mutation check.** `tests/test_invariants.py` has one failing case per rule, each a single change to a valid document, and shows that removing a rule from the checker lets its case pass: no rule is covered by another by accident. Edge cases that must stay valid (equal dose neighbours, `min` equal to `max`, one-sided ranges, opaque units) are pinned too. The real base file, normalized with each recorded API answer, keeps every invariant.

### The build (`zadrya-data build`, `src/zadrya_data/build.py`)

`zadrya-data build --dataset-version X.Y.Z` reads the base file (`--base`, default `sources/base/Substances.json`) and a snapshot directory (`--snapshot`, default `sources/api`) through `load_snapshot`, which checks the SHA-256 of each file against `snapshot.json`. It normalizes, adds `schemaVersion`, `datasetVersion` and `attribution`, validates the schema, then the invariants, and writes `--output` (default `dataset/substances.json`). It never uses the network.

- **No default version.** `--dataset-version` is required: a version is a decision of the dataset pull request, not of the code.
- **Deterministic bytes.** The text is that of `snapshot.dump_json`, the one form the pipeline writes: sorted keys, two-space indent, UTF-8 without escapes, `allow_nan=False`, line feeds and one final newline. List order is the documented order of normalization (ADR 4 and 5); nothing depends on set or dict iteration of unordered data. There is no date, path, host or hash seed in the file (the date belongs to the manifest, ADR 1). A test runs the command twice in separate processes with different `PYTHONHASHSEED` values and compares the bytes of the dataset and of the report.
- **The bytes on disk are checked, and nothing is half written.** As ADR 1 asks, every output (the dataset and, with `--report`, the report) is first written to a new hidden file in its target's directory, created by `tempfile.mkstemp` (a fresh name opened with `O_EXCL`, so an existing file or symbolic link is never followed or reused), flushed to disk with `fsync`, read back through the same descriptor and compared with the bytes meant. The dataset's read-back bytes are parsed with `strict_json` and checked against the schema and the invariants. Only when every output has passed are they renamed over their targets, report first and dataset last, and each directory is flushed after its rename. On any failure before the renames, the hidden files and any directory created for them are removed and no target changes. A failure between the two renames would need the directory to change under the command; it could leave a new report next to the previous dataset, never the reverse. A symbolic link at a target is replaced by the new file, and the file it pointed to is not touched. File modes follow the umask.
- **Refusals.** Exit code 0 when written; 1 when the dataset is refused (normalization stops, the schema or an invariant fails, or an output would overwrite the base file, land inside the snapshot directory or coincide with the other output), with every failure printed; 2 when an input cannot be read or is not a valid base file or snapshot (a wrong hash included), or an output cannot be written. Nothing is written on 1 or 2, so the codes match the release commands.
- **Report.** `--report PATH` writes the normalization report as tab-separated text: a header, then one finding per line (`kind`, `substance`, `route`, `detail`), with backslash, tab and line breaks escaped. One line per finding gives the dataset pull request a readable diff of the report too. It is staged and renamed together with the dataset, as above.
- **Attribution.** Three entries, from `DATA_LICENSES.md`: PsychonautWiki contributors for the text (`CC-BY-SA-4.0`) and for the semantic data (`CC-BY-4.0`), both pointing to the wiki's Copyrights page, and PsychonautWiki Journal v11.11 by Isaak Hanimann (`GPL-3.0-or-later`), the base file. **Proposed: the owner confirms the wording when deciding the license of the derived dataset**, which is still open (`DATA_LICENSES.md`, "Open questions"). The attribution sits inside the signed bytes and the manifest repeats it, so a change is a new dataset version.

No dataset is committed with this change: the first `dataset/substances.json` lands in its own pull request, after the owner's license decision.

## Consequences

- A collision of names or aliases that normalization lets through stops the build instead of reaching the app.
- A rule here can repeat a rule of normalization. That is the point: the two are written separately, so a mistake has to be made twice to ship.
- A new cross-field rule needs a failing case and passes the mutation check, as the schema fixtures do.
- Building with the defaults writes `dataset/substances.json` in the working tree. It must not be committed before the owner's license decision; the release workflow only ever signs the committed file (ADR 6).
