# Wanted-search performance features

Personal fast build of Bazarr with three performance features, each developed on its own branch so it can later be
proposed upstream. All options ship with defaults that preserve legacy behavior; the personal build enables them.

## Layout

| Path | Contents |
|---|---|
| `source/` | Original request/research documents, unmodified (may contain errors — see research and feature plans). |
| `research/findings-2026-09-24.md` | Verified source audit of the claims, upstream PR analysis, corrections. |
| `features/fr2-shared-provider-discovery.md` | FR2 plan: one provider listing per media item. |
| `features/fr1-subtitle-pack-reuse.md` | FR1 plan: reuse season packs across Wanted episodes. |
| `features/fr3-parallel-wanted-scheduler.md` | FR3 plan: provider-lane parallel Wanted (first acceptable subtitle wins; upgrades find better ones). |
| `upstream-watchlist.md` | Open upstream PRs/issues to reconsider later. |

Where a source document and a feature plan disagree, the feature plan (backed by the research file) wins.

## Branches

All branch from `upstream/development` (CONTRIBUTING: features branch from `development`, never `master`).

| Branch | Purpose | Upstream PR candidate |
|---|---|---|
| `docs/performance-features` | this folder | no (personal) |
| `fix/adaptive-search-failed-attempts` | multi-language failed-attempt lost update; errored providers ≠ no match | yes, small |
| `fix/provider-throttle-pool-thread-safety` | locks for throttle state/pools, atomic write, no `eval()` | yes, small |
| `feature/shared-provider-discovery` | FR2 | yes |
| `feature/subtitle-pack-reuse` | FR1 (phase B stacked on FR2) | yes, after FR2 |
| `feature/parallel-wanted-scheduler` | FR3 | yes, after Discord discussion |
| `integration/performance` | merge of all the above for personal use; rebuilt/rebased on development periodically | no |

Implementation order: fix branches → FR2 → FR1 → FR3.

## Settings summary (every feature needs UI + backend options)

| Feature | Keys | UI |
|---|---|---|
| FR2 | `general.shared_provider_discovery` | Subtitles → Search |
| FR1 | `general.pack_cache_enabled`, `general.pack_cache_max_mb`, `general.pack_cache_ttl_minutes`, `general.pack_reuse_across_episodes` | Subtitles → Search ("Subtitle packs") |
| FR3 | `general.wanted_parallel_enabled`, `general.wanted_max_active_items`, `general.provider_default_max_in_flight`, `general.provider_limits`, `general.local_io_max_in_flight`, (`general.persistence_batching`) | Subtitles → Search ("Wanted performance"), Providers → Advanced |

Per setting the work is: `Validator` in `bazarr/app/config.py`; type in `frontend/src/types/settings.d.ts`; component
in the relevant `frontend/src/pages/Settings/**` page (existing `Check`/`Selector`/`Number`, plus a new table editor
for per-provider limits); optional `save_settings` hook in `config.py` for live reconfiguration; frontend
`*.test.tsx` and backend tests.
