# 4. Normalization of the catalog, text, classes and routes

- Status: accepted
- Date: 2026-11-17

## Context

The dataset is built from two sources: the base file of PsychonautWiki Journal v11.11 (ADR 1 of the base import, `sources/base/Substances.json`) and a raw snapshot of the PsychonautWiki API and wiki (ADR 2). The spec lists what normalization must do (drop class and disambiguation pages, canonical names and aliases, units, routes, dose ranges, durations per phase) and the phase plan fixes the merge policy in one sentence: a value from the API replaces the base value only when it is present and consistent. Neither says what "consistent" means, how the two shapes map to the schema of ADR 1, or what to do with the oddities of the real data.

This ADR covers the first half of normalization: the catalog, names, text, categories, classes and routes. Tolerance, cross tolerance and interactions are normalized in the next slice, recorded in ADR 5.

The figures below are from the snapshot fetched on 2026-11-16 (373 API entries) and the base file (289 substances).

## Decision

### Pure, and nothing silent

`normalize(base, snapshot)` reads two typed objects and returns plain data and a report. It uses no network, no clock and no randomness: the same inputs give the same bytes and the same report. Whatever it drops, takes from the other source or repairs is a finding in the report (kind, substance, route, detail). It raises only where going on would mean guessing: a route name outside the schema, a route listed twice in one source, two substances that end up with one name, a URL or a category the schema refuses, a snapshot that was not fetched with this base file.

### Catalog

- Every substance of the base file is in the catalog.
- An API entry that is not in the base file enters only when it has at least one route with a number (in its dose, duration or bioavailability) and is named in the allow list `ALLOWED_API_ONLY` (`normalize/catalog.py`), each name with its reason. The list is **proposed: catalog membership is the owner's decision, confirmed in the dataset review**. Today it names 25E-NBOH, Blue Lotus and Tizanidine.
- Why an allow list and not "has data": the wiki has joke and stub pages with doses. "Cake" has an oral dose of 30 to 300 g and the class Depressant, and its page is the 2017 April Fools joke. It is not on the list; the report says so, with the reason.
- An API entry without any number is dropped and reported (89 today: class pages such as Stimulants, disambiguation pages, and entries whose routes state units only, such as 1,3-Butanediol and Grayanotoxin). Units alone are not data.
- An allowed entry that has no number left after normalization is dropped and reported.
- Matching between the sources is by exact name. An API name that differs from a base name only by case or whitespace, or that the wiki redirects to the same page, is the same substance: it is reported and named after the wiki's canonical title. None occurs today. An ambiguous match stops the normalization.
- A substance keeps the URL of the base file when it has one, otherwise the URL of the API. A base substance whose wiki page is missing stays, with its base URL, and is reported (nine today: Apomorphine, Bromazolam, Chlordiazepoxide, Cinolazepam, Etomidate, Oxazepam, Phenazepam, Tilidin, Triazolam). A wiki redirect to another title is reported and the name is kept (Blue Lotus).

### Names

Aliases are the base common names followed by the API common names: stripped, without the canonical name, without repeats. Repeats and the canonical name are recognized without regard to case, and the first spelling is kept. Collisions between substances belong to the invariants.

### Text

- All text is stripped of whitespace (and byte order marks) at both ends and otherwise left alone. Text that still breaks the text rules of the schema is reported and dropped, never repaired. The rules are read from the schema file itself, so normalization and validation cannot disagree. The four paragraph fields keep the line feeds between paragraphs.
- `summary` is the base summary and nothing else. The `summary` of the API is the first text of the wiki page, and for the substances that need it, it is rarely a summary. Of 373 API summaries, 172 are the placeholder "Summary sheet: ...". Of the 26 that are not placeholders on substances without a base summary, 7 begin "This page has not been fully approved by the PsychonautWiki administrators", others are a stub notice, a note that the article is in the Talk namespace, "Not to be confused with A-PVP. Summary sheet: A-PHP" (the placeholder behind a prefix), "Gaboxadol Chemical Nomenclature", or an overdose warning box; three or four read like a summary. A filter for banners would be a moving target, so the API summary is never used. 80 of 292 substances have no summary and are reported. **Follow-up:** read a proper lead paragraph through the MediaWiki API in a later slice.
- `effectsSummary`, `dosageRemark`, `generalRisks`, `longtermRisks` and `saferUse` come from the base file; the API does not have them. An empty `saferUse` becomes absent.
- `addictionPotential` and `toxicities` take the API value when it is present and not empty, otherwise the base value. The API values were read in full (44 and 49 distinct values): they are ordinary phrases without banners or placeholders, and equal the base wherever both exist.

