# 5. Normalization of tolerance, cross tolerance and interactions

- Status: proposed
- Date: 2026-11-17

## Context

ADR 4 normalized the catalog, the text, the classes and the routes, and left every substance without `tolerance`, with empty `crossTolerances` and interaction lists, and both group lists empty. ADR 1 fixed the shapes: `tolerance` with free text `full` and `{text, min, max}` for `half` and `zero`; `crossToleranceGroups` and `interactionGroups` as `substanceGroup` lists (`id`, `name`, `members`); interaction targets of three kinds (`substance`, `group`, `other`). The spec asks the app to check every new ingestion against what is still active, "including chemical and psychoactive classes", and to require explicit confirmation for "dangerous".

The sources do not have these shapes. Both write tolerance as wiki wording ("3 - 7 days"). Cross tolerance is a list of loose tokens taken from a sentence of the wiki (`psychedelic`, `psychedelics`, `GABA|gabaergic`, `trycyclic antidepressants`, `modafanil`, `analog`). Interactions are plain names that mix substances (`Tramadol`), abbreviations (`DXM`, `aMT`), classes in several spellings (`MAOI`, `MAOIs`; `2C-T-x`, `2C-T-X`; `Amphetamines`, `Substituted amphetamines`) and things outside the catalog (`Lithium`, `Grapefruit`). The lists are not symmetric: 143 substances list Tramadol without Tramadol listing them.

A missed warning is the unsafe direction. An alarmist warning is the lesser harm, but warning fatigue is still a harm. Figures are from the snapshot of 2026-11-16 and the base file, as in ADR 4.

## Decision

### Tolerance (`normalize/tolerance.py`)

- `full`, `half` and `zero` are three independent facts, so each is taken on its own: the API text when it is present and not empty, otherwise the base text. This is not the "a block never mixes sources" rule of ADR 4 broken: that rule protects numbers that only make sense together (the boundaries of one dose), and the three tolerance times are separate statements. Using the base text is reported (`tolerance-from-base`, 9 today: 3-FMA, Cinolazepam, Phenazepam, Triazolam), and so is every field where both sources have a text and the texts differ (`tolerance-differs`, none today). Text that is not valid after stripping is reported and treated as absent.
- `half` and `zero` keep the wording as `text` and, when it reads as a time, add `min` and `max` in minutes. A time is a number, or two numbers joined by a hyphen, then `minute`, `hour`, `day`, `week` or `month` in singular or plural, without case. A minute is 1, an hour 60, a day 1440, a week 10080 and a **month 30 days (43200)**, never a calendar month: the same text must always give the same number, and the wiki's "1 month" is an estimate, not a date. A single number gives `min` equal to `max`. Numbers are exact fractions rounded as in ADR 4.
- A wording that does not read as a time, or whose first number is above the second, keeps its text without numbers and is reported (`tolerance-not-parsed`). Every real wording reads (35 distinct texts, from "1 hour" to "2-3 months").

### Cross tolerance (`normalize/cross_tolerance.py`)

The tokens of a substance are the union of both sources, compared without case; a token that only one source has is reported (`cross-tolerance-sources-differ`, 4 today: 3-FMA has none in the API, Morphine has `opioids` only in the API). Each token is looked up, without case, in the explicit table `TOKEN_TO_GROUP`, which lists every token seen in either source. Tokens of the form `a|b` are wiki links (target and label) and are mapped as a whole. The table:

