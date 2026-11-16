# 1. Dataset schema 1.0.0

- Status: accepted
- Date: 2026-11-16

## Context

The spec (`Application/docs/SPEC.md`, "Substance dataset") asks for a strict JSON Schema in `Zadrya/Data/schema/` with semantic versioning, shared with the app, and lists what a release contains. It does not define the shape of `substances.json` or `manifest.json`. The base file from PsychonautWiki Journal v11.11 has its own shape (durations with a unit per phase, tolerance as free text, interactions as plain names), and the live API has another (dose ranges). Neither is what the app should depend on.

The schema is read by two implementations: `jsonschema` in Python here, and the Dart code of the app. A rule that the two read differently is a bug.

## Decision

### Shape of `substances.json`

- Keys are camelCase, every object sets `additionalProperties: false` and every key has a `description`.
- The top level holds `schemaVersion`, `datasetVersion`, `attribution`, `categories`, `interactionGroups`, `crossToleranceGroups` and `substances`. The two versions sit inside the file so that the signature covers them. The date lives only in the manifest, so the file stays reproducible.
- A substance is identified by its canonical `name`. There is no separate identifier: ingestions store the name, as the spec says.
- Lists that can be empty are required (`aliases`, `categories`, `roas`, `crossTolerances`, `toxicities`, the three interaction lists, both class lists), so the app never has to tell "absent" from "empty". Everything else that may be unknown is optional and is left out when unknown: `saferUse` is never an empty list, and `tolerance`, `duration`, a duration range and `bioavailability` have at least one key when present.
- `saferUse` is a list of strings and the other text fields are single strings, as in the base file.
- Categories have `id`, `name` and `description`. The `color` and `url` that the base file carries are presentation and stay out: the app chooses its own colors.

### Text

- Text is never empty, never only whitespace, never starts or ends with whitespace (the byte order mark U+FEFF counts as whitespace), and never contains a control character (U+0000 to U+001F, U+007F to U+009F) or a line or paragraph separator (U+2028, U+2029).
- One exception, forced by the data: `effectsSummary`, `dosageRemark`, `generalRisks` and `longtermRisks` hold several paragraphs in the base file, separated by line feeds (65 values). These four fields use a second definition, `paragraphs`, with the same rules except that the line feed U+000A is allowed inside. Carriage returns and tabs are not. Whether these fields should instead become lists of paragraphs is open, and is easy to change before the first signed release.

### Groups, interactions and cross tolerance

- `interactionGroups` and `crossToleranceGroups` are top-level lists with one shape, `substanceGroup`: an `id` (slug), a display `name` and `members` (canonical substance names, possibly none). The pipeline computes the members; the schema fixes the shape.
- An interaction target is one of three shapes, told apart by `kind`: `{kind: "substance", name}` (a canonical substance name), `{kind: "group", groupId}` (the `id` of an entry of `interactionGroups`) or `{kind: "other", name}` (a named drug or thing outside the catalog, such as Ritonavir or Grapefruit, kept as text). Groups are referred to by `id` and never by display name, because names can be reworded and ids are stable. The schema uses `oneOf` over three definitions, and `validate` reports the failures of the branch that `kind` selects.
- A substance's `crossTolerances` is a list of ids of `crossToleranceGroups`.
- The phase plan called the second kind `class`. It is named `group` because `classes` already means the psychoactive and chemical classes of a substance, and an interaction group (for example `25x-NBOMe`) is not always one of those.

### Tolerance

`full` is optional free text. `half` and `zero` are optional objects `{text, min, max}`: `text` is the wording of the wiki and is required, `min` and `max` are the same time as a range in minutes, and are present together or not at all (`dependentRequired`). "5 days" is 7200 and 7200; "1-2 weeks" is 10080 and 20160. The app draws the tolerance chart from the numbers and never parses text. A wording that is not a time has `text` only.

### Doses

- A dose is `{units, lightMin, commonMin, strongMin, heavyMin}`: boundaries, as in the base file. `units` is required and every boundary is optional.
- Classification: a dose below `lightMin` is a threshold dose; from `lightMin` up to, but not including, `commonMin` it is light; from `commonMin` up to `strongMin` it is common; from `strongMin` up to `heavyMin` it is strong; from `heavyMin` up it is heavy. A missing boundary means the two classes it would separate cannot be told apart.
- Ranges are not stored. The live API gives a range per class (`light: {min, max}` and so on), and adjacent ranges in the live data leave gaps in 21 places: a dose between the maximum of one class and the minimum of the next has no class, so classification by range is undefined. Boundaries cannot have gaps. For the same reason the range maxima are not stored, and neither is the separate `threshold` value of the API: with boundaries, "threshold" is everything below `lightMin`.
- A dose with `units` and no boundary is allowed. The base file has such entries, and the unit alone is useful: it tells the app which unit the wiki uses for the substance. A route with no dose information at all has no `dose`.

### Units

