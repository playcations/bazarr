# FR2 — Shared provider discovery (one listing per media item)

Branch: `feature/shared-provider-discovery` (from `upstream/development`)
Status: implemented on `feature/shared-provider-discovery` (stacked on `fix/hi-mode-profile-lookup`); unit tested,
needs live-instance validation.
Sources: `../source/fr2-multi-requirement-provider-search-notes.md`, `../source/combined-spec-fr1-fr2-fr3.md` §2/§7, verified in `../research/findings-2026-09-24.md` §2.

## Problem (verified)

`generate_subtitles()` (`bazarr/subtitles/download.py:69-95`) loops over every missing requirement and calls
`download_best_subtitles(languages={language})` with a **single-element set** (`:90`). The wrapper
(`custom_libs/subliminal_patch/core_persistent.py:73-74`) runs a full `pool.list_subtitles()` each time, i.e. a
complete provider fan-out per requirement.

This affects **every multi-requirement profile**, not only HI/forced variants: `{fr, en}` lists twice,
`{en, en:hi, en:forced}` up to three times. `SZProviderPool.list_subtitles` already accepts a language set and passes
it to each provider (`core.py:381, 415-452`), so providers can already batch — Bazarr just never asks them to.

The per-language loop exists for cutoff correctness (commit 2e2626ce, Nov 2022). It must stay; only listing moves out.

Expected gain: ~2–3× fewer provider listing calls for items with multiple missing requirements. No gain for
single-requirement items or upgrades (upgrade calls `generate_subtitles` one language at a time).

## As implemented

- `core_persistent.list_candidates()` + `select_best_subtitles()` (exact forced filter, per-language shallow copy of
  each candidate and its `matches`, excludes already saved `(provider, id)`), delegating to the unchanged
  `SZProviderPool.download_best_subtitles`.
- `generate_subtitles` lists **per hearing-impaired group**: regular + forced requirements share one listing, HI
  requirements share another, each listed lazily when its first requirement is resolved (so a cutoff reached earlier
  skips the HI listing entirely). Reason: providers differ in how they filter HI by requested language (addic7ed and
  YIFY filter exactly, OpenSubtitles/SubDL/Subsource return both), so one union listing cannot reproduce the legacy
  candidate set for every provider; forced is handled consistently by all audited providers, so an exact forced filter
  at selection is enough. Resulting listings: `{fr, en}` 2→1, `{en, en:forced}` 2→1, `{en, en:hi, en:forced}` 3→2.
- Requirements are resolved in profile order in shared mode (legacy path untouched).
- Setting `general.shared_provider_discovery` (default off), Settings → Subtitles → Search.
- The `hi_mode` lookup fix lives in its own branch `fix/hi-mode-profile-lookup` (`_get_hi_mode` helper).
- Tests: `tests/bazarr/test_shared_provider_discovery.py` (listing counts, identical saved subtitles vs legacy,
  forced isolation, cutoff stop in profile order, lazy HI listing, candidates not mutated),
  `tests/bazarr/test_download_hi_mode.py`.
- Not done yet: gestdown per-basename dedupe and #3585 ranking hook (only relevant once that PR lands).

## Original design notes

1. `core_persistent.py`
   - `list_candidates(video, languages, pool_instance) -> list[Subtitle]` — one `pool.list_subtitles()` for the union
     of still-missing requirements.
   - `select_best(candidates, video, language, pool_instance, min_score, hearing_impaired, use_original_format,
     fallback_allowed, exclude_ids)`:
     - filter `s.language.forced == language.forced` (pool selection filters by basename only, `core.py:562`);
     - drop ids already saved this call (`exclude_ids`);
     - shallow-copy each candidate and give it its own `matches` set (`compute_score` mutates `matches` in place,
       `score.py:122-154`; hash truncation would otherwise fail the second pass at `core.py:612-623`);
     - delegate to `pool.download_best_subtitles(candidates, ...)`.
   - Keep the existing `download_best_subtitles` wrapper unchanged for other callers.
2. `download.py::generate_subtitles`
   - Compute still-missing set once, call `list_candidates` once before the loop.
   - Keep the loop: cutoff recheck (`check_if_still_required`), per-requirement `hi_mode`, save, yield.
     The caller's `store_subtitles` between yields is what makes the cutoff recheck work — keep yield-then-recheck.
   - Deterministic requirement order: sort by profile item order (today it is set order — `_get_language_obj`
     returns a `set` and `Language.__hash__` ignores `hi`).
   - On listing error fall back to the legacy per-requirement path.
   - Fix while here: `hi_mode` lookup matches profile items on language+forced only (`download.py:80-86`); include `hi`.
3. Provider fixes needed for correctness under a union listing:
   - **addic7ed / embeddedsubtitles** return HI rows when HI is in the union; the normal requirement must filter them
     per current policy (today they never see them).
   - **gestdown** labels subtitles with the *requested* language and loops per language; dedupe by `s.id`
     (`core.py:393`) collapses copies. Make listing language-aware or dedupe per basename.
   - **opensubtitlescom** sets `self.video` inside `query` (`:304`) — fine sequentially, note for FR3.
4. Whisper fallback: keep it per requirement and only after the shared pool produced nothing acceptable for that
   requirement (`core.py:645-657`).
5. Leave room for PR #3585 (prefer embedded): selection should accept an optional candidate-ranking hook so
   "embedded first" becomes a ranking rule rather than a second pool pass.

Trade-off to handle: listing the union up front costs per-language providers (gestdown) calls that today are skipped
when cutoff is met early. Mitigation: list only requirements still missing *after* the first cutoff recheck; accept
the small cost otherwise.

## Settings (required)

| Key | Type / default | UI location |
|---|---|---|
| `general.shared_provider_discovery` | bool, default `False` (upstream-safe; enable in personal build) | Settings → Subtitles → Search, next to "Search Enabled Providers Simultaneously" |

Work involved:
- `bazarr/app/config.py`: `Validator('general.shared_provider_discovery', must_exist=True, default=False, is_type_of=bool)`.
- `frontend/src/types/settings.d.ts`: add to `Settings.General`.
- `frontend/src/pages/Settings/Subtitles/Search.tsx`: `<Check settingKey="settings-general-shared_provider_discovery">` + `<Message>`.
- Frontend test if a Search test exists; backend default test in `tests/bazarr/test_config.py` if applicable.
- No `save_settings` hook needed (read per call).

## Tests (none cover this area today)

Fake-provider unit tests (`tests/bazarr/`):
- listing called once for `{en, en:hi, en:forced}`; once for `{fr, en}`;
- forced isolation (forced candidate never satisfies normal requirement and vice versa);
- no `matches` leakage between requirements (hash-match case);
- cutoff met by first save stops second download;
- saved subtitle id never re-selected;
- Exclude HI / Force HI / default HI behave identically to legacy path;
- listing failure → legacy fallback; provider throttle handled once;
- setting off → byte-identical legacy call pattern.

## Upstream items to consider later
- PR #3585 (prefer embedded) edits the same loop — rebase conflict; design hook above.
- mjc #3384/#3397 rewrite `wanted/*` and `check_missing_languages` — conflict if merged first.