| Group id | Display name | Tokens |
| --- | --- | --- |
| `benzodiazepines` | Benzodiazepines | benzodiazepine, benzodiazepines |
| `cannabinoids` | Cannabinoids | cannabinoids |
| `deliriants` | Deliriants | deliriant |
| `depressants` | Depressants | depressants |
| `dissociatives` | Dissociatives | dissociative, dissociatives, dissociative\|dissociatives |
| `dopaminergic` | Dopaminergic substances | dopamine, dopaminergic |
| `entactogens` | Entactogens | entactogens |
| `gabaergic` | GABAergic substances | gaba, gabaergic, gaba\|gabaergic |
| `hallucinogens` | Hallucinogens | hallucinogen |
| `modafinil-analogs` | Modafinil and its benzhydryl analogs | benzhydryl, modafanil |
| `noradrenergic` | Noradrenergic substances | norepinephrine\|noradrenergic |
| `nootropics` | Nootropics | nootropic, nootropic\|nootropics |
| `opioids` | Opioids | opioids |
| `psychedelics` | Psychedelics | psychedelic, psychedelics |
| `racetams` | Racetams | racetam |
| `serotonergic` | Serotonergic substances | serotonergic, serotonin\|serotonergic |
| `stimulants` | Stimulants | stimulant, stimulants |
| `thienodiazepines` | Thienodiazepines | thienodiazepine, thienzodiazepines |
| `tricyclic-antidepressants` | Tricyclic antidepressants | trycyclic antidepressants |

`modafanil`, `thienzodiazepines` and `trycyclic` are misspellings in the data. N-Methylbisfluoromodafinil lists `modafanil` and `analog`, the wiki's "modafinil analogs": that is the benzhydryl group of Modafinil, Armodafinil and Adrafinil, so `modafanil` maps there. `analog` names no group of its own and is dropped and reported (`cross-tolerance-token-dropped`); so is any token missing from the table, never guessed.

A substance is a member of every group its tokens map to; a group's `members` are those substances, sorted by code points; only groups with members are listed, by id, and each is reported with its members (`cross-tolerance-group`). A substance's `crossTolerances` are its group ids, sorted.

### Interactions (`normalize/interactions.py`)

**Merge.** For each substance, the dangerous, unsafe and uncertain lists of both sources are merged as a union. A target found under two severities, in one source or across both, keeps the higher (dangerous over unsafe over uncertain), reported as `interaction-severity-conflict` (14 today, all within one source: nine opioids list MAOIs as both dangerous and uncertain, four stimulants list Stimulants or MDMA as both dangerous and unsafe). When both sources list targets, a target only one has is reported (`interaction-only-in-one-source`); when one source lists none at all, that is one finding (3-FMA has no API interactions).

**Resolution.** Each name is resolved in this order:

1. a catalog substance by its exact name, by its name without case, or by an alias, without case, that only one catalog substance has: `{kind: substance, name}`;
2. a class named in the table `NAME_TO_GROUP` (`normalize/interaction_groups.py`): `{kind: group, groupId}`;
3. anything else: `{kind: other, name}`, the name as written, one entry per name without case (the first spelling, base before API, is kept). An alias several substances share (`Dex`, `Speed`) is `other`, never a guess.

A substance target that is the substance itself is dropped and reported (none today). Every resolution that is not an exact name is reported once per spelling with the number of substances that list it (`interaction-target-resolved`, 44 today: `DXM`, `MXE`, `5-HTP`, `aMT`, `AMT`, `DPH` by alias, and 38 class spellings), and so is every `other` (`interaction-target-other`).

**Symmetry.** Substance targets are made symmetric: when A lists B, B lists A with the highest severity of the pair. Each target added (842 today) or raised (3: Tramadol and Alcohol, Tramadol and Methoxetamine, MDMA and αMT, all from uncertain to dangerous) is reported on the substance that changed (`interaction-symmetry-added`, `interaction-symmetry-raised`). Group targets are not expanded into substance pairs: that would multiply the data, and members change when the catalog does.

**Own group.** A substance that lists a group it is a member of (Alcohol lists Depressants) keeps the target: it says not to combine it with another substance of the same class, which is real advice. It is reported (`interaction-own-group`, 88 today).

**Order.** Within each severity the targets are sorted by kind (substance, group, other), then by name or group id, by code points.

### Interaction groups

`NAME_TO_GROUP` maps every class name of the data, without case, to a group id. `GROUPS` gives each group its display name and the rule that selects its members. A substance is a member when it matches any part of the rule: a category of the catalog, a psychoactive or chemical class of the API (without case), a regular expression the whole name matches, or an explicit name. Under-inclusion means a missed warning, so a rule includes when unsure; the choices are written next to each rule in the code. Each group is reported with its rule and members (`interaction-group`); a group without members (`interaction-group-empty`) and an explicit name missing from the catalog (`interaction-group-name-missing`, none today) are reported on their own. Only groups some target names are listed.

