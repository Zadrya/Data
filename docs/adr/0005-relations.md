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

**Merge.** For each substance, the dangerous, unsafe and uncertain lists of both sources are merged as a union. A target found under two severities, in one source or across both, keeps the higher (dangerous over unsafe over uncertain), reported as `interaction-severity-conflict` (14 today, all within one source: nine opioids list MAOIs as both dangerous and uncertain, four stimulants list Stimulants or MDMA as both dangerous and unsafe). When both sources list targets, a target only one has is reported (`interaction-only-in-one-source`); when one source lists none at all, that is one finding (2 today: 3-FMA has no API interactions, and Caffeine lists Lithium only in the API). A substance for which neither source lists a single target is reported as `interaction-lists-missing` (86 today, among them PMMA, Etizolam, Lorazepam, Flunitrazepam, the three barbiturates, Zolpidem, Zopiclone, Phenibut, Promethazine and Tianeptine): it receives warnings only from the lists of other substances, by symmetry, and through the groups it belongs to.

**Resolution.** Each name is resolved in this order:

1. a catalog substance by its exact name, through the table `TARGET_NAMES` of colloquial names of the data (without case), by its name without case, or by an alias, without case, that only one catalog substance has: `{kind: substance, name}`. `TARGET_NAMES` holds only names whose meaning is certain; today one, `Mushrooms` to Psilocybin mushrooms (the API writes it where the base file writes the full name, on ten substances). Without it the two spellings were a substance target and a duplicate `other`, and the warning depended on the base list surviving. No other `other` target or resolved name of the data is a colloquial or plural name of a catalog substance;
2. a class named in the table `NAME_TO_GROUP` (`normalize/interaction_groups.py`): `{kind: group, groupId}`;
3. anything else: `{kind: other, name}`, the name as written, one entry per name without case (the first spelling, base before API, is kept). An alias several substances share (`Dex`, `Speed`) is `other`, never a guess.

A name that is a group name and also a catalog name (other than the exact name) or alias stops the normalization with both candidates: resolving it to the substance would hide the group's warnings, and resolving it to the group would hide the substance's. No such name exists today.

A substance target that is the substance itself is dropped and reported (none today). Every resolution that is not an exact name is reported once per spelling with the number of substances that list it (`interaction-target-resolved`, 45 today: `Mushrooms` by the table, `DXM`, `MXE`, `5-HTP`, `aMT`, `AMT`, `DPH` by alias, and 38 class spellings), and so is every `other` (`interaction-target-other`, 5 today: Lithium, Grapefruit, Bupropion, Ritonavir, Trazodone).

**Symmetry.** Substance targets are made symmetric: when A lists B, B lists A with the highest severity of the pair. Each target added (842 today) or raised (3: Tramadol and Alcohol, Tramadol and Methoxetamine, MDMA and αMT, all from uncertain to dangerous) is reported on the substance that changed (`interaction-symmetry-added`, `interaction-symmetry-raised`). Group targets are not expanded into substance pairs: that would multiply the data, and members change when the catalog does.

**Own group.** A substance that lists a group it is a member of (Alcohol lists Depressants) keeps the target: it says not to combine it with another substance of the same class, which is real advice. It is reported (`interaction-own-group`, 92 today).

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
| `antihistamines` | Antihistamine, Antihistamines | Diphenhydramine, Promethazine (the two the base file calls antihistamines) | 2 |
| `barbiturates` | Barbiturates | category barbiturate; chemical class Barbiturates | 3 |
| `benzodiazepines` | Benzodiazepines | category benzodiazepine; chemical class Benzodiazepines, Thienodiazepines; Chlordiazepoxide, Cinolazepam | 25 |
| `cyp2c19-substrates` | CYP2C19-substrates | Carisoprodol, Diazepam, Flunitrazepam | 3 |
| `deliriants` | Deliriant, Deliriants | category deliriant; class Deliriant(s) | 8 |
| `depressants` | Depressant, Depressants | categories depressant, benzodiazepine, barbiturate; class Depressant(s); Desomorphine, Tilidin | 82 |
| `dissociatives` | Dissociatives | category dissociative; class Dissociative(s) | 24 |
| `dox` | DOx | name `DO[A-Z]` | 4 |
| `hepatotoxic-drugs` | Hepatotoxic drugs | none | 0 |
| `hormonal-birth-control` | Hormonal birth control | Progesterone | 1 |
| `maois` | MAOI, MAOIs | Ayahuasca (harmala alkaloids); αMT, PMA, PMMA, Bromo-DragonFLY (MAO-A inhibitors); 2C-T-7 (a "possible MAOI" in its base summary) | 6 |
| `opioids` | Opioids | category opioid; class Opioid(s); Tilidin | 26 |
| `protease-inhibitors` | Protease Inhibitors | none | 0 |
| `psychedelics` | Psychedelics | category psychedelic; class Psychedelic(s) | 96 |
| `serotonin-releasers` | Serotonin releasers | class Entactogen(s); Ethylone, MCPP, Mexedrone, NM-2-AI, Tramadol | 29 |
| `snris` | SNRIs | none | 0 |
| `ssris` | SSRI, SSRIs | none | 0 |
| `stimulants` | Stimulants | category stimulant; class Stimulant(s) | 80 |
| `substituted-amphetamines` | Amphetamines, Substituted amphetamines | chemical class Amphetamine, Substituted amphetamines; Amphetamine, Dextroamphetamine | 36 |
| `tricyclic-antidepressants` | Tricyclic antidepressants | Tianeptine (an atypical tricyclic) | 1 |