### Categories and classes

- The category list is the base list, in base order. `id` and `name` are both the base name, which is verified to be a slug; `color` and `url` are presentation and are left out.
- A base substance keeps its base categories. A category that is not in the list is reported and dropped (none today).
- A substance that only the API has gets categories from its psychoactive classes through the table `CLASS_TO_CATEGORY` (`normalize/categories.py`), which lists the fifteen classes of the API in singular and plural (for example "Psychedelic" to `psychedelic`, "Stimulants" to `stimulant`, "Dissociatives" to `dissociative`, "Opioids" to `opioid`). A class without a mapping is reported. The derivation is reported, also when it yields nothing (Blue Lotus has no class).
- `classes.psychoactive` and `classes.chemical` are the API lists as given: stripped, without exact repeats, in API order. They are empty for a base-only substance.

### Routes and the merge policy

The routes of a substance are the union of both sources by name, in the order of the schema's route list. A route that only one source lists is kept, and reported when the substance is in both sources.

Each route has up to eight blocks: the dose, the six duration phases and the bioavailability. For each block:

1. the API block, when it is present and consistent;
2. otherwise the base block, when it is present and consistent;
3. otherwise no block.

A block is never assembled half from one source and half from the other, with the single exception of the unit qualifier below. An API block that was rejected, a base block used because the API has none, and a block dropped because neither is consistent are reported. A dose that states units only is "weak": it is used only when the other source has no boundaries either. When the API states units only and the base block is inconsistent, the units are kept and the loss of the base block is reported as `block-dropped`, with the reason the base block was unusable. When a consistent API block is used and the base block is inconsistent, the base block is reported as `base-block-inconsistent`, with its reason: nothing usable is lost, but the error in the source data is visible in the dataset review (none today; the one inconsistent base dose, Meclofenoxate oral, is inconsistent in the API too and is dropped).

**What changed against the base file.** When the chosen block comes from the API and the base has a consistent block for the same route, every difference is reported, so that the dataset review sees each one, including every value the base states and the chosen API block does not:

- `dose-changed`, one finding per boundary, with its direction (`lower` or `higher`). A higher `strongMin` or `heavyMin` is the risky direction, because the doses between the two values now show in the class below; such a finding says `HIGHER (risky)` and names those doses. When the units differ, the numbers are listed without a direction, because they cannot be compared.
- `unit-changed` when the units differ.
- `dose-boundary-not-in-api`, one finding per boundary the base dose states and the chosen API dose does not. Under the rules above this can only be `thresholdMin` (or `lightMin`, which the base never states): a missing upper boundary rejects the API block instead.
- `duration-changed`, one finding per bound of a phase, in minutes, with its direction.
- `duration-bound-not-in-api`, one finding per bound the base phase states and the chosen API phase does not.
- `bioavailability-changed`, one finding per bound, in percent, with its direction.
- `bioavailability-bound-not-in-api`, one finding per bound the base states and the chosen API block does not.

**No base value of a block disappears without a finding.** For the dose, each of the six duration phases and the bioavailability of a route, the base block ends in one of these ways, and each is either lossless or reported: the base block is used whole (reported as `base-block-used` or `api-block-rejected` when the API had the route); the API block is used and the base block was consistent (each difference and each base value the API lacks is reported, as above); the API block is used and the base block was inconsistent (`base-block-inconsistent`); the API states units only and the base block was inconsistent (`block-dropped`); neither source has a consistent block (`block-dropped`, with both reasons). Two transformations of base values are documented rules, not losses: the base `lightMin` is stored as `thresholdMin` (ADR 1), and durations are converted to minutes, with any rounding reported (`duration-rounded`). Outside these blocks, the base category `color` and `url` and the substance flag `isApproved` are not in the schema and are not carried.

Today: Clonazolam oral (common 200 to 125 µg, strong 400 to 300, heavy 999 to 500) and N-Ethylhexedrone insufflated (30, 40, 50 to 24, 30, 40 mg), all lower; durations of Cocaine insufflated, NEP insufflated (total), Oxycodone oral and insufflated. No higher `strongMin` or `heavyMin`, and no change of unit. `dose-boundary-not-in-api` occurs on 8 routes, the same 8 that carry `dose-label-differs` below: the API has no threshold and states the base threshold as its light minimum, so the number is kept under another label and both findings say so. `duration-bound-not-in-api`, `bioavailability-changed`, `bioavailability-bound-not-in-api` and `base-block-inconsistent` do not occur.

