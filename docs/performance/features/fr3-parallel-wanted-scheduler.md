# FR3 — Provider-aware parallel Wanted scheduler

Branch: `feature/parallel-wanted-scheduler` (from `upstream/development`; depends on the two fix branches)
Status: implemented on `feature/parallel-wanted-scheduler` (stacked on FR2 + both fix branches); unit tested,
live A/B test in progress (see `../testing.md`).
Sources: `../source/fr3-provider-aware-parallel-wanted-notes.md`, `../source/combined-spec-fr1-fr2-fr3.md` §3–§7, verified in `../research/findings-2026-09-24.md` §4.

## As implemented

- `custom_libs/subliminal_patch/provider_limits.py`: process-wide lanes per provider (`max_in_flight`, optional
  minimum interval, monotonic clock), non-blocking `try_reserve()` for the scheduler, `slot()` wrapped around every
  provider `list_subtitles` and `download_subtitle` call in `SZProviderPool`. Re-entrant per thread. Disabled (no-op)
  unless parallel Wanted is enabled, so other paths behave exactly as before.
- `SZProviderPool.list_subtitles(..., providers=None)` / async pool: search a subset of the pool's providers.
- `generate_subtitles(..., only_providers=None, video_cache=None)`: restrict to providers (forces FR2 shared
  discovery) and reuse the prepared/hashed `Video` between provider attempts.
- `bazarr/subtitles/wanted/parallel.py`: `run_parallel_wanted(handler, rows, job_id)` — ThreadPoolExecutor of
  `wanted_max_active_items` workers; each item: take the per-media lock (non-blocking, busy items retried at the end
  with a blocking wait), then loop over enabled providers it hasn't tried, reserving the first one with free
  capacity (enabled-provider order, no ranking), search only that provider, reload missing languages after a save,
  stop when nothing due is missing. Whisper fallback only after all regular providers. Adaptive search stamped once
  for the languages still missing, and only if no provider got throttled during the item. Job stops only when every
  provider is throttled. Workers pass `job_id=None` so subtitle sync is queued as its own job (bounded by
  Concurrent Jobs) instead of running inline.
- `wanted/series.py`, `wanted/movies.py`: legacy code split into `_*_due_languages`, `_search_*`, `_stamp_*_attempts`,
  `_load_*` helpers (legacy behavior unchanged) plus a handler class used by the runner. `wanted_download_subtitles*`
  (webhooks, single searches) now take the per-media lock (`bazarr/subtitles/locks.py`).
- `provider_throttle` honors `Retry-After` (seconds or HTTP-date, from a `retry_after` attribute or an HTTP error
  response), bounded 30 s – 1 day; otherwise the fixed map as before.
- Settings (Settings → Subtitles → Search → "Wanted Performance"): `wanted_parallel_enabled` (off),
  `wanted_max_active_items` (8), `provider_default_max_in_flight` (1), `provider_limits` (chips,
  `provider:requests[:ms]`). Save hook reconfigures lanes live. Per-provider limits live in the same section rather
  than Providers → Advanced (simpler; can move later).
- Tests: `tests/bazarr/test_parallel_wanted.py` (lanes, overrides, intervals, reservations, re-entrancy, runner:
  parallel items within limits, first acceptable provider, partial results, exhaustion stamping, throttled
  mid-search, all throttled, busy item retry) and Retry-After tests in `test_provider_thread_safety.py`.
- Not done: local-I/O lane beyond sync offloading, persistence batching, cancellation (the jobs queue has no cancel).

## Goal

Maximize subtitles acquired per hour, bounded only by what each provider allows. Today a large Wanted backlog moves
at roughly 10–100 items/hour; the target is to raise that by an order of magnitude or more. The real unit of work is
**requests per provider**: every provider should be kept busy up to its own limit, independently of the others.

Selection rule (decided): **the first provider that returns an acceptable subtitle (meets min score, language,
HI/forced and profile rules) wins; the item is done for that requirement.** Finding a *better* subtitle later is the
job of the existing "Upgrade previously downloaded subtitles" feature (`general.upgrade_subs`,
`general.days_to_upgrade_subs`), not of Wanted.

