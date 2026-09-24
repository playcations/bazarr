# Live instance baseline — 2026-09-24

Read-only snapshot of the production instance (TrueNAS, container `ix-bazarr-bazarr-1`, image
`ghcr.io/home-operations/bazarr:1.6.1`, config at `/mnt/.ix-apps/app_mounts/bazarr/config` on the host).
Collected through the API and read-only SQLite queries; nothing was changed. No credentials are stored here.

## Environment
- Bazarr 1.6.1, Python 3.14.7, SQLite 3.53.4, 40 cores, Sonarr 4.0.20, Radarr 6.4.4, Jellyfin integration on.
- `multithreading` on, `concurrent_jobs` 12, adaptive search on (delay 1w, delta 1w), wanted search every 6 h.
- `minimum_score` 80 (series), 70 (movies). **`upgrade_subs` off.** Whisper fallback off, subsync off,
  post-processing off.
- Enabled providers: opensubtitlescom, supersubtitles, tvsubtitles, addic7ed, embeddedsubtitles, yifysubtitles,
  gestdown, subdl.
- One language profile: `en` forced, `en` HI, `en` HI-excluded → every episode has up to three requirements
  (`en:forced`, `en:hi`, `en`).

## Backlog
- Episodes: 6,770 of 7,352 still missing something; 7,163 have failed-attempt timestamps.
- Movies: 621 wanted.

## Throughput (history, action = downloaded)
- ~3,930 episode downloads between 2026-09-23 ~22:00 and 2026-09-24 17:00 local → **~200/hour**
  (hourly range 47–415). ~1,200 movie downloads over the same period (movie job runs in parallel as its own job).
- Series downloads by provider (24 h): gestdown 2,160, opensubtitlescom 877, subdl 519, embeddedsubtitles 126.
- Movies (24 h): opensubtitlescom 123, supersubtitles 119, subdl 32, yify 7, embedded 3.
- OpenSubtitles: 877 + 123 = 1,000 downloads, then `DownloadLimitExceeded` → the account's daily quota is 1,000.
- Log cadence: one subtitle saved every ~5–30 s, strictly one item at a time within the Wanted series job
  (e.g. ~27 s per episode for one show, ~6 s for another).

## Observed problems
- **HI mode bug in practice:** 3,698 `en:hi` vs 125 `en` and 106 `en:forced` downloads. With this profile the
  regular (HI-excluded) requirement resolves `hi_mode` from the HI item and is searched as "force HI"
  (fixed on `fix/hi-mode-profile-lookup`).
- **tvsubtitles** keeps failing with `ConnectionError`, is throttled for 10 min, then retried; while it is
  "available" every item's fan-out waits on its connection timeouts/retries (208 `retry.api` warnings: connection
  resets, 5 s retry sleeps). Classic slowest-provider stall that FR3 removes.
- **addic7ed**: 429s on 2026-09-23, now `AuthenticationError` ("cookies not valid anymore") — needs new cookies.
- **opensubtitlescom**: daily download quota hit (resets ~20:00 local).
- Many `.iso` files and a few files ffprobe cannot analyze are retried every run.

## Implications for the plan
- Providers in use are mostly non-pack (OpenSubtitles, Gestdown, Addic7ed, TVSubtitles, YIFY, Embedded); only SubDL
  and SuperSubtitles have pack logic → **FR3 before FR1**.
- FR2 applies to every episode here (3 requirements → 2 listings).
- FR3 "first acceptable subtitle wins" relies on upgrades for quality; `upgrade_subs` is currently off.
- Realistic FR3 ceiling is set by per-provider limits: Gestdown (token bucket, 429/Retry-After), SubDL (API quota),
  OpenSubtitles (1,000 downloads/day), not by Bazarr.