### Dose

The schema stores five boundaries (ADR 1). They come from the API as:

| Boundary | Direct value | Fill, only when the direct value is absent |
| --- | --- | --- |
| `thresholdMin` | `threshold` | none |
| `lightMin` | `light.min` | none |
| `commonMin` | `common.min` | `light.max` |
| `strongMin` | `strong.min` | `common.max` |
| `heavyMin` | `heavy` | `strong.max` |

**Why maxima are used as fills, and only as fills.** Range maxima are not stored, because adjacent ranges leave gaps (ADR 1). But dropping them entirely loses information: on 41 routes the API has no `heavy` value and a `strong.max`, and on 11 it has no `strong` range and a `common.max`. Without the fill those routes would have no `heavyMin` (or `strongMin`), and the app would show any dose above the last boundary, however large, in the lower class. They include Fentanyl insufflated (75 µg), Acetylfentanyl, 25I-NBOMe sublingual (1000 µg) and the other NBOMe and NBOH compounds, PCP, PCE and Rolicyclidine on all routes, Pentobarbital, Phenobarbital and Secobarbital (300 mg), Methaqualone, Pethidine and 5-MeO-DMT insufflated; and for `strongMin`, PMA, PMMA, Ibogaine and Naloxone. The base file has exactly the filled number on all 40 and 11 routes it shares with the API, so the Journal app did the same. A fill is used only when the direct value is absent, moves one step only, and is discarded and reported if it would break the order (none today). Each fill is reported.

**Upper boundaries the base has are never lost.** For a route in both sources, after fills, an API block that lacks `commonMin`, `strongMin` or `heavyMin` while the consistent base block has it is rejected, and the whole base block is used, reported as `api-block-rejected` with the reason "missing upper boundaries the base has". Losing an upper boundary is the unsafe direction (larger doses would show in a lower class), so a stale but complete block is preferred to a fresh but truncated one. Differences only in `thresholdMin` or `lightMin` keep the API block and are reported as label differences. Normalization then checks every route with a consistent base dose: if its result lacks an upper boundary the base has, it stops with an error instead of producing the output. This guard runs on whatever input normalization is given, not only on the recorded data. Today the rule changes no route: the fills already supply every upper boundary the base has.

From the base file: `thresholdMin` is the base `lightMin` (the lowest number of the Journal app is the wiki threshold, ADR 1), `lightMin` is absent, and `commonMin`, `strongMin`, `heavyMin` are as named.

On 8 routes the API has no threshold and a light minimum: `lightMin` is set, `thresholdMin` is absent, and the difference in label against the base file, which calls the same number the threshold, is reported (`dose-label-differs`). The base `thresholdMin` is also reported as not in the API block (`dose-boundary-not-in-api`). On all 8 routes the two numbers are equal (4-HO-EPT oral, EPT insufflated, JWH-073 smoked, Methylnaphthidate insufflated, Metizolam oral, Myristicin oral, Progesterone oral and rectal).

A block is **consistent** when it has usable units, every API range (light, common, strong) has its minimum at or below its maximum, and every boundary is finite, not negative and not below the one before it, in the order threshold, light, common, strong, heavy, skipping absent ones. An inverted range makes the whole API block inconsistent before anything is mapped or filled, since neither its minimum nor its maximum can be trusted. The order check runs on the direct values first and then on each fill. Equal neighbours are allowed and reported: 100 today, 98 of them a threshold equal to the light minimum, plus 4-MeO-PCP insufflated (strong and heavy both 150) and Theacrine insufflated (threshold and common both 25).

One real API block has an inverted range: **HXE insufflated**, whose light range is 40 to 20. The base block (20, 40, 70, 120 mg) is used and the rejection is reported. Before this rule the API block was used, with a light minimum of 40 equal to its common minimum.

Two real dose blocks are inconsistent and are dropped:

- **Meclofenoxate oral**: 50, 400, 800, 600 in both sources (strong starts above heavy).
- **Tizanidine oral**: the API has a threshold of 25 and a light minimum of 2; the substance is API-only, so there is no base block. It stays in the catalog because its durations have numbers.

### Units

Units are stripped and kept as written, with one repair: the Greek letter mu becomes the micro sign (6 routes: Clonidine, Fentanyl on three routes, Flubromazolam, Sufentanil). Every final unit other than `µg`, `mg` and `g` is reported and left alone: `mL` (1,4-Butanediol, 2M2B, GBL), `Mg#` (Apomorphine), `mg/kg of body weight` (Ibogaine), `seeds` (LSA, two routes), `mg THC` and `mg Psilocybin`. Boundaries without units are inconsistent.

