# Bazarr Research Notes — Feature 1: Pack-Aware Bulk Subtitle Acquisition

## Proposed feature

When a provider returns a season pack, multi-episode pack, or full-series subtitle archive, Bazarr should be able to use that one provider result to satisfy multiple Wanted episodes instead of extracting only the episode that initiated the search.

This is **not** a request to add basic subtitle-pack support. Bazarr already has substantial provider-specific pack support. The missing orchestration is: **one downloaded pack should be able to satisfy more than one Wanted episode**.

---

## What Bazarr does today

The current Wanted-series job is episode-centric.

`bazarr/subtitles/wanted/series.py` selects episodes with missing subtitles and processes them sequentially:

```python
for i, episode in enumerate(episodes, start=1):
    ...
    wanted_download_subtitles(episode.sonarrEpisodeId, job_id=job_id)
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/wanted/series.py

That means the unit of orchestration is one Sonarr episode.

Provider code can recognize subtitle packs, but the higher-level flow still asks for subtitles one episode at a time.

---

## Existing pack support in Bazarr

A source search found explicit pack handling in multiple providers.

### SubDL

Current SubDL code has first-class state for:

```python
is_pack
is_full_season
target_episode
absolute_episode
```

The provider comments explicitly state:

> A pack covering a whole season carries no episode range: every episode of `season` is inside it.

The provider can recognize:

- episode ranges
- season packs
- full-season packs
- absolute-number anime packs
- title-only/full-series style fallback results

Relevant source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/subdl.py

However, when downloading a pack, `_extract()` still selects **one episode**:

```python
if subtitle.is_pack or subtitle.is_full_season:
    target_episode = subtitle.target_episode or subtitle.absolute_episode
    content = utils.get_subtitle_from_archive(
        archive,
        episode=target_episode,
        episode_title=subtitle.episode_title,
    )
```

If that episode is found, only that subtitle is returned to the current episode's workflow.

This is the clearest evidence that Bazarr already understands season packs but does not reuse the rest of a downloaded archive across Wanted episodes.

### SuperSubtitles

SuperSubtitles explicitly falls back from an episode lookup to a season-pack lookup:

```python
episode_subs, season_subs = self.get_subtitle_list(series_id, season, episode, video)

if episode_subs:
    sub_list = episode_subs
else:
    # episode sub may only be present in a season pack
    _, sub_list = self.get_subtitle_list(series_id, season, None, video)
```

Its download path then extracts one target episode:

```python
subtitle.content = get_subtitle_from_archive(
    archive,
    episode=subtitle.episode or None
)
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/supersubtitles.py

### Other providers with explicit pack behavior

Source searches found pack-related logic in:

- SubDL
- SuperSubtitles
- SubSource
- Titlovi
- TurkceAltyazi
- LegendasDivx
- SubF2M
- ASSRT
- SubX
- AvistaZ-family providers
- additional provider-specific archive handlers

Examples:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/subsource.py
- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/titlovi.py
- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/legendasdivx.py
- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/mixins.py

---

## Shared archive utilities already exist

`custom_libs/subliminal_patch/providers/utils.py` already contains generic archive handling:

```python
def get_archive_from_bytes(content)
def get_subtitle_from_archive(...)
def _get_matching_sub(...)
```

It supports ZIP/RAR-style archives and uses GuessIt / filename parsing plus optional episode-title matching to select one member.

Current behavior:

```python
matching_sub = _get_matching_sub(
    subs_in_archive,
    forced,
    episode,
    ...
)
```

The same parsing machinery could be extended from:

> "find the best member for one requested episode"

to:

> "enumerate every safely identifiable member and map each one to a Wanted episode."

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/utils.py

---

## Existing historical discussion

### GitHub issue #764 — "Subtitles for season packs aren't grabbed"

- https://github.com/morpheus65535/bazarr/issues/764

The maintainer explicitly stated in 2020:

> "Bazarr already look for subtitles pack (dependant of the providers of course)."

This is important because it confirms that "support season packs" is not the correct feature request framing.

That issue was about Bazarr finding a pack for a specific episode. The new proposal is different:

> Once Bazarr has a pack, use all other applicable members in that same pack to satisfy other Wanted episodes.

### GitHub issue #1629 — `legendas.tv download packs`

- https://github.com/morpheus65535/bazarr/issues/1629

Another older issue shows provider-level pack behavior was already a recurring concern.

### Existing Feature Upvote request for compressed subtitle upload

There is also an existing Feature Upvote suggestion for manually uploading compressed single-episode/season subtitles.

That is complementary but not the same feature.

The proposed feature here is automatic reuse of provider-returned archives across multiple Wanted episodes.

---

## Proposed orchestration model

When a provider returns a pack:

```text
Provider result
    |
    v
Download/access pack once
    |
    v
Enumerate subtitle members
    |
    +--> identify season/episode/language/HI/forced
    +--> map to Sonarr episode
    +--> check if requirement is Wanted
    +--> score/validate
    +--> save accepted member
    |
    v
Update every satisfied episode
```

The pack itself should not automatically confer trust on all members.

Each contained subtitle should still be validated independently.

---

## Validation requirements

For each archive member Bazarr should ideally determine:

