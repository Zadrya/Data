# 1. Dataset schema 1.0.0

- Status: accepted
- Date: 2026-11-16

## Context

The spec (`Application/docs/SPEC.md`, "Substance dataset") asks for a strict JSON Schema in `Zadrya/Data/schema/` with semantic versioning, shared with the app, and lists what a release contains. It does not define the shape of `substances.json` or `manifest.json`. The base file from PsychonautWiki Journal v11.11 has its own shape (flat dose minimums, durations with a unit per phase, interactions as plain names), which is not what the app should depend on.

## Decision

### Shape of `substances.json`

- Keys are camelCase, every object sets `additionalProperties: false` and every key has a `description`.
- The top level holds `schemaVersion`, `datasetVersion`, `attribution`, `categories`, `interactionGroups` and `substances`. The two versions sit inside the file so that the signature covers them. The date lives only in the manifest, so the file stays reproducible.
- A substance is identified by its canonical `name`. There is no separate identifier: ingestions store the name, as the spec says.
- Lists that can be empty are required (`aliases`, `categories`, `roas`, `crossTolerances`, `toxicities`, the three interaction lists, both class lists), so the app never has to tell "absent" from "empty". Everything else that may be unknown is optional and is left out when unknown: an optional string is never empty, `saferUse` is never an empty list, and `tolerance`, `duration`, a duration range and `bioavailability` have at least one key when present.
- `saferUse` is a list of strings and the other text fields are single strings, as in the base file.
- Categories have `id`, `name` and `description`. The `color` and `url` that the base file carries are presentation and stay out: the app chooses its own colors.

### Interactions

- A target is `{kind, name}` with `kind` one of `substance` (a canonical substance name), `group` (the `name` of an entry in `interactionGroups`) or `other` (a named drug or thing outside the catalog, such as Ritonavir or Grapefruit, kept as text).
- Groups are listed at the top level with an `id`, a `name` and their `members` (canonical names, possibly none), so that the app can resolve "Stimulants" to the substances it covers. Targets refer to a group by name, the same way they refer to a substance, so one rule covers both kinds.
- The phase plan called the second kind `class`. It is named `group` here because `classes` already means the psychoactive and chemical classes of a substance, and an interaction group (for example `25x-NBOMe`) is not always one of those.

### Routes, doses and durations

- `route` is a closed list of eleven names. A new route is a major version, because the app switches over the list.
- A dose has `units` (the wiki unit, as text), an optional `threshold`, optional `light`, `common` and `strong` ranges with both bounds, and an optional `heavy` number. A dose range needs both bounds: a range with one bound cannot be shown or compared, so the pipeline drops it instead.
- Durations are in minutes, one range per phase (`onset`, `comeup`, `peak`, `offset`, `total`, `afterglow`). Each bound is optional, because the wiki often gives only one, but at least one is present. Values are numbers, not integers, so that phases measured in seconds are not rounded away.
- `bioavailability` is a range in percent, 0 to 100, with the same rule for bounds, because the base file has entries with only one of them.
- Every number is non-negative.

### What the schema does not check

Shape only. Increasing dose ranges, minimum not above maximum, references that exist (categories, groups, substances), symmetric interactions, unique names, aliases and list items are invariants checked by the pipeline. JSON Schema cannot express most of them, and expressing only some would split one concern over two places.

### Versions, addresses and dates

- Versions are plain `MAJOR.MINOR.PATCH`, without pre-release or build metadata: one accepted spelling is easier to compare in the app.
- `substances.schema.json` accepts only `schemaVersion` 1.x.y, so a document of another major version fails validation instead of being half understood. `manifest.schema.json` accepts any version, so that an app can read the manifest of a release it cannot use.
- Addresses are checked with a pattern (`https://`, and `https://psychonautwiki.org/wiki/` for a substance article), not with `format: uri`. `jsonschema` asserts `uri` only when an optional package is installed and otherwise accepts anything silently, which is the wrong failure mode.
- `date` uses `format: date` with format assertions on, which rejects days that do not exist.
- `sha256` is 64 lowercase hexadecimal characters.

### Manifest

`manifest.json` holds `datasetVersion`, `schemaVersion`, `minAppVersion`, `sha256` (of the exact bytes of `substances.json`), `date` and `attribution`, all required. The signature is not in the manifest: it is its own release asset. The manifest schema repeats the `attribution` definition instead of referring to the other file, so each schema is self-contained for the code generator of the app; a test keeps the two copies identical.

### Where the files live

The schemas live in `schema/`, where the spec puts them. The Python package reads them through symbolic links in `src/zadrya_data/schemas/`, which the build backend resolves into real files in the wheel. This keeps one copy and works both from a checkout and from an installed package.

### Versioning rules

Major: a change that breaks an app pinned to the previous major. Minor: additive. Patch: descriptions only. The version is frozen at the first signed release (see `schema/README.md`).

## Consequences

- The pipeline must normalize the base file and the API into this shape: split the flat dose minimums into ranges, convert durations to minutes, lowercase the cross tolerance tokens (the base file has values such as `GABA` and `serotonin|serotonergic`) and type the interaction targets.
- Because objects reject unknown keys, a minor version that adds a key is only safe if the app ignores unknown keys when it reads a dataset. The app must be written that way.
- The symbolic links need a file system and a git configuration that support them (macOS and Linux do). A clone on Windows without symlink support would not find the schemas.
- The `$id` of each schema is its raw address on the `main` branch. It identifies the schema and is not fetched by the validator.