**The unit qualifier: the single, deliberate exception to "never mix sources".** When a route is in both sources, the API block is the one chosen, and the base unit is in the list `QUALIFIED_UNITS` (`normalize/dose.py`) and is the API unit followed by a space and a qualifier (compared after the Greek mu repair), the dose keeps every API number and takes the base unit. Only the unit string crosses; no number ever does. The list is **proposed: the owner confirms it in the dataset review**. It holds `mg THC` and `mg Psilocybin`, the three routes where the units of the two sources differ: Cannabis oral and smoked and Psilocybin mushrooms oral. The numbers are milligrams of the active compound, not of the material a user weighs. Plain `mg` is a mass unit the app may convert (ADR 1), so half a gram of flower or two grams of dried mushrooms would be compared with 10 mg and 50 mg and shown as far beyond heavy. With the qualifier the unit is opaque, never converted, and says what the number measures.

A list, not a general rule, because a qualifier only belongs on the list when someone has checked what its numbers measure. Any other base unit of the form "API unit, space, qualifier" is reported as `unit-qualifier-not-adopted` and not used; the API unit stays and the change of unit is reported. None occurs today. An unrelated base unit (`seeds` against `mg`) is not a qualifier at all. Each adoption is reported as `unit-qualified`.

### Durations

- The six phases of the schema are separate blocks. The API's seventh phase, `duration`, is not in the schema: it is reported and ignored (MDAI oral).
- Values are converted to minutes: seconds divide by 60, minutes stay, hours multiply by 60, days by 1440. Unit names are matched without case and in singular or plural (`Hours`, `hour`).
- A phase is consistent when its numbers have a known unit, are finite and not negative, and the minimum is not above the maximum. A phase with one bound is kept. A phase without numbers is absent, whatever its unit.

### How numbers are written

Every number is handled as an exact fraction made from the shortest decimal text of the source value, so 15.0 is 15 and 0.1 is one tenth. Conversions are exact. A converted duration is then rounded to four decimal places, half to even, which is finer than anything the sources state, and the rounding is reported (41 values today, all from seconds: 5 seconds is 0.0833 minutes). A number is written as an integer when it is whole and as the shortest decimal otherwise: 45 seconds is `0.75`, and no value carries binary floating point noise.

### Bioavailability

The API block, otherwise the base block. Consistent means every bound is within 0 to 100 and the minimum is not above the maximum. Changes against the base are reported as for durations (`bioavailability-changed`, `bioavailability-bound-not-in-api`).

### Output and order

The result is `categories`, `interactionGroups`, `crossToleranceGroups` and `substances` as plain data in the shape of the schema; the build adds the versions and the attribution. Order: categories as in the base file; substances by the code points of their names; routes in the order of the schema's route list; aliases, classes, toxicities and safer use items in source order (base first, then API, where both contribute). The report lists catalog findings first, in base file order, then the findings of each substance in catalog order.

### Tests

Each rule has a reference case in `tests/fixtures/normalize/`: a small JSON file that states the rule and gives only the inputs it is about. The real base file is normalized with two recorded API answers; one of them, `graphql-doses.json`, holds the real dose blocks of every substance whose dose normalization does something (62 entries), so the 41 and 11 fills, the label differences and the two dropped blocks are pinned. A regression guard asserts that no dose boundary of the base file is lost without a report.

## Consequences

- Against the base file the dataset changes where the wiki has changed. Every such change is a `dose-changed`, `unit-changed` or `duration-changed` finding, which the diff report of a later slice prints; a higher `strongMin` or `heavyMin` is marked as risky.
- Three substances enter the catalog from the API, without base text: no summary, no risks, no safer use advice. Tizanidine's wiki page carries the banner that it "has not been fully approved" and "may contain incorrect information, particularly with respect to dosage". The base file has an `isApproved` flag (23 substances are not approved) that the schema does not carry; whether unapproved pages should be marked in the app is open.
- Some plain mass units do not measure what a user weighs or counts: Alcohol in `g` (ethanol, not the drink), Nitrous in `g` (gas), Nicotine in `mg` (not tobacco), Myristicin in `mg` (the compound of nutmeg). Kratom and Blue Lotus in `g` do measure plant material. These are listed for the dataset review; normalization does not change them.
- The allow list, the class mapping and the list of qualified units are hand-maintained tables. An API entry with data that is not on the list is reported on every build until someone decides.
- 80 substances have no summary until the follow-up reads lead paragraphs from the wiki.