| Group id | Names in the data | Rule | Members today |
| --- | --- | --- | --- |
| `25x-nboh` | 25x-NBOH | name `25[A-Z]-NBOH` | 3 |
| `25x-nbome` | 25x-NBOMe, NBOMe (NBOMes) | name `25[A-Z]-NBOMe` | 5 |
| `2c-t-x` | 2C-T-x, 2C-T-X | name `2C-T(-[0-9]+)?` (2C-T, the parent, included) | 4 |
| `2c-x` | 2C-x, 2C-X | name `2C-[A-Z].*` (2C-T-x and 2C-B-FLY included), and βk-2C-B | 12 |
| `5-meo-xxt` | 5-MeO-xxT, 5-MeO-xxt | name `5-MeO-[A-Za-z]+T` (5-MeO-DiBF, a benzofuran, excluded) | 4 |
| `aldh2-inhibitors` | ALDH2 inhibitors | none | 0 |
| `antidepressants` | Antidepressants | category antidepressant; class Antidepressant(s) | 2 |
| `antihistamines` | Antihistamine, Antihistamines | Diphenhydramine, Promethazine | 2 |
| `barbiturates` | Barbiturates | category barbiturate; chemical class Barbiturates | 3 |
| `benzodiazepines` | Benzodiazepines | category benzodiazepine; chemical class Benzodiazepines, Thienodiazepines | 23 |
| `cyp2c19-substrates` | CYP2C19-substrates | Carisoprodol, Diazepam, Flunitrazepam | 3 |
| `deliriants` | Deliriant, Deliriants | category deliriant; class Deliriant(s) | 8 |
| `depressants` | Depressant, Depressants | categories depressant, benzodiazepine, barbiturate; class Depressant(s); Desomorphine | 81 |
| `dissociatives` | Dissociatives | category dissociative; class Dissociative(s) | 24 |
| `dox` | DOx | name `DO[A-Z]` | 4 |
| `hepatotoxic-drugs` | Hepatotoxic drugs | none | 0 |
| `hormonal-birth-control` | Hormonal birth control | Progesterone | 1 |
| `maois` | MAOI, MAOIs | Ayahuasca (harmala alkaloids) | 1 |
| `opioids` | Opioids | category opioid; class Opioid(s) | 25 |
| `protease-inhibitors` | Protease Inhibitors | none | 0 |
| `psychedelics` | Psychedelics | category psychedelic; class Psychedelic(s) | 96 |
| `serotonin-releasers` | Serotonin releasers | class Entactogen(s); MCPP, NM-2-AI | 26 |
| `snris` | SNRIs | none | 0 |
| `ssris` | SSRI, SSRIs | none | 0 |
| `stimulants` | Stimulants | category stimulant; class Stimulant(s) | 80 |
| `substituted-amphetamines` | Amphetamines, Substituted amphetamines | chemical class Amphetamine, Substituted amphetamines; Amphetamine, Dextroamphetamine | 36 |
| `tricyclic-antidepressants` | Tricyclic antidepressants | Tianeptine (an atypical tricyclic) | 1 |

`serotonin-releasers` uses the API class, not the entactogen category: the category also holds 2C-B, 2C-T, 2C-T-7, 4-AcO-MiPT, 5-MeO-DiPT, Ayahuasca and Psilocin, which act on receptors and release no serotonin, and 5-HTP lists Serotonin releasers as dangerous. Five groups are empty because no catalog substance belongs to them: SSRIs, SNRIs, protease inhibitors, ALDH2 inhibitors and hepatotoxic drugs. They are kept: the warning still shows on the substance that lists them, and a later catalog may fill them.

### The contract for the app

The app phase implements this; it is the only way the data is complete.

