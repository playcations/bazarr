# Only want forced subtitles for titles that have them

Branch: `feature/forced-only-when-available` (from `development`). Status: implemented, unit tested, live on the NAS.

Nothing in Sonarr/Radarr says whether a title has foreign-language parts, so the indexer
(`subtitles/indexer/forced_evidence.py`, used by `list_missing_subtitles` for series and movies) decides per title and
language:
1. **Evidence** — an indexed forced subtitle (embedded track or external file) or a forced subtitle in history: forced
   subtitles stay wanted.
2. **TMDB spoken languages** (series via TVDB id → `/find`, movies via TMDB id): more than one spoken language → wanted;
   a single one → not wanted. Answers are kept in the existing subtitles cache for 30 days; errors back off 10 minutes
   and aren't cached. Uses Bazarr's bundled TMDB key unless `general.tmdb_api_key` is set.
3. **No TMDB data** — not wanted once forced subtitles were first searched for the title longer than
   `general.forced_evidence_grace_days` ago (from `failedAttempts`).

The first forced subtitle indexed for a series recomputes the whole series so its other episodes want forced again.
Changing the settings recomputes missing subtitles. Settings (Subtitles → Search → Performance):
`forced_only_when_available` (off by default), `forced_evidence_use_tmdb` (on), `forced_evidence_grace_days` (7;
live instance uses 1), `tmdb_api_key` (optional). Complements `feature/forced-only-search-interval`, which only
reduces how often forced-only requirements are searched.

## Live result (2026-09-25)
Wanted episodes 6,631 → 2,800 and movies 617 → 181 after enabling (recompute took 220 s). Remaining: 1,673 episodes
and 136 movies only missing forced (titles with several spoken languages or forced evidence, e.g. Breaking Bad,
Better Call Saul, Game of Thrones), 1,127 episodes missing real subtitles. The Office, Barry, Bruce Almighty no longer
want forced subtitles.
