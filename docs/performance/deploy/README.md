# Running the integration build on the TrueNAS server

Deployed 2026-09-25. The TrueNAS community app `bazarr` (image `ghcr.io/home-operations/bazarr:1.6.1`) is installed
but **stopped**; a custom app `bazarr-perf` runs the `integration/performance` branch with the same config and media.

## Image
`Dockerfile.nas` builds on the exact image the community app uses (Python 3.14, unrar, entrypoint) and replaces only
`/app/bin` with the branch (version shown as `v1.6.1-perf`). The full backend test suite passes inside it (310 tests).

```bash
# in a checkout of integration/performance with frontend/build built (cd frontend && npm run build)
docker build -f docs/performance/deploy/Dockerfile.nas -t bazarr-perf:1.6.1-perf .
docker save bazarr-perf:1.6.1-perf | gzip -1 | ssh admin@192.168.1.245 'cat > /tmp/bazarr-perf.tar.gz'
# on the NAS: sudo sh -c 'gunzip -c /tmp/bazarr-perf.tar.gz | docker load'
```
The image only exists on the NAS (not published); the app uses `pull_policy: never`.

## Custom app
Created with `midclt call --job app.create` (custom app, compose mirrors the community app's rendered compose):
image `bazarr-perf:1.6.1-perf`, user/group 568, `group_add: [568]`, UMASK 002, TZ America/New_York,
`/entrypoint.sh --port 30046`, port 30046, `/mnt/Media/Media` → `/SMB`,
`/mnt/.ix-apps/app_mounts/bazarr/config` → `/config`, 8 CPU / 4 GB limits, same healthcheck.

Updating to a new build: rebuild and load the image with the same tag, then
`midclt call --job app.redeploy bazarr-perf` (or stop/start the app).

## Data
Before switching, the NAS config was backed up to
`/mnt/Apps/bazarr-backups/config-before-perf-2026-09-25.tar.gz`, then `cache`, `config`, `db`, `log` were replaced
by the local test instance's data (newest state, settings already enabled), owned 568:568.

## Rollback
`midclt call --job app.stop bazarr-perf` then `midclt call --job app.start bazarr`. No database schema changes were
made; the new settings are ignored by the stock version. To also restore the old data, extract the backup tarball
into `/mnt/.ix-apps/app_mounts/bazarr/` first.

## Verification (2026-09-25)
Connected to Sonarr/Radarr; first Wanted pass 6,631 episodes in ~10 min + 617 movies in ~2 min (OpenSubtitles quota
had just reset and Embedded re-scanned once because its ffprobe path differs in this image); second pass 9 min 18 s
with 18 provider calls. Per-item local work (DB, video preparation, cache file reads on ZFS) is slower on the NAS CPU
than on the dev machine (~3 min per cached pass there).