- The severity of a pair of two different catalog substances X and Y is the highest of: a `substance` target of X naming Y, a `group` target of X whose group has Y as a member, and the same two from Y's lists with X. Groups are therefore resolved through `members` in both directions: X lists `stimulants`, Y is a member, so logging Y while X is active warns, and so does logging X while Y is active.
- A `group` target applies to every member, including another member of the substance's own group (Alcohol and GHB both in `depressants`). A substance is never an interaction with itself: a redose is not a combination.
- An `other` target never matches a catalog substance. It is shown on the substance page and in the manual checker as text. Whether it should match a custom substance by name is open.
- The pipeline guarantees that substance pairs are symmetric and that every `groupId` exists; the invariant checks of a later slice verify both on the built dataset.

### Report and order

The findings of this ADR come after those of ADR 4: tolerance and cross tolerance tokens with each substance, in catalog order; then the cross tolerance groups; then the merge findings of each substance, in catalog order; then resolutions and `other` targets by spelling; then symmetry; then the interaction groups by id; then own-group targets in catalog order. The same inputs give the same document and report.

### Tests

Reference cases in `tests/fixtures/normalize/` (`tolerance-*`, `cross-tolerance-*`, `interactions-*`), which may now also pin `interactionGroups` and `crossToleranceGroups`. The real base file is normalized with `tests/fixtures/api/graphql-relations.json`, the whole real API entries of fifteen substances that exercise these rules; because the base file lists interactions for all of its substances, the graph of targets, groups and pairs is real. Every rule was mutation-checked: changing it fails a test.

## Consequences

- The dataset gets 842 interaction targets that the sources do not state in that direction. Each is a finding, so the dataset review sees them.
- The tables `TOKEN_TO_GROUP`, `NAME_TO_GROUP` and `GROUPS` are hand-maintained. A new token is dropped and reported, and a new class name becomes `other` and is reported, until someone adds it.
- Groups that depend on API classes miss a substance the API does not have. Categories cover most groups for base-only substances; `serotonin-releasers` and `substituted-amphetamines` rely on classes and names only, and no base-only substance belongs to them today.
- Membership follows the categories of the base file, which are broad: `stimulants` holds Caffeine, Nicotine, Theacrine, Tyrosine, Oxiracetam, Phenylpiracetam, Benzydamine, Apomorphine and the modafinil family; `depressants` holds Bromantane, Clonidine, Datura, Ibogaine, Nicotine and Salvinorin A; `opioids` holds Naloxone (an antagonist) and Ibogaine; `psychedelics` holds Buspirone and Efavirenz. These follow the data and lean alarmist.

## Open questions for the owner

1. **"Mushrooms".** Ten substances list `Psilocybin mushrooms` in the base and `Mushrooms` in the API. "Mushrooms" is not an alias, so it is `other`, next to the substance target. No warning is lost today, but if the base list goes away the API name would hide it. Option: a small reported table of target names to substances (`Mushrooms` to Psilocybin mushrooms).
2. **Judgement calls in group membership**, each written in the code: βk-2C-B in `2c-x`; Desomorphine in `depressants`; Progesterone in `hormonal-birth-control`; Carisoprodol, Diazepam and Flunitrazepam as `cyp2c19-substrates`; Tianeptine as a tricyclic; Ayahuasca as the only MAOI; MCPP and NM-2-AI as serotonin releasers; Diphenhydramine and Promethazine as the only antihistamines (Quetiapine and Mirtazapine are antihistaminic but left out). Naloxone stays in `opioids` because its category says so.
3. **Cross tolerance tokens are joined, not combined.** "Cross tolerance with dopaminergic stimulants" arrives as `dopamine` and `stimulant`, and the substance becomes a member of both groups, so the app sees cross tolerance between, for example, Tyrosine and Cocaine through `dopaminergic`. For tolerance, an overestimate is not the safe direction: a user who believes their tolerance is high may take more. The app's tolerance chart should present cross tolerance as an estimate and never suggest a larger dose.
4. **Single-member cross tolerance groups** (`deliriants`, `entactogens`, `hallucinogens`, `noradrenergic`, `tricyclic-antidepressants`) relate a substance only to itself today. They are kept so that the meaning of the token is not lost.
5. **`other` targets and custom substances**: whether the app should match an `other` name (Lithium, Grapefruit) against a custom substance the user created.