## Why it is slow today (verified)

- Wanted series/movies loop one item at a time (`wanted/series.py:148-162`, `movies.py:135-147`) and `break` the whole
  job once every provider is throttled.
- For each item, `SZAsyncProviderPool.list_subtitles` queries **every** enabled provider in parallel and joins on all
  of them (`core.py:733-762`); only then are candidates ranked across providers by score (`core.py:556-584`) and
  downloaded. So an item finishes only when its **slowest or timing-out provider** answers, even if a fast provider
  already had a good match. This is current Bazarr behavior, and the first thing FR3 removes.
- This is repeated per missing language (FR2 fixes that).
- Sync (ffsubsync) runs inline in the same thread; throttles use fixed cooldowns.
- `concurrent_jobs` (default 4) parallelizes *jobs*, not items (`jobs_queue.py:519-552`).

Step zero of implementation: instrument the baseline (per-provider request count/latency/errors, items/hour) so gains
are measured, not assumed.

Corrections to the source notes:
- The `RateLimiting` mixin is **dead code**: added c39e2929a, removed from sessions in 7343b1d15 (maintainer: it
  interfered with providers' own rate limiting). `DomainThrottler` has no budget reservation, uses wall-clock time,
  is keyed by domain only, and does not parse `Retry-After`. It is not usable groundwork as-is.
- Provider instances are **already shared across threads today** (Wanted job + webhook job on the same pool under
  `concurrent_jobs`); `_pools`, lazy provider init and `SZProviderPool.update` are unlocked. Existing hazard.
- Throttle state (`tp`, `throttled_count` in `get_providers.py:472-577`) is unlocked, rewritten non-atomically and
  read back with `eval()`.
- Existing bug: multi-language failed-attempt stamping rebuilds from the original `failedAttempts` each pass, so only
  the last language's stamp survives (`series.py:69-71`, `movies.py:67-69`). `providers_list` is snapshotted before
  search, so providers that fail mid-search count as "no match".
- `process_subtitle` fires sync, post-processing, Sonarr/Radarr notify, events, Plex/Jellyfin, webhook **before** the
  Wanted caller writes index/history (`processing.py:93-183`, `series.py:61-65`).
- Sync runs inline in the Wanted thread → parallel items mean parallel ffsubsync/ffmpeg.
- Whisper fallback fires when nothing was downloaded across the pool's candidates (`core.py:645-657`); in
  provider-by-provider mode it would fire after the first miss unless gated.
- No per-media locks exist anywhere. Open issue #3309 (duplicate downloads from racing jobs) is motivation.

## Prerequisite fix branches
1. `fix/adaptive-search-failed-attempts` — lost-update fix; exclude providers that errored mid-search.
2. `fix/provider-throttle-pool-thread-safety` — locks for `tp`/`throttled_count`/`_pools`/lazy init, atomic
   `throttled_providers.dat` write, replace `eval()` with a safe parser.

## Design — provider-lane scheduler

```text
Wanted coordinator
  bounded queue of lightweight item IDs (prepare/hash Video only for active items)
  provider lanes: each provider has max_in_flight + min request interval + cooldown/quota state
  loop: pair any READY item with any available, compatible provider it has not tried yet
        -> one provider lease per item at a time; many items in flight across lanes
```

Per (item, provider) attempt:
- Uses FR2 `list_candidates` + `select_best`: one listing for all of the item's remaining requirements, then
  per-requirement selection within that provider's candidates.
- **Acceptable result → download, save, done** for the requirements it satisfies; recheck cutoff; remaining
  requirements return the item to READY. No waiting on other providers.
- No acceptable result → mark provider tried for those requirements → READY for the next available provider.
- 429 / throttle / transient error → release item (provider *not* marked tried), cool the provider down honoring
  `Retry-After` (seconds or HTTP-date); other lanes keep running. Job no longer `break`s on throttles.
- Auth/config error → disable provider for this run.
- No untried compatible providers left → EXHAUSTED; stamp adaptive search once per exhausted requirement.
- FR1 pack members can complete other queued items directly.
- Whisper fallback only after genuine regular-provider exhaustion for that requirement.
- No provider ranking or rotation: whichever compatible lane is free takes the next item. Optional later: honor
  the user's provider order as a tie-break only.

Supporting pieces:
- Per-provider lanes apply to **all** entry points (wanted, manual, webhook, mass-download, upgrade) so combined
  traffic stays within limits. Conservative defaults (1 in flight) where limits are unknown; API providers
  (OpenSubtitles.com, SubDL, Gestdown) can be raised in settings. Providers with native pacing keep it.
- Per-media lock registry `(media_type, id)` across all save paths (also fixes issue #3309 class of duplicates).
- Local-I/O lane for sync, embedded extraction, hashing (bounded separately from network lanes).
- Central progress (terminal items / initial items); cancellation stops dispatch and lets saves finish;
  `scoped_session.remove()` in worker teardown.
- Legacy path untouched when the feature is off.

Persistence/side effects (only if measured contention warrants): move notify/Plex/Jellyfin/webhook after
`store_subtitles`/`history_log` and coalesce equivalent refreshes; optional writer thread batching index/history/
failed-attempt writes with real transactions (DB is AUTOCOMMIT today). Borrow mjc #3397's per-requirement attempt
rows (plus a provider dimension) if in-memory attempt tracking is insufficient.

## Settings (required)

Suggested UI: new "Wanted performance" section in Settings → Subtitles → Search; per-provider limits in
Settings → Providers → Advanced.

| Key | Type / default | Notes |
|---|---|---|
| `general.wanted_parallel_enabled` | bool, default False | off = legacy sequential Wanted with full provider fan-out |
| `general.wanted_max_active_items` | int, default 16 | bound on items in flight / prepared Video objects |
| `general.provider_default_max_in_flight` | int, default 1 | default lane width for providers without an override |
| `general.provider_limits` | list of `provider:max_in_flight[:min_interval_ms]`, default `[]` | per-provider overrides; UI table in Providers → Advanced |
| `general.local_io_max_in_flight` | int, default 1 | sync/extraction/hashing |
| `general.persistence_batching` | bool, default False | only if the writer is implemented |

Work involved: validators in `config.py`; types in `settings.d.ts`; `Check`/`Number` components in
`Subtitles/Search.tsx`; new editable table component in `Providers/Advanced.tsx`; `save_settings` hook to reconfigure
lanes live; frontend tests (`*.test.tsx` exist for these pages); backend tests. UI text should state that the first
acceptable subtitle is kept and that "Upgrade previously downloaded subtitles" finds better ones later, and that
`concurrent_jobs` caps jobs, not items or requests.

## Tests
Scheduler invariants (never two leases per item, never above max in-flight, pacing respected, throttle isolates
provider), work-item outcomes (no-match vs 429 vs auth), persistence (no SQLite lock regression, no duplicate history,
adaptive stamped once per exhausted requirement), cross-entry-point locking (manual/webhook vs wanted), cancellation.
Synthetic benchmark: fake providers 100 ms–2 s latency (one that times out), ~10k items, compare items/hour,
requests per provider, limit violations and peak memory vs the sequential baseline; then measure on the live instance.

## Upstream items to consider later
- mjc #3397 (normalized wanted state, batched failed attempts) — overlaps attempt tracking and wanted loops.
- PR #3551 (auto-translate fallback) — hooks into end of wanted functions; keep a per-item completion hook.
- Sportarr #3521/#3522 — third wanted flow and `database.py`/`scheduler.py` changes; keep scheduler media-type-generic.
- Maintainer stance: resisted parallelism (#3162, #3128); removed global limiter (7343b1d15). Defaults must equal
  legacy behavior for any upstream PR, and the PR must explain first-acceptable + upgrade semantics.
