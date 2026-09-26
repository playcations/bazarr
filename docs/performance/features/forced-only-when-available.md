# Only want forced subtitles for titles that have them

Branch: `feature/forced-only-when-available` (from `development`). Status: implemented, unit tested, live on the NAS.

Nothing in Sonarr, Radarr, TMDB or TVDB (v4 API: episode records only carry name/overview translations; series only
`originalLanguage`) or Gestdown says which episodes have foreign-language parts (TMDB only has show-level
`spoken_languages`; episode and season objects have no language data), so the indexer
(`subtitles/indexer/forced_evidence.py`, used by `list_missing_subtitles` for series and movies) learns it from what
is found (indexed forced subtitles, embedded or external, and forced subtitles in history) versus episodes searched
without result (`failedAttempts`):

- **Movies**: wanted if the movie has a forced subtitle, else if TMDB lists more than one spoken language, else until
  forced subtitles were first searched longer than `forced_evidence_grace_days` ago.
- **Episodes**: an episode of a series TMDB lists with a single spoken language and without any forced subtitle
  doesn't want them. Otherwise every episode is searched once (and gets the grace period); after that, an episode
  without forced subtitles keeps wanting them only if the series needs them throughout: at least 4 checked episodes
  and at least `forced_series_ratio` percent (default 25) of them have forced subtitles. Library data: 95 series have
  forced subtitles; 35 have them in 50%+ of episodes (Pachinko, Game of Thrones 67%), Better Call Saul 43%, Breaking
  Bad 37%, while 22 have them in under 10% (Ted Lasso, Atlanta, Arrested Development: 1 episode out of 41–84).
- A forced subtitle in one episode doesn't make the whole series want them (an earlier version did).

TMDB answers are kept in the existing subtitles cache for 30 days; errors back off 10 minutes and aren't cached. Uses
Bazarr's bundled TMDB key unless `general.tmdb_api_key` is set. Changing the settings recomputes missing subtitles.
Settings (Subtitles → Search → Performance): `forced_only_when_available` (off by default), `forced_evidence_use_tmdb`
(on), `forced_evidence_grace_days` (7; live instance uses 1), `forced_series_ratio` (25), `tmdb_api_key` (optional).
Complements `feature/forced-only-search-interval`, which only reduces how often forced-only requirements are searched.

## Live result (2026-09-25)
Wanted episodes 6,631 → 2,800 and movies 617 → 181 after enabling (recompute took 220 s). Remaining: 1,673 episodes
and 136 movies only missing forced (titles with several spoken languages or forced evidence, e.g. Breaking Bad,
Better Call Saul, Game of Thrones), 1,127 episodes missing real subtitles. The Office, Barry, Bruce Almighty no longer
want forced subtitles.

After switching to the per-episode rule: wanted episodes 2,211 (1,084 only missing forced). Series with forced in few
episodes (Arrested Development, Ted Lasso) still want forced for episodes first searched for forced on 2026-09-25
(the legacy code didn't record forced attempts when another language was found), until the grace period passes.
