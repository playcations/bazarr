# Only want forced subtitles for titles that have them

Branch: `feature/forced-only-when-available` (from `development`). Status: implemented, unit tested, live on the NAS.

Nothing in Sonarr, Radarr, TMDB or TVDB (v4 API: episode records only carry name/overview translations; series only
`originalLanguage`) or Gestdown says which episodes have foreign-language parts (TMDB only has show-level
`spoken_languages`; episode and season objects have no language data), so the indexer
(`subtitles/indexer/forced_evidence.py`, used by `list_missing_subtitles` for series and movies) learns it from what
is found (indexed forced subtitles, embedded or external, and forced subtitles in history) versus episodes searched
without result (`failedAttempts`):

- **Movies and episodes** with a forced subtitle keep wanting it.
- A title TMDB lists with a single spoken language, without any forced subtitle, doesn't want them (not searched).
- Otherwise every movie and episode is searched once and stops wanting forced subtitles when that search, done longer
  than `forced_evidence_grace_days` ago, found nothing. Releases leave brief or story-irrelevant foreign dialogue
  untranslated, and where no translation exists no forced subtitle exists.
- Neighbouring episodes don't decide for each other. An earlier version kept a whole series wanting forced when at
  least `forced_series_ratio` percent (25) of its checked episodes had them; that kept ~615 episodes wanted on a guess
  (The Blacklist: 66 of 218 episodes have forced, the other 152 stayed wanted) and was removed on 2026-09-27. Movies
  with several TMDB spoken languages used to stay wanted forever for the same reason.

TMDB answers are kept in the subtitles cache (`SHOW_EXPIRATION_TIME`); a TMDB error stops lookups for the current
recompute and isn't cached. Uses Bazarr's bundled TMDB key unless `general.tmdb_api_key` is set. Changing the settings
recomputes missing subtitles; code changes need a reindex (Index All Existing Episodes/Movies Subtitles).
Settings (Subtitles → Search → Performance): `forced_only_when_available` (off by default), `forced_evidence_use_tmdb`
(on), `forced_evidence_grace_days` (7; live instance uses 1), `tmdb_api_key` (optional).
How often the remaining forced requirements are retried is left to Bazarr's adaptive searching.

HI subtitles were checked as per-episode evidence (2026-09-27): HI files tag foreign speech (`[IN ITALIAN]`,
`(speaking Persian)`), 57% of HI files of episodes with forced subtitles vs 18% of the others. 65% of tagged lines are
tag only (no translation exists, or it's burned in); of the 618 episodes then wanting forced, 27 had a translated
tagged line (median 1 line), so generating forced subtitles from HI files wasn't worth building.

## Live result (2026-09-25)
Wanted episodes 6,631 → 2,800 and movies 617 → 181 after enabling (recompute took 220 s). Remaining: 1,673 episodes
and 136 movies only missing forced (titles with several spoken languages or forced evidence, e.g. Breaking Bad,
Better Call Saul, Game of Thrones), 1,127 episodes missing real subtitles. The Office, Barry, Bruce Almighty no longer
want forced subtitles.

After switching to the per-episode rule: wanted episodes 2,211 (1,084 only missing forced). Series with forced in few
episodes (Arrested Development, Ted Lasso) still want forced for episodes first searched for forced on 2026-09-25
(the legacy code didn't record forced attempts when another language was found), until the grace period passes.
