# 2. Extraction and the raw snapshot

- Status: accepted
- Date: 2026-11-16

## Context

The spec (`Application/docs/SPEC.md`, "Substance dataset") names the sources of the extraction step: the PsychonautWiki GraphQL API and, where it is stale, the wiki itself through the MediaWiki API. The repository rules add that network access happens only in the extraction step and that tests never touch the network. The spec does not say what extraction stores, how it behaves towards the services, or what it does when they change.

## Decision

### One command, one client

`zadrya-data fetch --output <dir>` is the only command that uses the network. Every request goes through one client (`PoliteClient`): at least one second between requests, a 30 second timeout, at most three attempts on a timeout or a 5xx answer, no redirects followed. It identifies itself as `dataset-builder/<package version>` and sends nothing that names a person or the project. A fetch takes nine requests today: one GraphQL query and eight wiki lookups of 50 titles.

### What is fetched

- **GraphQL**: one query for every substance (`substances(limit: 2000)`) with the fields the dataset needs. The exact query text is stored in the snapshot.
- **MediaWiki**: for every substance name of the base file and of the API, whether the wiki page exists, its title after normalization and redirects, and the id and timestamp of its last revision (`action=query`, `prop=revisions`). This is provenance, and it lets a later step see that a substance was renamed or lost its page. No page text, HTML or wikitext is read.
- **Semantic MediaWiki is not used.** The nine substances of the base file that the API does not have (Apomorphine, Bromazolam, Chlordiazepoxide, Cinolazepam, Etomidate, Oxazepam, Phenazepam, Tilidin, Triazolam) have no page on the wiki at all today, so `action=browsebysubject` returns nothing for them. For pages that do exist it returns clean per-route properties (for example `Sublingual_min_light_dose`), but those are the same data the GraphQL API serves. These nine substances therefore keep their base file data, and the wiki lookup records that their pages are missing.

### Raw means raw

The answers are checked for shape and stored as received. Null stays null, units stay as written (`Hours`, `hour`, the Greek letter mu), class and disambiguation pages without routes stay in the list, and the order of the API is kept. Every cleaning step belongs to normalization, where it is visible and tested. The typed readers fail on an unknown key, a missing key, a value of another type and a GraphQL `errors` member, so a change of either service stops the fetch instead of being read by accident. `fetch` writes nothing unless every request succeeded and every answer was understood.

### Snapshot format

A snapshot is a directory with `graphql.json` (the `data` member of the answer), `mediawiki.json` (one record per title, sorted by title) and `snapshot.json` (endpoints, the exact query, the client name, the UTC fetch date and counts). The first two are written with sorted keys, a two-space indent, UTF-8 without escapes, no `NaN` and a final newline, and carry no date, so two fetches of unchanged upstream data give the same bytes. Writing ends by reading the three files back through `strict_json` into the typed objects, so what later commands will read is what was checked. `load_snapshot` also refuses a snapshot whose counts do not match its data.

### Strict JSON everywhere

Answers of the services, snapshot files and the base file are all read through `zadrya_data.strict_json`. The base loader no longer has its own copy of those checks, which closes the follow-up noted in ADR 1.

### No real snapshot in the repository yet

The first real snapshot is committed together with the first dataset, once the owner has decided the license of the derived data. Tests use a few recorded answers, trimmed, under `tests/fixtures/api/`, with the PsychonautWiki licenses in `REUSE.toml`.

## Consequences

- Builds are offline and reproducible from a snapshot directory; only `fetch` can fail because of the network.
- A change in the shape of either service breaks `fetch` loudly and needs a code change. That is intended: the alternative is silently dropped data.
- The snapshot holds everything the API returns for the query, including 89 class and disambiguation pages and summaries that are placeholders. Normalization has to filter them.
- Byte-identical output depends on the API returning the substances in a stable order, which it did in two consecutive fetches. If that stops being true, the writer will have to sort the list, which is a small change.
