# Dataset schema

JSON Schema (Draft 2020-12) for the two documents of a dataset release:

- [`substances.schema.json`](substances.schema.json): the substance catalog, `substances.json`.
- [`manifest.schema.json`](manifest.schema.json): the release manifest, `manifest.json`.

Current version: **1.0.0**. Both files share one version, stated in their `$comment` and in `SCHEMA_VERSION` (`src/zadrya_data/schema.py`). Every dataset carries the version it follows in `schemaVersion`.

The schemas check shape only. Invariants across fields (increasing dose ranges, minimum not above maximum, references that exist, symmetric interactions, unique names) are checked by the pipeline, not by JSON Schema. The design decisions are recorded in [`docs/adr/0001-dataset-schema.md`](../docs/adr/0001-dataset-schema.md).

## Checking a document

```sh
uv run zadrya-data validate dataset/substances.json
uv run zadrya-data validate --schema manifest manifest.json
```

Exit code 0 means valid, 1 means schema violations (each printed with its JSON path) and 2 means the file cannot be read as strict JSON: `NaN`, `Infinity`, a number out of range such as `1e999`, a repeated key in one object and nesting that is too deep are all refused. Format assertions are on, so `date` must be a real calendar day.

## Conventions the app must follow

These are stated in the descriptions of the schema and explained in the ADR:

- **Dose classification.** A dose holds five boundaries, not ranges: below `thresholdMin` it has no class (below threshold), from `thresholdMin` up to `lightMin` it is a threshold dose, from `lightMin` up to `commonMin` it is light, then common, then strong, and from `heavyMin` up it is heavy. When a boundary is missing, the two classes it separates cannot be told apart, and the app shows the lower one up to the next known boundary.
- **Units.** Exactly `µg` (micro sign U+00B5, never the Greek letter mu), `mg` and `g` are mass units the app may convert between. Every other value of `units` is opaque and is never converted.
- **Tolerance.** `half` and `zero` carry the wording of the wiki in `text` and, when it is a time, a range in minutes in `min` and `max`. The app uses the numbers and never parses the text.
- **References.** Interaction targets of kind `group` and the `crossTolerances` of a substance refer to groups by `id`, never by display name.
- **Text.** No empty or padded strings and no control characters. Only `effectsSummary`, `dosageRemark`, `generalRisks` and `longtermRisks` may contain line feeds, between paragraphs.
- **Patterns.** Every pattern ends with `$(?![\s\S])` and avoids `\s` where Python and ECMA 262 disagree, so the Python validator and the app accept the same strings.

## Versioning

The schema follows semantic versioning, and the question that decides the number is always the same: what happens to an app that pins the previous version?

- **Major**: a change that breaks an app pinned to the previous major version. Examples: removing or renaming a key, changing the type or the meaning of a value, making an optional key required, adding a value to an enumeration the app switches over, loosening a rule the app relies on.
- **Minor**: an additive change that an app pinned to an earlier minor version of the same major can ignore. Example: a new optional key. Because every object sets `additionalProperties: false`, the app must read datasets leniently (ignore unknown keys) while the pipeline validates strictly.
- **Patch**: descriptions only. Nothing that changes which documents are valid.

`substances.schema.json` accepts only `schemaVersion` values of its own major version. The manifest accepts any `schemaVersion`, so that an app can read the manifest of a release it cannot use and say so.

The app (`Zadrya/Application`) pins a schema version, generates its models from it, and its CI fails if the latest data release needs a major version it does not support.

## Frozen at the first signed release

Until the first signed dataset release, version 1.0.0 may still change in place: nothing depends on it yet. From the first signed release on, a published version is never edited. Every later change is a new version under the rules above, with its number updated in both `$comment` fields, in `SCHEMA_VERSION` and in this file, and with fixtures for each new rule in `tests/fixtures/schema/`.

## For contributors

- Every key has a `description`, and every object rejects unknown keys. Tests enforce both.
- The fixture documents are defined in `tests/schema_cases.py`, each invalid one with the JSON path and the keyword that must reject it. The files in `tests/fixtures/schema/` are generated from it: after a change run `uv run python -m tests.schema_cases` and commit the result. A test fails when the files are out of date.
- What the tests guarantee, exactly: each invalid fixture breaks one rule and nothing else, and removing any single constraint from a schema changes the result of at least one fixture. "Constraint" means the keywords `$ref`, `additionalProperties`, `const`, `enum`, `format`, `items`, `maximum`, `minItems`, `minProperties`, `minimum`, `not`, `oneOf`, `pattern` and `type`, each entry of a `required` list and each entry of a `dependentRequired` map (`tests/test_schema_mutations.py`). They do not guarantee that every string a pattern should reject is rejected, nor that Python and ECMA 262 agree on every pattern: the patterns were checked once by hand in Node, and a new pattern needs the same check.
- The files here are the only copy. `src/zadrya_data/schemas/` holds symbolic links to them, which the build resolves so that the installed package carries the schemas.
