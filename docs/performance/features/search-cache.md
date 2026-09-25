# Search results cache (existing subtitles cache)

Branch: `feature/cache-settings` (from `development`). Status: implemented, unit tested, live.

Bazarr already has a persistent cache: subliminal's dogpile `region`, configured in `bazarr/init.py` with the
`SZFileBackend` (fcache files under `<config>/cache`, pickled values, 30-day default expiration). ~20 providers
already use it (OpenSubtitles title ids and tokens, Addic7ed show ids, SubSource queries and archives…), and the
**Cache Maintenance** task (`utilities/cache.py::cache_maintenance`, every 24 h) removes stale files. No separate cache
is added; everything below uses that region.

## What changed
- **Settings → Scheduler → Cache** (next to Backups): `cache.search_results_hours` (0 = off, default), cache
  retention (`cache.retention_days`, was hardcoded 14) and downloaded archives retention
  (`cache.archive_retention_days`, was hardcoded 4) used by Cache Maintenance; cache size shown with
  "Clear Search Results" and "Clear Entire Cache" actions (`GET/DELETE /api/system/cache`).
- **Generic search results reuse** (`subliminal_patch/core.py`, `search_results_cache`): every provider's answer is
  stored in the region per file (path, size, hashes), requested languages and provider settings, so a search
  already done isn't sent to the provider again until it expires. Applies to Wanted, upgrades, webhooks and new
  episodes. Manual searches and "search this language" ask the providers and refresh the cache. "Clear search
  results" bumps a generation number in the keys (keys are sha1-mangled, so no prefix delete); old entries are
  removed by Cache Maintenance. Cache hits don't take a provider lane (FR3).
- **Provider scopes stored in the same region**: Gestdown show lookups (24 h) and whole-season listings (1 h);
  SubDL season-only/title-only searches (1 h); SubDL packs kept whole for pack reuse (4 days). `get_or_create` with
  dogpile's per-key lock gives single-flight downloads. The earlier in-memory caches (`pack_cache.py`, Gestdown's and
  SubDL's private dicts) and the pack cache size/lifetime settings were removed.
- **Thread safety**: `SZFileBackend` now locks around FileCache, whose write buffer was iterated by `sync()` while
  other threads could add to it (already possible with Concurrent Jobs).

Live: first full Wanted series pass (6,631 episodes) took 25 minutes with the cache filling; see testing.md for the
second pass.

## Follow-ups from live testing
- Gestdown errors seen (connection errors, `500` on the per-episode refresh endpoint, `404` on downloads of removed
  subtitles) all also occurred on the NAS at sequential speed; no `429` rate-limit response was ever seen. They are
  Gestdown-side issues; since the rework they only fail that subtitle/episode instead of throttling the provider.
- Shows Gestdown doesn't have are remembered (not-found answers cached) instead of looked up for every episode.
- The ~270 Gestdown calls left in cached passes were downloads of subtitles rejected for hearing-impaired content
  (HI-excluded requirement). Rejections are now remembered in the cache (`hi_content.<provider>.<id>`), so they aren't
  downloaded again.
- Buffered cache writes are flushed every 100 entries / 60 s, at exit and on shutdown/restart.

Result: consecutive full Wanted series passes (6,631 episodes): 25 min cold, then under 3 minutes with 1 provider call.