- series identity
- season number
- episode number
- language
- forced state
- hearing-impaired state
- release/source/group metadata when available
- whether the corresponding episode is monitored
- whether that requirement is actually missing
- whether the member meets the normal score threshold
- must-contain / must-not-contain rules
- profile cutoff semantics
- upgrade rules

Partial success must be valid.

Example:

```text
S01E01 -> valid -> save
S01E02 -> valid -> save
S01E03 -> filename ambiguous -> skip
S01E04 -> valid -> save
```

E03 remains Wanted and can be searched normally later.

---

## Release matching

Pack metadata may be useful for all contained members.

Example:

```text
Video files:
Show.S01E01.1080p.WEB-DL-GROUP
Show.S01E02.1080p.WEB-DL-GROUP

Pack:
Show.S01.1080p.WEB-DL-GROUP
```

The archive-level release identity can help establish source/release-group matches for member files, while member filenames establish episode identity.

Bazarr already has pack-specific matching logic in several providers, so this should reuse existing provider metadata rather than treating all packs generically.

---

## Avoid repeated pack work

A Wanted run should track processed provider-pack IDs.

Example:

```text
Pack P satisfies E01-E19.
E20 cannot be safely matched.
```

When E20 later reaches the same provider during the same Wanted run, Bazarr should not blindly download and unpack P again unless there is a reason to retry it.

Possible in-run state:

```text
(provider, pack_id) -> processed members / unresolved members
```

This can reduce:

- repeated provider requests
- repeated download quota consumption
- repeated archive decompression
- repeated parsing

---

## Quota impact

This feature can dramatically reduce provider usage.

For a 20-episode season, current episode-centric behavior may cause:

```text
20 episode searches
possibly 20 accesses/downloads of the same pack
20 archive extraction passes
```

Pack-aware behavior can potentially reduce that to:

```text
1 pack discovery
1 pack download/access
1 archive parse
20 subtitle saves
```

For a 100-episode full-series archive, the savings can be much larger.

This is especially valuable on providers with:

- daily download quotas
- strict request limits
- scraper-style rate limits

---

## Side effects and downstream refreshes

The current `process_subtitle()` path can trigger, per successfully processed subtitle:

- Sonarr/Radarr notification
- episode/movie history updates
- Wanted UI updates
- Plex refresh
- Jellyfin refresh
- external webhook
- analytics/event tracking

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/processing.py

If a pack supplies 20 subtitles at once, emitting 20 full downstream refresh chains may be unnecessary.

An implementation should consider coalescing side effects at an appropriate scope:

- per episode
- per season
- per processing batch

The actual subtitle/history entries should still remain individual.

---

## Persistence implications

Pack-aware bulk saves create a burst of DB updates.

Potentially affected state includes:

- subtitle index rows
- `missing_subtitles`
- Wanted state
- history
- adaptive-search state

This overlaps with the persistence-manager research from the parallel-Wanted feature.

Even if this feature is implemented independently, it should avoid long-running transactions and should preserve safe ordering between file writes and database state.

---

## Safety considerations

Archive handling should avoid unsafe arbitrary extraction.

Prefer:

- reading archive members directly
- validating allowed subtitle extensions
- rejecting traversal-like paths
- limiting archive/member sizes if needed
- not extracting unrelated files to media directories

Bazarr's current provider utilities already mostly operate on archive members rather than blindly expanding archives to disk.

---

## Suggested implementation seam

A provider result could optionally expose pack metadata:

```text
SubtitlePack
    provider
    pack_id
    series identity
    season / episode range
    language metadata
    release metadata

PackMember
    filename
    member reference/content
    season
    episode
    language
    forced
    HI
```

This does not have to replace existing `Subtitle` objects.

A smaller implementation could instead let selected providers return:

```text
download_pack_members(...)
```

and let the series Wanted layer consume additional validated members after the initiating subtitle is downloaded.

---

## Relationship to other proposed features

This feature removes duplicate work **across episodes**.

It complements:

1. Multi-requirement provider searching — removes duplicate provider searches across normal/HI/forced requirements.
2. Provider-aware parallel Wanted scheduling — removes idle time across independent providers.

A logical optimization order is:

```text
pack reuse
    ->
multi-requirement search reuse
    ->
parallel provider-aware scheduling
```

The first two reduce the workload before the third parallelizes it.

---

## Succinct Feature Upvote draft

### Title

Use one subtitle pack to satisfy multiple Wanted episodes

### Description

Bazarr already recognizes season/multi-episode packs in several providers, but Wanted searching is still episode-centric. For example, SubDL supports `is_pack` / `is_full_season`, yet when a pack is downloaded Bazarr extracts only the episode that initiated the search.

If a provider returns a pack containing S01E01-S01E20, Bazarr should inspect the archive once and use every safely matchable member to satisfy other Wanted episodes.

Each member should still be validated independently against the corresponding Sonarr episode, language/HI/forced requirement, score threshold, release rules, cutoff, and monitoring state. Ambiguous or low-scoring members can simply remain Wanted.

This could turn a 20-episode season from repeated searches/downloads of the same pack into roughly one pack lookup/download plus 20 validated saves. It would reduce Wanted processing time, provider requests, archive work, and potentially download quota usage.

Bazarr already has pack-specific logic in SubDL, SuperSubtitles, SubSource, Titlovi, LegendasDivx and others, so this request is specifically about reusing the rest of an already discovered pack across episodes, not adding basic pack detection.
