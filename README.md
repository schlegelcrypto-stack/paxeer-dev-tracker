# Paxeer dev tracker

A daily development tracker for the Paxeer / Sidiora ecosystem. It scrapes public
GitHub activity across the tracked accounts and writes a short briefing in plain
English first, technical detail underneath.

Built for the Gideon App Store: install it, and Gideon runs it every day.

## What it reports

- **Build progress first.** Merged work-lane names from the main repository's recent
  commits, the task board, the qualification ledger, and open PR counts.
- **Plain-English lead.** A few sentences anyone in the community can read.
- **Labels on every claim.** `[verified]` retrieved this sweep · `[reported]` team
  claim, unverified. The ladder built / deployed / live / gated / confirmed on chain
  is never collapsed.
- **Watch list** — gateways returning 200, a clean qualification run on a tagged
  revision, deploy lanes increasing, the first published container image, new repos.

## Method traps this handles

- **Renames.** `Paxeer-X-Network` was renamed twice (`LayerX-Protocol` →
  `LayerX-Network`). Old names return a redirect object and parsers read zero. The
  tracker resolves the current name from the org listing every sweep and marks any
  zero as suspect before reporting it.
- **Org vs user endpoints.** Two tracked accounts are orgs, six are users. The wrong
  endpoint silently returns an empty list.
- **PR counts.** The rendered `/pulls` page caps at 25; counts come from the search API.
- **Ledger arithmetic.** Gate outcomes are counted per record and checked against the
  gate total.
- **Rollup headers.** 8 of the board's `[ ]` lines are wave headers, not tasks. Both
  counts are printed.
- **SPA 200s and wildcard DNS.** Endpoint checks compare against a nonsense-path
  control before calling a route live.

## Run it

```bash
python3 run.py pull     # quick sweep
python3 run.py full     # every tracked account
python3 run.py brief    # render the brief from saved snapshots
python3 run.py all      # full sweep + brief (what the daily run executes)
python3 -m unittest discover -s tests -v
```

`GITHUB_TOKEN` in the environment raises the rate limit (anonymous is 60 req/hr).
**No token is ever written to this repository** — key names only, values in the
environment.

## Install in Gideon

`app.json` is the manifest. Install from the Gideon App Store, then the daily
automation runs `python3 run.py all` and delivers the brief.

Once installed it registers three agent tools:

- `paxeer_sweep` — pull fresh state from the public GitHub API, save the
  snapshot, and return the briefing (`mode: "quick"` ~10s or `mode: "full"` ~50s).
- `paxeer_brief` — render the briefing from the last saved snapshots with no
  network call.
- `paxeer_sources` — show the watchlist in effect (accounts, websites, repos),
  where it was fetched from, and how to extend it.

## Extending the watchlist

The tracked accounts, websites and repos are **data, not code**: one canonical
[`sources.json`](./sources.json), fetched at run time by every install. To add a
developer account, a website, or a repo to watch:

1. Edit `sources.json` — one entry, e.g. `{"login": "new-dev", "kind": "user"}`.
2. Bump `version`.
3. Commit (or open a PR) on `main`.

Every install fetches that file on its next sweep — the change reaches all users
without a re-install, and each brief stamps which watchlist version produced it
(`[verified]` when fetched from the canonical URL, `[reported]` on fallback), so a
watchlist change can never silently explain a diff. Resolution order: canonical
URL → last-fetched cache → bundled copy. The file is strictly schema-validated
(unknown keys rejected): it can widen what is watched, nothing more.

## Scope and ethics

Public data only: public GitHub endpoints and public HTTPS status checks. The
operator's own accounts are excluded from ecosystem intel by design. Nothing here
touches credentials, private repositories, or unpublished material — anything about
repository security findings goes privately to the team, never into a public brief.

## Licence

MIT.
