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

Exit code 0 means valid, 1 means schema violations (each printed with its JSON path) and 2 means the file cannot be read as JSON. Format assertions are on, so `date` must be a real calendar day.

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
- Each rule has one invalid fixture in `tests/fixtures/schema/<schema>/invalid/`, named after the rule it breaks, and the test table says which JSON path and keyword must reject it.
- The files here are the only copy. `src/zadrya_data/schemas/` holds symbolic links to them, which the build resolves so that the installed package carries the schemas.
