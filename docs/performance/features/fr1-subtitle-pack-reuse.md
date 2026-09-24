# FR1 — Subtitle pack reuse across Wanted episodes

Branch: `feature/subtitle-pack-reuse` (from `upstream/development`; phase B stacked on FR2 helpers)
Status: planned — second feature.
Sources: `../source/fr1-pack-aware-bulk-acquisition-notes.md`, `../source/combined-spec-fr1-fr2-fr3.md` §1/§7, verified in `../research/findings-2026-09-24.md` §3.

## Problem (verified)

Wanted series is episode-centric (`bazarr/subtitles/wanted/series.py:148-160`). Providers recognize packs but only
the triggering episode is used. Nothing reuses a pack across episodes, and upstream has no issue/PR for it.

Corrections to the source notes:
- **SubDL rarely downloads the archive**: searches use `unpack=1` and per-file `unpack_files` URLs
  (`subdl.py:381, 551-585`); the `_extract()` archive path is only a fallback (`:1018-1040`). Its season fallback
  search (`:427-433`) already returns members + direct URLs for other episodes → fan-out needs no archive at all.
- **SubSource already caches** archives 15 min and queries 1 h (`subsource.py:35, 247, 635-650`).
- **SuperSubtitles** sets `is_pack=True` for every subtitle (`supersubtitles.py:81`) — flag is useless there.
- Shared helpers `get_subtitle_from_archive` / `_get_matching_sub` (`providers/utils.py:46-139`) **ignore season**
  and return one member's content; no enumeration exists. Only the mixin (`mixins.py:104-111`) is season-aware.
- Pack providers inject a synthetic `episode` match (`subsource.py:97-99`, `assrt.py:177-179`,
  `legendasdivx.py:117-120`) → every member must be re-scored from its own filename.
- Blacklist is global per `(provider, id)` (`pool.py:22`); pack-wide ids (SubSource, Titlovi) blacklist every episode.
- Missing from notes: Assrt (per-file filelist), Subx, Subf2m, Subclub also handle packs.
- Mainstream providers (OpenSubtitles.com, Addic7ed, Gestdown, Embedded) have **no** pack support. Value is highest
  for SubDL/SubSource and regional providers (anime, Arabic/Persian, HU, SR/HR, TR, PT, ZH).
- For SubDL the dominant cost is the ~2–3 *searches* per episode, not downloads — fan-out saves them only because
  `wanted_download_subtitles` re-reads `missing_subtitles` from the DB per episode (`series.py:80-114`), so episodes
  filled by a pack are skipped automatically.

## Design (phased)

### Phase A — run-scoped pack cache (no behavior change)
- New bounded in-memory cache (bytes + TTL) keyed by `(provider, stable pack id, revision)`.
- Use in LegendasDivx (daily download cap), Titlovi, SuperSubtitles, TurkceAltyazi and SubDL's archive fallback.
  Keep SubSource's existing dogpile cache.
- New `enumerate_archive_members(archive) -> [Member(name, season, episode(s), language?, hi?, forced?)]` in
  `providers/utils.py`, season-aware guessit parsing, safe member reads (extension whitelist, size limits, no
  traversal, no extraction to disk).

### Phase B — cross-episode fan-out (SubDL first)
- From one SubDL listing, collect `unpack_files` members that map to other episodes of the same series id/season.
- After the triggering episode's save, for each member → `save_external_candidate(sonarr_episode_id, subtitle)`:
  - fresh eligibility: monitored, `get_exclusion_clause`, episode profile, requirement still missing, cutoff;
  - own `get_video()` for that episode, per-member re-score (`get_matches` + `compute_score`) vs its min score;
  - reuse the common save → `process_subtitle` → `store_subtitles` → `history_log` path (per-episode history);
  - skip ambiguous/absolute-vs-season-numbering conflicts (reuse `_select_unpack_entry` logic);
  - never stamp adaptive-search failures from fan-out.
- Coalesce Sonarr/Plex/Jellyfin refreshes per series/season where equivalent; keep per-subtitle history,
  post-processing and webhooks.
- Reuses FR2's `select_best`-style per-requirement copy/scoring helpers.

### Phase C (later)
More adapters (LegendasDivx, SubSource, Titlovi…), shared in-flight pack registry for FR3's parallel scheduler,
cross-item completion events.

## Settings (required)

| Key | Type / default | UI location |
|---|---|---|
| `general.pack_cache_enabled` | bool, default `True`? (Phase A is behavior-neutral) — or `False` for upstream caution | Settings → Subtitles → Search, new "Subtitle packs" section |
| `general.pack_cache_max_mb` | int, default 200 | same |
| `general.pack_cache_ttl_minutes` | int, default 60 | same |
| `general.pack_reuse_across_episodes` | bool, default `False` (Phase B) | same |

Work involved: validators in `config.py`; types in `frontend/src/types/settings.d.ts`; new `<Section>` with `Check`
+ `Number` inputs in `frontend/src/pages/Settings/Subtitles/Search.tsx` (or a new sub-page); a `save_settings` hook
to resize/clear the cache on change; frontend tests. Document supported adapters in the UI `Message`
("currently: SubDL").

## Tests
- Fixture pack fills multiple eligible episodes from one access, with correct per-episode history.
- Wrong series/season, ambiguous numbering, low score, unsupported variant, excluded/unmonitored episode → untouched.
- Episode already satisfied between pack download and save → no overwrite.
- Corrupt/unsafe archive → rejected, cache bounded and cleaned.
- Providers without enumeration → original single-result path.
- Setting off → legacy behavior.

## Upstream items to consider later
- PR #3603 (accent sanitize) changes `sanitize()`; watch if member matching uses it.
- mjc #3397 changes wanted loops/state — conflict risk in `wanted/series.py`.
- Sportarr #3522 adds `wanted/sports.py`; keep helpers media-type-generic.
