# Forced subtitles built from hearing impaired subtitles

Branch: `feature/forced-from-hi-subtitles` (from `development`). Status: implemented, unit tested, checked read-only
against the live library; provider disabled by default.

Hearing impaired subtitles tag foreign-language speech. When the release translates it, the translation follows the
tag (`[IN FRENCH] You called my mom.`); when it doesn't, only the tag is there (`[SPEAKING RUSSIAN]`), which means no
forced subtitle exists for that line. The `hiforced` provider (`subliminal_patch/providers/hiforced.py`, Settings →
Providers → "Forced From HI Subtitles") reads the external HI subtitle next to the video (found with Bazarr's
`search_external_subtitles`) and offers the tagged, translated lines, tags and speaker labels removed and timing kept,
as a forced subtitle in the same language. It searches nothing online.

Being a provider, it only runs during forced searches, which only happen for movies and episodes missing forced
subtitles that are still wanted, and its subtitles go through Bazarr's normal scoring (matches guessed from the HI file
name, which is named after the video), history, blacklist and upgrades. Language names come from babelfish (alpha2
languages, plus the last word of names like "Modern Greek"); the subtitles' own language is ignored
(`[IN ENGLISH] Hello.`), as is "in" without a language (`[in the kitchen]`).

Limits: external HI files only (not embedded tracks); a foreign conversation is often tagged on its first line only, so
untagged continuation lines are missed.

## Live library check (2026-09-27, read-only)
- 4,118 English HI files: forced subtitles could be built for 206 (118 episodes without forced subtitles, 88 with).
  Median 1 line per built file (73 of the 118 have a single line), max 38.
- Against the 41 episodes that have both a built and a real forced subtitle: 148 of 159 built lines (93%) are in the
  real forced subtitle, but they cover 116 of its 888 lines (13%).
- Some tagged "translations" are the original words (`Merci.`, `Ándele. Okay?`).

## Comparison with existing forced subtitles (2026-09-27)
Every movie and episode with both an English HI and a real forced subtitle (263): forced lines were built for 72; 9
were skipped because their "forced" file is really a full subtitle, leaving 63 compared. Each built line was compared
with the real forced line shown within 1.5 s (text similarity ≥ 0.6).
- First run found translated lines wrapped onto a second subtitle line were cut after the first line ("You'll" for
  "You'll have to come to Mexico."); fixed by taking whole speaker turns. Numbered speaker labels
  (`POLICE OFFICER 1:`) are removed too.
- After the fix: 278 of 319 built lines (87%) match the real forced subtitle; they cover 414 of its 1,755 lines (24%).
- The other 41 are mostly foreign words the HI file writes out as spoken (`Más café?`, `C'est la vie.`, `Da.`,
  `Saludos.`) that the real forced subtitle doesn't show, and a few short lines around untranslated scenes.
