# Provider audit for FR1/FR2/FR3 — 2026-09-25

All providers enabled on the live instance, checked against pack/season support (FR1), multi-language listing (FR2)
and rate limits / thread safety (FR3). "Lane" = FR3 `provider_limits` entry.

| Provider | Packs / season listing | Multi-language listing | Forced / HI declared | Limits & handling | Safe with >1 in flight | Suggested lane |
|---|---|---|---|---|---|---|
| gestdown | `GET /shows/{id}/{season}/{lang}` (whole season + packs), `/season-packs` | one language per call, HI+regular together | HI only (no forced) | per-IP token bucket 200 burst / 50 per minute, 429 + Retry-After; downloads cached by Cloudflare 8 days | yes | `gestdown:4` after rework |
| opensubtitlescom | season query possible (paginated); downloads per file | yes | both | 5 req/s per IP, login 1/s, account download quota (1,000/day here) | **was no** (`self.video` race) — fixed | `opensubtitlescom:2:250` |
| subdl | packs (FR1 implemented); season-only fallback search now cached | yes | both | Retry-After handled; daily limit → midnight GMT | mostly | `subdl:3` |
| supersubtitles | native season packs; season query | page lists all languages | forced only | built-in 2 s sleep inside the lane; `find_id` uncached | yes | `supersubtitles:2` (Gestdown aggregates it for TV) |
| tvsubtitles | season page cached | scrape | neither | site failing (ConnectionError ≈25 s per attempt) | yes | disable |
| addic7ed | season ajax page (uncached) | yes | HI only | 40/day (80 VIP), cookie auth expires, IP bans; download counter race | no | disable — use Gestdown |
| embeddedsubtitles | n/a | all tracks per ffprobe | both | local only | yes | `embeddedsubtitles:4` |
| yifysubtitles | n/a (movies only) | one page, all languages | HI only | undocumented | yes | `yifysubtitles:2` |

Key findings:
- Gestdown is the Addic7ed proxy (free, no account, downloads use Gestdown's own Addic7ed accounts, no cookies,
  no personal quota) and also aggregates SuperSubtitles. Bazarr's provider made ~4 listing requests per episode
  (uncached show lookup, one call per language variant, all matching shows), slept 30 s ×3 on 423, ignored 429
  and discarded all results on a 404 for one language.
- Gestdown doesn't do forced subtitles, so it's skipped for forced-only requirements — 83% of this library's wanted
  episodes were forced-only, which is why Gestdown was barely used in the first runs.
- opensubtitlescom parsed responses against `self.video` on the shared instance: concurrent searches could score
  results against another video (effect: missed results; audit of 578 downloads found no wrong saves).

Implemented from this audit:
- `feature/gestdown-season-cache`: show cache (24 h), season listing cache (1 h, single-flight), one request per
  base language, per-episode endpoint only as fallback (misses remembered), 429/Retry-After handling, download pool
  429 → DownloadLimitExceeded, no 423 sleeps, first matching show only, throttle map entry.
- `fix/opensubtitlescom-concurrent-searches`: video passed through `query`, year-aware title search, login lock.
- `feature/subdl-season-search-cache`: season-only and title-only searches cached 1 h per parameters.
- `feature/forced-only-search-interval`: forced subtitles searched with other languages as before, but alone only
  every N days (setting), since forced subtitles rarely exist (3% of downloads here).

Not done yet: season listing reuse for opensubtitlescom and supersubtitles, supersubtitles `find_id` cache and moving
its sleep out of the lane, Gestdown season packs as FR1 candidates, a single listing for regular+HI requirements for
providers that return both (FR2).
