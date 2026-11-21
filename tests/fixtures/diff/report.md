# Dataset diff report

Old: old\.json

New: new\.json

> **Review these first:**
>
> - Interactions lowered: 1
> - Interactions removed: 2
> - Members removed from interaction groups: 1
> - Groups removed: 1
> - Substances removed: 2
> - Substances renamed: 1 (Methyl Thing -> Methyl\-Thing)
> - Routes removed: 1
> - Dose units changed: 1
> - Risky dose changes: 1
> - Risky duration changes: 1
> - Tolerance values removed: 3
> - Cross tolerances removed: 2

## Summary

- Substances: 7 old, 7 new
- Added: 2, removed: 2, renamed: 1
- Changed numbers and units: 14
- Interactions: 1 lowered, 2 removed, 1 raised, 2 added
- Group and cross tolerance changes: 8
- Categories and texts changed: 5 field(s) (unchanged substances: 4)
- datasetVersion\: 1\.0\.0 \-\> 1\.1\.0

## Substances

### Removed (never truncated)

- **Old Name Drug** (possible rename\: New\|Name \*Drug\* &#8212; \[x\]\(y\) lists Old Name Drug as an alias, at another address)
- **Removed Drug**

### Renamed (never truncated)

- Methyl Thing -> Methyl\-Thing (same address)

### Added

- Added \@&#8203;Drug \#&#8203;1
- New\|Name \*Drug\* &#8212; \[x\]\(y\)

## Doses, durations, tolerance and bioavailability

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Amphetamine | oral | dose strongMin | 30 mg | 35 mg | **higher \(risky\: doses from 30 to 35 mg now show in the class below\)** |
| Amphetamine | oral | duration onset min | 30 min | 20 min | **lower \(risky\: the app shows a shorter timeline\)** |
| Amphetamine | insufflated | route | present | none | **removed** |
| Caffeine | oral | dose | units mg; commonMin 50; strongMin 150 | units mg caffeine; commonMin 50; strongMin 200 | **units differ** |
| Caffeine | all routes | tolerance zero | 7 days | none | **removed** |
| Caffeine | all routes | tolerance zero min | 10080 min | none | **removed** |
| Caffeine | all routes | tolerance zero max | 10080 min | none | **removed** |

<details>
<summary>dose thresholdMin removed: 1 row(s)</summary>

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Amphetamine | oral | dose thresholdMin | 5 mg | none | removed |

</details>

<details>
<summary>dose commonMin higher: 1 row(s)</summary>

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Amphetamine | oral | dose commonMin | 10 mg | 12 mg | higher \(note\: doses from 10 to 12 mg now show in the class below\) |

</details>

<details>
<summary>duration total higher: 1 row(s)</summary>

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Amphetamine | oral | duration total max | 360 min | 420 min | higher |

</details>

<details>
<summary>bioavailability higher: 1 row(s)</summary>

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Amphetamine | oral | bioavailability max | 75 % | 80 % | higher |

</details>

<details>
<summary>tolerance half changed: 1 row(s)</summary>

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Caffeine | all routes | tolerance half | 3 days | 5 days | changed |

</details>

<details>
<summary>tolerance half higher: 2 row(s)</summary>

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Caffeine | all routes | tolerance half min | 4320 min | 7200 min | higher |
| Caffeine | all routes | tolerance half max | 4320 min | 7200 min | higher |

</details>

## Interactions

### **LOWERED** interactions (never truncated)

| Substance | With | Old | New |
| --- | --- | --- | --- |
| Alcohol | MDMA | dangerous | **unsafe** |

### **REMOVED** interactions (never truncated)

| Substance | With | Old | New |
| --- | --- | --- | --- |
| Alcohol | other\: Grapefruit | uncertain | **none** |
| Caffeine | Old Name Drug | unsafe | **none** |

### Raised interactions

| Substance | With | Old | New |
| --- | --- | --- | --- |
| Amphetamine | Caffeine | uncertain | unsafe |

### Added interactions

| Substance | With | Old | New |
| --- | --- | --- | --- |
| MDMA | group depressants | none | unsafe |
| Caffeine | New\|Name \*Drug\* &#8212; \[x\]\(y\) | none | unsafe |

## Groups and cross tolerance

| Where | Change | Substances |
| --- | --- | --- |
| interaction group hallucinogens | **group removed** | none |
| interaction group stimulants | **members removed** | Caffeine |
| cross tolerance group stimulants | **members removed** | Caffeine |
| substance Caffeine | **cross tolerance removed** | stimulants |
| cross tolerance group stimulants | name changed | n/a |
| interaction group stimulants | members added | MDMA |
| cross tolerance group stimulants | members added | MDMA |
| substance MDMA | cross tolerance added | stimulants |

## Categories and texts

Only whether a field changed, never its text.

<details>
<summary>category description changed: 1</summary>

category depressant

</details>

<details>
<summary>category added: 1</summary>

category opioid

</details>

<details>
<summary>categories changed: 1</summary>

substance MDMA

</details>

<details>
<summary>summary changed: 1</summary>

substance MDMA

</details>

<details>
<summary>saferUse added: 1</summary>

substance MDMA

</details>
