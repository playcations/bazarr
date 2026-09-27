# Forced subtitles built from hearing impaired subtitles

Branch: `feature/forced-from-hi-subtitles` (from `development`). Status: **dropped (2026-09-27), branch deleted**.
Acceptance criterion (user, 2026-09-27): generated forced subtitles must match the real forced subtitles; the best
version covers 28% of their lines, so it stays on its branch.

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

## More inclusive rules (2026-09-27)
Goal: match real forced subtitles as closely as the HI file allows, preferring extra translated lines over missing
ones; nothing is removed to match. Measured on the 197 titles with a usable real forced subtitle (4,910 lines) plus
600 sampled titles without forced subtitles:

| Rules | Real forced lines covered | Built lines not in the real forced | Titles without forced getting one (sample) |
|---|---|---|---|
| tagged lines, alpha2 language names | 7% | 13% | 38/600 |
| + conversations (5 s, stop at another speaker) | 21% | 29% | 38/600 |
| + on-screen text for non-English originals | 26% | 28% | 61/600 |
| + 10 s conversations (default) | 28% | 33% | 61/600 |

Rejected: italics (+1–3 points, thousands of voice-over/song/phone lines); continuing after tag-only lines or across
speakers (English replies: 72% of built lines not in the real forced); on-screen text for every title (243/600 English
titles got forced subtitles for English signs).

- Language names from pycountry (Klingon, Mandarin Chinese, Yue Chinese...), the language named after the speech word
  (`[Tkuvma, in Klingon]`), a bare tag only for alpha2 languages (`[SPANISH]`, not `[MAN]`), signing counts.
- Conversations: untagged lines within `hiforced.continuation_seconds` (10) of a translated line, until a dialogue dash
  or speaker label, an own-language tag (`[IN ENGLISH]`) or an untranslated tag.
- On-screen text: lines in capitals without tags or placed at the top (`{\an8}`), unless the file writes dialogue in
  capitals, for titles whose Sonarr/Radarr `originalLanguage` (passed by the database refiner as
  `video.original_language`) isn't the subtitles' language (`hiforced.on_screen_text`).

Where the rest is (same 197 titles): 29% of real forced lines aren't in the HI file at all, 31% are in HI files that
tag no foreign speech anywhere (many are forced files that also carry English lines), 9% are over 60 s from any
foreign tag; about 7% is near a tag and still missed.

## Where it only has something to work with (2026-09-27)
Of 4,599 English HI files, 23% tag foreign speech and 6% (296) have at least one translated tag. On the 59 titles whose
HI file has translated tags and contains 80%+ of the real forced lines: 69% of real lines reproduced, 72% of generated
lines real, exact 1:1 match for 6 (10%), every real line (plus extras) for 14.

## Final round: regular subtitles and other markers
- Regular English subtitles (30 titles with a real forced subtitle): they hold about half the forced lines, but
  italics pick forced lines 1% of the time and capitals 12%; only 34 of 439 forced lines found in HI files were missing
  from the regular file, so absence isn't a signal either.
- HI markers (195 titles, 2,640 real forced lines present): foreign tag on the line 75% precise, tag within 10 s 40%,
  capitals 50% (all already used); italics, `{\an8}`, music notes and quotes ~0-1%; no ASS styles in these files. At
  least 1,500 forced lines present in HI files carry no marker at all.

Dropped: forced subtitles built from local subtitle files can't match real forced subtitles. No subtitles were ever
created by it on the live instance (provider never enabled, no history entries); all measurements were read-only.