**Members a class or category misses.** The catalog was searched (names, aliases, API classes, base categories and base text) for substances a rule should hold and does not. Chlordiazepoxide and Cinolazepam (base-only benzodiazepines without the category), Tilidin (a base-only opioid without any category), Ethylone and Mexedrone (entactogenic cathinones in the entactogen category whose API classes lack Entactogen) are named in their groups. The first search missed Mexedrone; the review found it.

**MAOIs.** No API class or base category marks an MAOI, so the group is a list of names. The search covered harmala alkaloids (harmine, harmaline, Syrian rue or Peganum harmala, Banisteriopsis caapi) and pharmaceutical MAOIs (moclobemide, selegiline, phenelzine, tranylcypromine, isocarboxazid, rasagiline, linezolid, methylene blue). None of these is in the catalog except Ayahuasca, which contains harmala alkaloids. The search then covered research chemicals that are MAO inhibitors: αMT, PMA and PMMA are documented MAO-A inhibitors (a main reason PMA and PMMA kill when taken with MDMA), and before this rule PMMA had no warning with the 38 substances that list MAOIs as dangerous and αMT none with 21. Bromo-DragonFLY potently inhibits MAO-A and resists hepatic metabolism (Noble et al., Toxicology Letters 2018, "Bromo-dragonfly, a psychoactive benzodifuran, is resistant to hepatic metabolism and potently inhibits monoamine oxidase A"); the first two searches missed it and the review found it, and adding it made 77 pairs dangerous (58 from uncertain, 11 from no warning, 8 from unsafe) while lowering or removing none. The base summary of 2C-T-7 calls it a "possible MAOI". All five are included, because a missed MAOI warning is the unsafe direction. Considered and left out, because they are not MAO inhibitors at the doses taken or nothing in the data says so: MDMA, Amphetamine, Methamphetamine and 4-FA (at most weak MAO inhibition in the literature, and they are releasers, already reached through `serotonin-releasers` and `substituted-amphetamines`), Myristicin and 2C-T-2 (weak inhibitors in the literature only), Nicotine (the inhibitors are β-carbolines in tobacco smoke, not nicotine), and DMT, 5-MeO-DMT and Bufotenin (substrates of MAO, not inhibitors). No other alpha-methylated tryptamine (αET, 5-MeO-αMT) or 4-MTA is in the catalog. The API has entries for Peganum harmala (Syrian rue) and Banisteriopsis caapi, but without a single dose, duration or bioavailability number, so ADR 4 keeps them out of the catalog; a user who takes them can only log a custom substance, which no group reaches.

**Antihistamines.** Diphenhydramine and Promethazine are the two substances the base file calls antihistamines. Quetiapine and Mirtazapine are antihistaminic, but the data classes them as an antipsychotic and an antidepressant and no wiki class calls them antihistamines, so they are left out.

**Serotonin releasers.** The group uses the API class, not the entactogen category (accepted by the coordinator): the category also holds 2C-B, 2C-T, 2C-T-7, 4-AcO-MiPT, 5-MeO-DiPT, Ayahuasca and Psilocin, which act on receptors and release no serotonin, and 5-HTP lists Serotonin releasers as dangerous. Every substance with the entactogen category or a serotonergic description in its base text was checked. Added by name: mCPP; Ethylone and Mexedrone (above); NM-2-AI (its action is not clear); Tramadol, whose base summary calls it "a serotonin releasing agent". Considered and left out: 3-FA (its base summary says it is selective for dopamine and noradrenaline over serotonin), 2-FA, Amphetamine and Methamphetamine (dopamine and noradrenaline releasers), Cocaine, Methylphenidate, Bromantane and Nicotine (reuptake or other actions, not release), 6-APDB's agonism (it is already a member through its class), and the receptor agonists of the category listed above. Five groups are empty because no catalog substance belongs to them: SSRIs, SNRIs, protease inhibitors, ALDH2 inhibitors and hepatotoxic drugs. They are kept: the warning still shows on the substance that lists them, and a later catalog may fill them.

### The contract for the app

The app phase implements this; it is the only way the data is complete.

- The severity of a pair of two different catalog substances X and Y is the highest of: a `substance` target of X naming Y, a `group` target of X whose group has Y as a member, and the same two from Y's lists with X. Groups are therefore resolved through `members` in both directions: X lists `stimulants`, Y is a member, so logging Y while X is active warns, and so does logging X while Y is active.
- A `group` target applies to every member, including another member of the substance's own group (Alcohol and GHB both in `depressants`). A substance is never an interaction with itself: a redose is not a combination.
- Cross tolerance is an estimate built from loose wiki tokens. The app must never use it, or any tolerance estimate, to suggest a larger dose.
- A warning that comes from a broad group (`stimulants`, `depressants`, `psychedelics` and the like) names the group, for example "MDMA lists Stimulants as dangerous, and Caffeine is a stimulant", so that the user can judge it.
- An `other` target never matches a catalog substance. It is shown on the substance page and in the manual checker as text. Whether it should match a custom substance by name is open.
- The pipeline guarantees that substance pairs are symmetric and that every `groupId` exists; the invariant checks of a later slice verify both on the built dataset.