`units` is text, with a closed convention. Exactly three spellings are mass units that the app may convert between: `µg` (with the micro sign U+00B5), `mg` and `g`. Every other value (`mL`, `mg THC`, `seeds`, and anything else) is opaque: it is shown as written and never converted. The Greek letter mu (U+03BC) looks the same as the micro sign and is a different character, so the schema rejects any unit that contains it, and the pipeline has to normalize it. The base file already uses the micro sign.

### Routes and durations

- `route` is a closed list of eleven names. A new route is a major version, because the app switches over the list.
- Durations are in minutes, one range per phase (`onset`, `comeup`, `peak`, `offset`, `total`, `afterglow`). Each bound is optional, because the wiki often gives only one, but at least one is present. Values are numbers, not integers, so that phases measured in seconds are not rounded away.
- `bioavailability` is a range in percent, 0 to 100, with the same rule for bounds, because the base file has entries with only one of them.
- Every number is non-negative.

### What the schema does not check

Shape only. Increasing dose boundaries, minimum not above maximum, references that exist (categories, groups, substances), symmetric interactions, unique names, aliases and list items are invariants checked by the pipeline. JSON Schema cannot express most of them, and expressing only some would split one concern over two places. There is no `uniqueItems`.

### Two regular expression dialects

`jsonschema` runs patterns with Python's `re`, and the app runs them with ECMA 262 (Dart). They differ in two ways that matter here:

- In Python a final `$` also matches before a trailing newline, so `"1.0.0\n"` would pass here and fail in the app. Every pattern ends with `$(?![\s\S])`, which both dialects read as the very end of the string.
- `\s` does not cover the same characters. Addresses use an explicit class of printable ASCII (`[!-~]`), so anything else must be percent-encoded, as the base file already does. The text patterns add U+FEFF and the control ranges explicitly, which removes the difference.

Each pattern has a fixture with a trailing newline, and all patterns were run once in a real ECMA 262 engine (Node) against the same samples. That check is manual: the test job has no JavaScript engine.

### Strict JSON

`validate` reads documents with `zadrya_data.strict_json`: `NaN`, `Infinity`, numbers out of range such as `1e999`, and objects with a repeated key are rejected, and nesting that is too deep is an error instead of a crash. All of them exit with code 2. The base loader on its own branch has a private copy of the same checks; the two are unified after both are merged.

### Versions, addresses and dates

- Versions are plain `MAJOR.MINOR.PATCH`, without pre-release or build metadata: one accepted spelling is easier to compare in the app.
- `substances.schema.json` accepts only `schemaVersion` 1.x.y, so a document of another major version fails validation instead of being half understood. `manifest.schema.json` accepts any version, so that an app can read the manifest of a release it cannot use.
- Addresses are checked with a pattern (`https://`, and `https://psychonautwiki.org/wiki/` for a substance article), not with `format: uri`. `jsonschema` asserts `uri` only when an optional package is installed and otherwise accepts anything silently, which is the wrong failure mode.
- `date` uses `format: date` with format assertions on, which rejects days that do not exist.
- `sha256` is 64 lowercase hexadecimal characters.

### Manifest

`manifest.json` holds `datasetVersion`, `schemaVersion`, `minAppVersion`, `sha256` (of the exact bytes of `substances.json`), `date` and `attribution`, all required. The signature is not in the manifest: it is its own release asset. The manifest schema repeats the `attribution`, `semver` and `text` definitions instead of referring to the other file, so each schema is self-contained for the code generator of the app; a test keeps the copies identical.

### Where the files live

The schemas live in `schema/`, where the spec puts them. The Python package reads them through symbolic links in `src/zadrya_data/schemas/`, which the build backend resolves into real files in the wheel. This keeps one copy and works both from a checkout and from an installed package. When a link is not a link (a clone without symbolic link support), loading fails with `SchemaLoadError`, which says so.

### Fixtures

Every fixture document is defined in `tests/schema_cases.py`, with the JSON path and the keyword that must reject it, and the files in `tests/fixtures/schema/` are generated from it. Tests check that the files are up to date, that each invalid document breaks exactly its rule, and, by removing each constraint of the schema in turn, that no constraint can be dropped without a fixture changing its result.

### Versioning rules

Major: a change that breaks an app pinned to the previous major. Minor: additive. Patch: descriptions only. The version is frozen at the first signed release (see `schema/README.md`).

## Consequences

- The pipeline must normalize the base file and the API into this shape: convert durations and tolerance times to minutes, trim text, turn dose ranges of the API into boundaries, build the two group lists and map names to group ids, and type the interaction targets.
- Because objects reject unknown keys, a minor version that adds a key is only safe if the app ignores unknown keys when it reads a dataset. The app must be written that way.
- The app must implement the dose classification and the unit convention exactly as written here; both are also in the descriptions of the schema.
- A `oneOf` is harder for code generators than a flat object. The three target shapes are separate definitions with a constant `kind`, which generators can map to a sealed class.
- The symbolic links need a file system and a git configuration that support them (macOS and Linux do).
- The `$id` of each schema is its raw address on the `main` branch. It identifies the schema and is not fetched by the validator.
