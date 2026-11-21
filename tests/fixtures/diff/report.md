# Dataset diff report

Old: old\.json

New: new\.json

> **Warning: 1 interaction(s) lowered and 1 removed. Review them first, in the Interactions section.**

## Summary

- Substances: 6 old, 6 new
- Added: 1, removed: 1, renamed: 1
- Changed numbers and units: 12
- Interactions: 1 lowered, 1 removed, 1 raised, 1 added
- Group and cross tolerance changes: 5
- Categories and texts changed: 4 (unchanged substances: 3)
- datasetVersion: 1\.0\.0 -> 1\.1\.0

## Substances

### Added

- Added \@&#8203;Drug \#&#8203;1

### Removed (never truncated)

- **Removed Drug**

### Renamed

- Old Name Drug -> New\|Name \*Drug\* &#8212; \[x\]\(y\) (the old name is an alias of the new substance)

## Doses, durations, tolerance and bioavailability

| Substance | Route | Field | Old | New | Note |
| --- | --- | --- | --- | --- | --- |
| Amphetamine | oral | dose thresholdMin | 5 mg | none | removed |
| Amphetamine | oral | dose commonMin | 10 mg | 12 mg | higher |
| Amphetamine | oral | dose strongMin | 30 mg | 35 mg | **higher (risky)** |
| Amphetamine | oral | duration onset min | 30 min | 20 min | lower |
| Amphetamine | oral | duration total max | 360 min | 420 min | higher |
| Amphetamine | oral | bioavailability max | 75 % | 80 % | higher |
| Amphetamine | insufflated | route | present | none | **removed** |
| Caffeine | oral | dose units | mg | mg caffeine | **units differ: the numbers cannot be compared** |
| Caffeine | oral | dose strongMin | 150 mg | 200 mg caffeine | units differ |
| Caffeine | all routes | tolerance half | 3 days | 5 days | changed |
| Caffeine | all routes | tolerance half min | 4320 min | 7200 min | higher |
| Caffeine | all routes | tolerance half max | 4320 min | 7200 min | higher |

## Interactions

### **LOWERED** interactions (never truncated)

| Substance | With | Old | New |
| --- | --- | --- | --- |
| Alcohol | MDMA | dangerous | unsafe |

### **REMOVED** interactions (never truncated)

| Substance | With | Old | New |
| --- | --- | --- | --- |
| Alcohol | other: Grapefruit | uncertain | none |

### Raised interactions

| Substance | With | Old | New |
| --- | --- | --- | --- |
| Amphetamine | Caffeine | uncertain | unsafe |

### Added interactions

| Substance | With | Old | New |
| --- | --- | --- | --- |
| MDMA | group depressants | none | unsafe |

## Groups and cross tolerance

| Where | Change | Substances |
| --- | --- | --- |
| interaction group stimulants | **members removed** | Caffeine |
| interaction group stimulants | members added | MDMA |
| cross tolerance group stimulants | name changed | n/a |
| cross tolerance group stimulants | members added | MDMA |
| substance MDMA | cross tolerance added | stimulants |

## Categories and texts

Only whether a field changed, never its text.

| Where | Changed |
| --- | --- |
| category depressant | description (changed) |
| category opioid | category added |
| substance MDMA | categories (changed), summary (changed), saferUse (added) |
| substance New\|Name \*Drug\* &#8212; \[x\]\(y\) | aliases (changed), url (changed) |
