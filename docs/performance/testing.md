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
