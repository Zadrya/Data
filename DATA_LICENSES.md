# Data licenses

The code of this repository is GPL-3.0-or-later. The data is not ours: it comes from the sources below, each under its own terms. This file records the source address, commit and license of every external input, as [`NOTICE`](NOTICE) does in short form. The machine-readable record per file is [`REUSE.toml`](REUSE.toml), and the license texts are in [`LICENSES/`](LICENSES).

## Inputs

### PsychonautWiki Journal v11.11: `sources/base/Substances.json`

| | |
| --- | --- |
| File here | [`sources/base/Substances.json`](sources/base/Substances.json), vendored untouched |
| Repository | <https://github.com/isaakhanimann/psychonautwiki-journal-android> (archived) |
| Tag | `v11.11` |
| Commit | `73f013752cea2f05558c1ed091cdccd3dfcde62b` |
| Path in the repository | `app/src/main/assets/Substances.json` |
| Source address | <https://raw.githubusercontent.com/isaakhanimann/psychonautwiki-journal-android/73f013752cea2f05558c1ed091cdccd3dfcde62b/app/src/main/assets/Substances.json> |
| SHA-256 | `a2300bea9bf8013fc97c4279eeb7393f1800766ec55455ac117502a1208a666f` |
| Copyright | Isaak Hanimann |
| License of the repository | [GPL-3.0-or-later](https://www.gnu.org/licenses/gpl-3.0.html) |
| License of the content | PsychonautWiki content, see below |

The file is the curated starting point of the dataset. It is never edited: `tests/test_base_file.py` pins its SHA-256, and `.gitattributes` turns off line ending conversion under `sources/`.

In `REUSE.toml` the file is annotated `GPL-3.0-or-later AND CC-BY-SA-4.0 AND CC-BY-4.0`. The first part is what the repository states: its [`README.md` at that commit](https://github.com/isaakhanimann/psychonautwiki-journal-android/blob/73f013752cea2f05558c1ed091cdccd3dfcde62b/README.md), section "License", opens with "Copyright (C) 2022 Isaak Hanimann." and says the app is free software under the GNU General Public License, "either version 3 of the License, or (at your option) any later version". The other two parts are the licenses of the PsychonautWiki content the file holds.

### PsychonautWiki

The substance information in the base file was written by the contributors of [PsychonautWiki](https://psychonautwiki.org). Its terms are on the wiki page [Copyrights](https://psychonautwiki.org/wiki/Copyrights) (read on 2026-11-16, revision 145652).

| Content | License |
| --- | --- |
| Text (summaries, effects, risks, safer use advice) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| Semantic data (doses, durations, tolerance, interactions, classes) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

Both licenses require attribution, which the dataset carries in its `attribution` list and the release manifest repeats. CC BY-SA 4.0 also requires that adapted text is shared under the same license.

### PsychonautWiki API and wiki (planned inputs)

`zadrya-data fetch` reads two services, and nothing else in this repository uses the network:

| Service | Address | What is read |
| --- | --- | --- |
| GraphQL API | <https://api.psychonautwiki.org/> | Every substance with its doses, durations, tolerance, classes and interactions, in one query |
| Wiki API (MediaWiki) | <https://psychonautwiki.org/w/api.php> | For each substance name: whether the page exists, its title after redirects, and the id and timestamp of its last revision. No page text |

Their content is PsychonautWiki content under the licenses in the table above: text (for example the `summary` of the API) under CC BY-SA 4.0, semantic data under CC BY 4.0.

No snapshot of these services is committed yet: the first one lands together with the first dataset, once the license of the derived data is decided (see "Open questions"). A snapshot records its own provenance: the endpoints, the exact query, the fetch date, and the last revision of every page. Until then the only data from these services in the repository is [`tests/fixtures/api/`](tests/fixtures/api): a few recorded answers, trimmed to seven substances and eight page lookups, annotated `CC-BY-SA-4.0 AND CC-BY-4.0` in `REUSE.toml`.

## Derived data

The dataset this repository builds is derived from the inputs above. Its annotation in `REUSE.toml` is added together with the first dataset file, so that no file ever falls back to the default annotation for code.

## Open questions

These are recorded as facts to resolve, not as decisions.

1. **Text that may descend from "Disregard Everything I Say".** The [Copyrights](https://psychonautwiki.org/wiki/Copyrights) page says: "Original articles from "Disregard Everything I Say" are probably licensed for any purpose other than commercial use: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)". It also says: "Personal experience report stories and personal user information, not including semantic data, are subject to their owner's copyright" and "File contributions, including, but not limited to images, are subject to their owner's copyright; additional terms may apply". Whether any summary or safer use text in the base file descends from those original articles is not established. The base file has no key that holds experience reports or files.
2. **License of the derived dataset.** The owner decides it before the first dataset file lands in this repository. Until then no file of the dataset is committed and `REUSE.toml` has no annotation for it.
