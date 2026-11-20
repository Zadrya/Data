# 7. Dataset invariants and the build command

- Status: proposed
- Date: 2026-11-20

## Context

The schema checks shape only (ADR 1, "What the schema does not check"): increasing dose boundaries, minimum not above maximum, references that exist, symmetric interactions, unique names, aliases and list items are left to the pipeline. Normalization already produces data that keeps most of these rules (ADR 4 and 5), but it is the code under test. The signed bytes need a check that does not depend on it.

## Decision

### Invariants (`src/zadrya_data/invariants.py`)

The invariants are a second, independent check over the finished document. They import nothing from `normalize` and read only the document, so a bug in a normalization rule cannot also hide itself here. They assume a document the schema accepts: the build validates the schema first. Each rule yields every place it is broken, with the substance (or `(catalog)` for the top-level lists) and the field, and `require` raises `InvariantError` with all of them, sorted, never only the first.

| Rule | What must hold |
| --- | --- |
| `dose-order` | The dose boundaries present in a route never decrease, in the order `thresholdMin`, `lightMin`, `commonMin`, `strongMin`, `heavyMin`. Equal neighbours are allowed (below). |
| `range` | `min` is not above `max` in every duration phase, every bioavailability and the tolerance times `half` and `zero`. |
| `target-exists` | A `substance` target is another substance of the catalog, never the substance itself. |
| `target-unique` | A target appears once across the three severities of a substance (`other` targets without case). |
| `interaction-symmetric` | When A lists the substance B, B lists A with the same severity. |
| `group-exists` | A `group` target is the id of an entry of `interactionGroups`. |
| `member-exists` | Every member of every interaction and cross tolerance group is a substance of the catalog. |
| `cross-tolerance` | A substance lists exactly the cross tolerance groups it is a member of, and each exists. |
| `category-exists` | A substance's categories are ids of `categories`. |
| `unique-id` | Ids are unique within `categories`, `interactionGroups` and `crossToleranceGroups`. |
| `unique-name` | Canonical names are unique without case. |
| `unique-alias` | An alias leads to exactly one substance, without case: it is not the substance's own name, not another substance's name, not carried by another substance and not repeated. |
| `alias-not-group` | No alias is, without case, the name or the id of an interaction or cross tolerance group. |
| `unique-items` | No list holds an item twice: routes, categories, both class lists, cross tolerances, toxicities, safer use items and group members. |
| `mass-unit` | A dose unit never holds the Greek letter mu (U+03BC), and a unit that spells a mass another way (`MG`, `mcg`, `ug`, `grams`, compared after NFKC and without case) is refused: the only mass spellings are `µg` (micro sign U+00B5), `mg` and `g`. Every other unit (`mL`, `mg THC`, `seeds`, `Mg#`) stays opaque. |
| `finite` | No number anywhere is NaN or infinite. |

**Equal dose boundaries are allowed.** ADR 4 accepts equal neighbours and reports each one (`dose-equal-boundaries`, 100 in the snapshot of 2026-11-16: 98 a threshold equal to the light minimum, plus 4-MeO-PCP insufflated with `strongMin` and `heavyMin` both 150 and Theacrine insufflated with `thresholdMin` and `commonMin` both 25). The invariant enforces exactly that: boundaries never decrease. Equal boundaries are safe because the classification of ADR 1 takes each boundary as the start of its class, up to but not including the next one: between two equal boundaries the lower class is empty, and a dose at that value takes the higher class. A user who logs 150 mg of 4-MeO-PCP sees it as heavy, never as strong. A strict rule would have refused these real routes, or forced normalization to drop a boundary the wiki states.

**Mutation check.** `tests/test_invariants.py` has one failing case per rule, each a single change to a valid document, and shows that removing a rule from the checker lets its case pass: no rule is covered by another by accident. Edge cases that must stay valid (equal dose neighbours, `min` equal to `max`, one-sided ranges, opaque units) are pinned too. The real base file, normalized with each recorded API answer, keeps every invariant.

## Consequences

- A collision of names or aliases that normalization lets through stops the build instead of reaching the app.
- A rule here can repeat a rule of normalization. That is the point: the two are written separately, so a mistake has to be made twice to ship.
- A new cross-field rule needs a failing case and passes the mutation check, as the schema fixtures do.
