# 2. Extraction and the raw snapshot

- Status: accepted
- Date: 2026-11-16

## Context

The spec (`Application/docs/SPEC.md`, "Substance dataset") names the sources of the extraction step: the PsychonautWiki GraphQL API and, where it is stale, the wiki itself through the MediaWiki API. The repository rules add that network access happens only in the extraction step and that tests never touch the network. The spec does not say what extraction stores, how it behaves towards the services, or what it does when they change.

## Decision

### One command, one client

`zadrya-data fetch --output <dir>` is the only command that uses the network. Every request goes through one client (`PoliteClient`): at least one second between requests, a 30 second timeout per read, at most three attempts on a timeout or a 5xx answer, no redirects followed. It identifies itself as `dataset-builder/<package version>` and sends nothing that names a person or the project. A fetch takes nine requests today: one GraphQL query and eight wiki lookups of 50 titles.

The client cannot be steered or stalled from outside:

- Proxy and certificate variables of the environment are ignored (`trust_env` is off), so they cannot reroute requests or change the trust store.
- An answer is read while it streams and dropped beyond 8 MB (the real answers are under 1 MB).
- One request has an overall deadline of 120 seconds, so an answer that drips in slowly counts as a timeout instead of hanging.
- `Retry-After` on a 503 is honoured when it is a number of seconds up to 60. Beyond 60 the fetch fails instead of waiting. Other forms of the header are ignored and the usual interval applies.

### What is fetched

- **GraphQL**: one query for every substance (`substances(limit: 2000)`) with the fields the dataset needs. The exact query text is stored in the snapshot.
- **MediaWiki**: for every substance name of the base file and of the API, whether the wiki page exists, its title after normalization and redirects, and the id and timestamp of its last revision (`action=query`, `prop=revisions`). This is provenance, and it lets a later step see that a substance was renamed or lost its page. No page text, HTML or wikitext is read.
- **Semantic MediaWiki is not used.** The nine substances of the base file that the API does not have (Apomorphine, Bromazolam, Chlordiazepoxide, Cinolazepam, Etomidate, Oxazepam, Phenazepam, Tilidin, Triazolam) have no page on the wiki at all today, so `action=browsebysubject` returns nothing for them. For pages that do exist it returns clean per-route properties (for example `Sublingual_min_light_dose`), but those are the same data the GraphQL API serves. These nine substances therefore keep their base file data, and the wiki lookup records that their pages are missing.

### Raw values, one deliberate order

The answers are checked for shape and every value is stored as received. Null stays null, units stay as written (`Hours`, `hour`, the Greek letter mu), and class and disambiguation pages without routes stay in the list. Every cleaning step belongs to normalization, where it is visible and tested.

One thing is not kept: the order of the substances. The order of the API is an artefact of its backend (`1,3-Butanediol, 1P-ETH-LAD, 1cP-MiPLA, 1cP-AL-LAD, 1B-LSD, ...`) and nothing promises that it stays the same, so byte-identical snapshots could not depend on it. The writer orders the substances by name in code point order: plain comparison of the Unicode code points of the name, with no locale and no case folding, so digits come first, then capitals, then lower case, then letters outside ASCII. Wiki page records are ordered by requested title in the same way. Lists inside a substance (routes, interactions, names) keep the order of the API.

The typed readers fail on an unknown key, a missing key, a value of another type and a GraphQL `errors` member, so a change of either service stops the fetch instead of being read by accident. They also refuse answers that would be stored wrongly without anyone noticing:

- GraphQL: an empty list, a list as long as the limit of the query (2000, which may be a truncated answer), an empty name, two entries with the same name.
- MediaWiki: two pages with the same title, a page nobody asked for, a missing page that has an id or revisions, a namespace other than 0, ids that are not positive, a timestamp that is not ISO 8601 UTC, a redirect chain that does not end. A title with a pipe is refused before anything is sent, because the pipe separates titles.

### Snapshot format

A snapshot is a directory with exactly three files:

- `graphql.json`: the `data` member of the answer.
- `mediawiki.json`: one record per title.
- `snapshot.json`: the endpoints, the exact query, the client name, the UTC fetch date, the names of the base file that were looked up, counts, and the SHA-256 of the other two files.

The first two are written with sorted keys, a two-space indent, UTF-8 without escapes, no `NaN` and a final newline, and carry no date, so two fetches of unchanged upstream data give the same bytes.

**Writing is all or nothing.** The three files are written into a temporary directory next to the destination, read back through `strict_json` into the typed objects, and only then moved into place. If anything fails before that, an existing snapshot is untouched; if the move itself fails, the previous snapshot is put back. `fetch` writes nothing unless every request succeeded and every answer was understood. A destination that holds anything other than snapshot files is refused, so a wrong `--output` can never delete unrelated files. The move is two renames, not one atomic step: a crash exactly between them leaves the previous snapshot in a hidden sibling directory, which is the one case that needs a hand. The hidden siblings are named `.<name>.new-<pid>` and `.<name>.old-<pid>`. Once a snapshot is committed to this repository, its parent directory needs a `.gitignore` line for them (`.*.new-*` and `.*.old-*`), so that a leftover can never be committed by accident; nothing is needed while snapshots live outside the repository.

The destination is checked before the first request: a symbolic link is refused (replacing it would swap the link, not the directory it points to), and so is a directory that holds anything other than snapshot files.

**Loading checks that the three files belong together**, not only that each is well formed:

- the directory holds the three files and nothing else;
- the SHA-256 of `graphql.json` and `mediawiki.json` are the ones in `snapshot.json`, so a file swapped in from another fetch is rejected even when the counts agree;
- `snapshot.json` has exactly the known keys, its counts are integers equal to what the other files contain, and its endpoints and query equal the constants in the code (a snapshot fetched with another query must be fetched again);
- a page record has positive ids and a UTC timestamp exactly when the page exists;
- substances and titles are sorted and free of repeats;
- the titles are exactly the substance names of the API and of the base file, so no name lacks a record and no record is unexplained;
- `fetchedOn` is a valid ISO date. It is not compared with the clock, so loading the same snapshot always gives the same result.

### Strict JSON everywhere

Answers of the services, snapshot files and the base file are all read through `zadrya_data.strict_json`. The base loader no longer has its own copy of those checks, which closes the follow-up noted in ADR 1.

### No real snapshot in the repository yet

The first real snapshot is committed together with the first dataset, once the owner has decided the license of the derived data. Tests use a few recorded answers, trimmed, under `tests/fixtures/api/`, with the PsychonautWiki licenses in `REUSE.toml`.

## Consequences

- Builds are offline and reproducible from a snapshot directory; only `fetch` can fail because of the network.
- A change in the shape of either service breaks `fetch` loudly and needs a code change. That is intended: the alternative is silently dropped data.
- The snapshot holds everything the API returns for the query, including 89 class and disambiguation pages and summaries that are placeholders. Normalization has to filter them.
- Byte-identical output no longer depends on the order in which the API returns the substances. It still depends on the values: any edit on the wiki changes the snapshot, as it should.
- A change of the query, of an endpoint or of the snapshot format makes older snapshots unreadable on purpose. They are cheap to fetch again.
