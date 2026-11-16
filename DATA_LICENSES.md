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

The substance information in the base file was written by the contributors of [PsychonautWiki](https://psychonautwiki.org).

| Content | License |
| --- | --- |
| Text (summaries, effects, risks, safer use advice) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| Semantic data (doses, durations, tolerance, interactions, classes) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

Both licenses require attribution, which the dataset carries in its `attribution` list and the release manifest repeats. CC BY-SA 4.0 also requires that adapted text is shared under the same license.

## Derived data

The dataset this repository builds is derived from the inputs above. Its annotation in `REUSE.toml` is added together with the first dataset file, so that no file ever falls back to the default annotation for code.
