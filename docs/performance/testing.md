# Live testing setup

Local test instance on the dev machine running `integration/performance` against a copy of the production
configuration and the production media, while the NAS instance is stopped.

- NAS app stopped with `midclt call --job app.stop bazarr` (restart with `app.start bazarr`).
- `/config` copied from `/mnt/.ix-apps/app_mounts/bazarr/config` (without `backup/`, `restore/`) to
  `~/bazarr-test/data`, owned by `568:3000` like the NAS files.
- `~/bazarr-test/src`: detached worktree of `integration/performance` (so branch switches in `/opt/bazarr` don't
  change the running code) plus a copy of `frontend/build`.
- `~/bazarr-test/docker-compose.yml`: image `bazarr-perf:dev` built from `dev-setup/Dockerfile.backend`, runs as
  `568:3000` on port 30046, mounts the worktree read-only, `./data` as the config dir, `/mnt/nas-media` (NFS mount of
  the NAS media share) as `/SMB` so paths match production, and the host `/usr/share/zoneinfo` (the alpine image has
  no tzdata; without it APScheduler mixes UTC and local time and "run now" is scheduled hours later).
- Known difference from production: no `unrar` binary in the image (RAR archives from providers fail); Python 3.12
  instead of 3.14.
- `~/bazarr-test/measure.py <api key> <csv>`: every minute records Wanted job progress (items searched) and
  downloads since start from the local DB.

## A/B protocol

Run A (all new options off) and run B (FR2 + FR3 on) for 30 minutes each, both Wanted jobs triggered at the start,
provider throttles reset first. Compare items searched per hour and subtitles downloaded per hour. Run A goes first,
so run B works on a slightly harder remainder of the backlog; downloads per hour is therefore conservative for B.

## Results (2026-09-24, 30 minutes each, both Wanted jobs running)

| Run | Build / settings | Episodes searched | Movies searched | Downloads (ep + mv) |
|---|---|---|---|---|
| A | all new options off (fix branches only) | 129 | 169 | 46 + 9 = 55 |
| B | FR2 + FR3, 12 items/job, gestdown:3 opensubtitlescom:2 subdl:2 embedded:2, others 1 | 346 | 189 | 51 + 24 = 75 |
| C | B + statistics (stopped after 7 min) | 105 | 35 | 0 |
| D | B + fastest-free-provider-first ordering | 478 | 185 | 79 + 12 = 91 |
| E | D + 16 items/job, subdl:3, supersubtitles:2 | 608 | 277 | 165 + 27 = 192 |

Every run starts at the beginning of the same Wanted order, so B–E first re-search the few hundred episodes the
previous runs already searched without result; downloads per run are therefore conservative for later runs.

Findings:
- Items that find nothing must try every provider, so throughput is bounded by the slowest single provider lane.
  Statistics showed SuperSubtitles (≈6–7 s per search, built-in 2 s pause) saturating its single lane, and broken
  TVSubtitles (≈25 s per attempt on connection retries) gating runs whenever it is not throttled. Trying the fastest
  free provider first and giving SuperSubtitles/SubDL more lanes removed most of the waiting.
- Re-download bug (pre-existing, also on production: 773 of 3,893 episode/language pairs downloaded more than once):
  `save_subtitles` relabels a regular subtitle as HI when its text has HI cues, so a subtitle downloaded for a
  requirement excluding HI was saved as `.hi.srt` (overwriting the HI subtitle) and the regular requirement stayed
  missing. Parallel mode amplified it (next provider tried immediately). Fixed on `fix/exclude-hi-content-detection`
  plus a guard in FR3 that stops an item when a save doesn't satisfy its language.
