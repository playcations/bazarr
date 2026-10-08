# Regular subtitles made from hearing impaired subtitles

Branch: `feature/regular-from-hi` (stacked on `feature/parallel-wanted-scheduler`). Status: **merged into
`integration/performance` (2026-10-08)** after the live test below.

Acceptance criterion (user, 2026-10-05): tests pass, then a deploy and re-index show Wanted dropping by the episodes
that have an HI subtitle and want a regular one, with nothing newly wanted. Both HI and regular English stay in the
profile.

## What it does
The `hiregular` provider (Settings → Providers → "Regular From HI Subtitles", off until enabled) offers a regular
subtitle made from the video's own HI subtitle: an external file tagged `hi`/`sdh`/`cc` (next to the video or in the
custom subtitles folder), otherwise an embedded HI text track read with the Embedded Subtitles settings
(`get_providers_auth()['hiregular']['embedded_config']`, HI fallback off). It searches nothing online.

- Conversion: music markers removed before `remove_HI` (it deletes lyric lines and reads `*`/`#` as music), censored
  words (`*****`) hidden from it and restored as `#####`; afterwards the inline tags Bazarr's HI detection still finds
  (`(CHUCKLES)`, `[COUGHS, VOMITS]`) and speaker labels after formatting (`<i>DAVID: ...`, using remove_HI's own
  `HI_before_colon_caps` rule) are removed. Italics and `{\an8}` positioning are kept. A result still detected as HI is
  never offered.
- Last resort: `subliminal_patch.core.LAST_RESORT_PROVIDERS` sorts its subtitles after every other provider's, past
  the minimum score of the others; parallel Wanted only gives it a turn once every other provider was tried. A real
  regular subtitle always wins.
- Scoring: matched like embedded subtitles (`hash`, not verifiable), since it's the video's own subtitle; scoring the
  HI file name left most at 68% (no year in the name) below the 80% minimum.
- Never overwrites: nothing is offered when a non-HI file of that language or a subtitle without a language already
  exists (the result is saved as `<video>.<lang>.srt`). The HI file is not touched.
- Converted again when downloaded: the search results cache keeps listings, so the download re-reads the HI file
  instead of reusing a cached conversion. Clear cached search results after deploying a change to this provider.

## Measurements (read-only, live library)
141 episodes with both a real HI and a real regular English file:

| | Result |
|---|---|
| Offered | 140 (The Blacklist still detected as HI) |
| Real regular words present in the raw HI file | 94.37% |
| Real regular words present in the converted file | 94.32% |
| Converted words not in the real regular file | 8% (different releases' wording) |
| Lines, converted vs real | 1.05× |

The prototype's `\x00` censor placeholder made the parser merge neighbouring events; replaced by a private-use
character before these numbers were taken.

## Live test (2026-10-07/08)
Test build = integration + this branch, provider enabled, adaptive searching off for the run, then re-indexed:

| | Before | After |
|---|---|---|
| Episodes with anything missing | 627 | 437 |
| Episodes missing regular English | 301 | 117 |
| Episodes missing HI English | 401 | 401 |
| Movies with anything missing | 38 | 19 |
| Movies missing regular English | 22 | 3 |
| Newly wanted items or languages | — | none |

184 episodes and 19 movies got a regular subtitle from this provider (110 and 18 in the first round, 74 and 1 after the
scoring fix). Of the 117 episodes left, 100 are in `bazarr-no-subs` series (never searched) and 17 have no HI subtitle
(Watchmen: Motion Comic 12, Peep Show 5). 18 files first saved with speaker labels in italics were deleted and searched
again after the label fix.