### Report and order

The findings of this ADR come after those of ADR 4: tolerance and cross tolerance tokens with each substance, in catalog order; then the cross tolerance groups; then the merge findings of each substance (missing lists, sources, conflicts), in catalog order; then resolutions and `other` targets by spelling; then symmetry; then the interaction groups by id; then own-group targets in catalog order. The same inputs give the same document and report.

### Tests

Reference cases in `tests/fixtures/normalize/` (`tolerance-*`, `cross-tolerance-*`, `interactions-*`), which may now also pin `interactionGroups` and `crossToleranceGroups`. The real base file is normalized with `tests/fixtures/api/graphql-relations.json`, the whole real API entries of fifteen substances that exercise these rules; because the base file lists interactions for all of its substances, the graph of targets, groups and pairs is real. Every rule was mutation-checked: changing it fails a test.

## Consequences

- The dataset gets 842 interaction targets that the sources do not state in that direction. Each is a finding, so the dataset review sees them.
- The tables `TOKEN_TO_GROUP`, `NAME_TO_GROUP` and `GROUPS` are hand-maintained. A new token is dropped and reported, and a new class name becomes `other` and is reported, until someone adds it.
- Groups that depend on API classes miss a substance the API does not have, or whose API classes are incomplete. The searches above found five such substances (Chlordiazepoxide, Cinolazepam, Tilidin, Ethylone, Mexedrone), now named; a new one appears only as a missing member, which no finding reports. The dataset review should look at the members of each group.
- Membership follows the categories of the base file, which are broad: `stimulants` holds Caffeine, Nicotine, Theacrine, Tyrosine, Oxiracetam, Phenylpiracetam, Benzydamine, Apomorphine and the modafinil family; `depressants` holds Bromantane, Clonidine, Datura, Ibogaine, Nicotine and Salvinorin A; `opioids` holds Naloxone (an antagonist) and Ibogaine; `psychedelics` holds Buspirone and Efavirenz. These follow the data and lean alarmist.

## Open questions for the owner

1. **Judgement calls in group membership**, each written in the code: βk-2C-B in `2c-x`; Desomorphine in `depressants`; Progesterone in `hormonal-birth-control`; Carisoprodol, Diazepam and Flunitrazepam as `cyp2c19-substrates`; Tianeptine as a tricyclic; αMT, PMA, PMMA, Bromo-DragonFLY and 2C-T-7 as MAOIs; MCPP, NM-2-AI, Ethylone, Mexedrone and Tramadol as serotonin releasers; Diphenhydramine and Promethazine as the only antihistamines. Naloxone stays in `opioids` because its category says so. Myristicin (nutmeg) and 2C-T-2 are reported in the literature as weak MAO inhibitors, but nothing in the data says so, and they are not in `maois`.
2. **Cross tolerance tokens are joined, not combined.** "Cross tolerance with dopaminergic stimulants" arrives as `dopamine` and `stimulant`, and the substance becomes a member of both groups, so the app sees cross tolerance between, for example, Tyrosine and Cocaine through `dopaminergic`. For tolerance, an overestimate is not the safe direction: a user who believes their tolerance is high may take more. The app's tolerance chart should present cross tolerance as an estimate and never suggest a larger dose.
3. **Single-member cross tolerance groups** (`deliriants`, `entactogens`, `hallucinogens`, `noradrenergic`, `tricyclic-antidepressants`) relate a substance only to itself today. They are kept so that the meaning of the token is not lost.
4. **`other` targets and custom substances**: whether the app should match an `other` name (Lithium, Grapefruit) against a custom substance the user created.
5. **Syrian rue and Banisteriopsis caapi** are not in the catalog because their API entries have no numbers. Whether they should enter the catalog without dose data, so that the MAOI warnings reach them, is the owner's decision (`ALLOWED_API_ONLY`).
6. **Gaps the sources leave** (found by the review): opioids against depressants other than benzodiazepines (barbiturates, Z-drugs, Phenibut, Promethazine, Pregabalin) give no warning in either source; this slice does not invent interactions the sources do not state.
7. **Group statements that outrank a milder specific pair**: in 43 pairs a group target gives a higher severity than the pair's own entry (for example Nitrous and Alcohol become dangerous through `depressants`). The app contract takes the highest; whether a specific statement should win is the owner's call.
8. **Buspirone carries the aliases DMT, Dimethyltryptamine and Dmitri in the base file.** Closed: all three are removed (ADR 4, "Names"), "DMT" because it is the name of another substance and the other two through `ALIAS_REMOVALS`, and the build refuses any alias that does not name exactly one substance. No warning changed.
