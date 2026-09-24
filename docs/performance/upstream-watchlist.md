# Upstream watchlist — PRs/issues to consider later

Snapshot: 2026-09-24 against `upstream/development` @ 7448b2a7d. Not blocking current work; revisit before each
upstream PR and when rebasing the integration branch.

| Item | Touches | Affects | Action when revisited |
|---|---|---|---|
| mjc #3383 test/CI foundation | tests harness, CI, `language_utils` | all | Optional: cherry-pick transactional test fixtures (credit mjc). Full suite has order-dependent settings pollution. |
| mjc #3384 wanted/adaptive hardening | `wanted/*`, `adaptive_searching.py` | FR2, FR3 | Characterization tests are useful; conflicts with our wanted-loop edits. |
| mjc #3385/#3386/#3388 | mass-download, API, sync, upgrade | — | Orthogonal. |
| mjc #3387 manual/upload | `processing.py` guards, `download.py` (obsolete `hi_required` hunk) | FR1 | Hand-take processing guards if needed. |
| mjc #3397 (draft) normalized wanted state | new tables + migration, `wanted/*`, `download.py`, indexers, adaptive | FR3 (attempt tracking), FR2 (`check_missing_languages`) | Not ported (12 conflicts, Alembic fork vs 537e9b4d10e3, broken test import). Borrow design; re-evaluate if merged upstream. |
| #3585 prefer embedded | `download.py` per-language loop, `pool.py` | FR2 | FR2 selection exposes a ranking hook so this becomes a rule. |
| #3551 auto-translate fallback | `wanted/*`, `database.py` profile, migration | FR3 | Keep per-item completion hook. Maintainer asked questions 08-30. |
| Sportarr #3521/#3522 (base `sportarr`) | `database.py`, `scheduler.py`, new `wanted/sports.py`, media_type branches | all | Keep helpers media-type-generic. |
| #3603 accent sanitize | `sanitize()` | FR1 (matching) | Watch. |
| #3584, #3414, #3087 | provider-internal | — | Ignore. |
| Issue #3309 (open) | duplicate downloads from racing jobs | FR3 | Motivation for media locks. |
| Issues #3274/#3225/#3159 | SQLite "database is locked" | FR3 stage 3 | Evidence for persistence work. |
| #3162, #3128 (closed) | maintainer rejected/held parallelism | FR3 | Defaults = legacy; pitch as opt-in. |
| 7343b1d15 | removed global rate-limit mixin | FR3 | Per-provider opt-in limits only. |

Process reminder (CONTRIBUTING.md): discuss features on Discord before upstream PRs; disclose AI assistance;
validate on a live instance with real data across Python 3.10–3.13.
