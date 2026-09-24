# Bazarr Wanted performance: end-to-end feature specification and research

Prepared: 2026-09-24. Expanded after reviewing the exported Markdown, the complete local FR.txt, and the pinned source snapshot.

## Implementation objective and reading guide

Deliver all three features as an integrated Wanted workflow: reuse a provider pack across eligible episodes, share discovery across compatible remaining subtitle requirements, and process multiple media items through independently limited providers. Keep required HI/SDH, forced and language behavior, existing eligibility rules, and the complete subtitle save/processing/history lifecycle. Select providers by availability and compatibility; do not add success ranking or fixed rotation.

The short posting texts are summaries. Sections 1–6 preserve research and implementation context. **Section 7 is the implementation contract**, including existing components to reuse, the full workflow, interaction rules, error handling and per-feature completion criteria. Where earlier illustrative language differs, section 7 controls. The specification is self-contained; FR.txt remains the original exported reference.

This is a researched implementation specification, not a claim that code has been implemented or tested. Provider adapters marked as retained findings still need the release-time audit described below. Unknown provider limits must remain unknown rather than being invented.

## Scope and provenance

This file accompanies three concise Feature Upvote submissions. It began as supplemental research from the referenced conversation, “Convert Addic7ed Cookies” (conversation ID 6ab43252-f234-83ea-91c6-9be76823af60), and now includes a self-contained implementation contract for all three features.

The baseline is the original long request beginning “Feature Request: Provider-aware parallel processing for Wanted subtitle searches,” produced after “well, write it up and I'll look into posting it.” The implementation contract incorporates the necessary scheduler, attempt-tracking, rate-limit, persistence and existing-concurrency requirements so implementers do not need that earlier conversation to understand the complete target.

The initial conversation retrieval truncated the final combined long-three-request message at 20,000 characters. The user's local FR.txt now supplies the complete three-request export, including the remaining parallel-scheduler design. This revision incorporates that material alongside the earlier research and fresh source checks. FR.txt remains unchanged as the original reference.

Bazarr snapshot: [ec41fe82c03ccd556d168666595bd0be1202f77b](https://github.com/morpheus65535/bazarr/commit/ec41fe82c03ccd556d168666595bd0be1202f77b), also returned as master during this check. Links below are pinned to that snapshot. Provider websites are mutable. Repository configuration is not proof of public production limits.

Evidence labels:
- **Checked**: source or official service material inspected during this task.
- **Retained finding**: a detailed finding from the earlier conversation with its source location; not independently audited in full again.
- **Proposal**: implementation guidance, not an existing feature or provider promise.

## Posting texts and character counts

Counts include spaces, punctuation and LF paragraph breaks, but exclude the title/description labels. Even CRLF line endings leave ample room under the limits.

| Request | Title characters | Description characters |
|---|---:|---:|
| 1 | 74 | 1290 |
| 2 | 89 | 1352 |
| 3 | 87 | 1839 |

### FR 1

**Title**

Reuse subtitle packs to satisfy multiple Wanted episodes from one download

**Description**

Bazarr already recognizes subtitle packs from some providers, but Wanted processing focuses on the episode that triggered the search. Other matching subtitles in the same archive could satisfy additional Wanted episodes.

Please let one season, multi-episode, or full-series pack satisfy all safely matched Wanted episodes it contains:
- Download/access the pack once and inspect its members.
- Match each member to the correct series, season and episode.
- Independently apply language, HI/SDH, forced, release-matching, score, profile and cutoff rules.
- Save valid matches, update each episode's Wanted/history state, and leave ambiguous or unsuitable members Wanted.
- Respect monitoring, exclusions, existing subtitles and upgrade rules.
- Remember processed packs during the run to avoid repeatedly downloading the same archive.
- Update queued episodes when pack members are saved, preventing duplicate searches and writes.

For example, one 20-episode season pack could fill 20 missing subtitles instead of repeatedly accessing it for individual episodes. Actual savings depend on provider behavior and quota accounting.

Providers without packs should continue normally. This concerns automatic reuse of provider results; it is separate from manually uploading a compressed season.

### FR 2

**Title**

Search each provider once per media item for all compatible missing subtitle requirements

**Description**

Bazarr processes missing subtitle requirements separately, which can repeat provider discovery for the same movie or episode: English normal, English HI/SDH and English forced, for example.

Please separate provider candidate discovery from requirement-specific selection:
- Give each provider all compatible missing requirements for the media item in one listing operation where supported.
- Use the same shared discovery when the Wanted scheduler assigns an item to a provider.
- Reuse the candidate pool, but score and filter each requirement independently.
- Preserve language matching, normal/HI/Exclude HI/forced policies, minimum scores, release filters and upgrade rules.
- After each successful save, recheck missing requirements and profile cutoff before downloading anything else.
- Handle a shared listing failure or rate-limit event once.

This must preserve the purpose of the existing per-requirement loop. Simply passing all languages into a download/scoring call with one HI mode could change results.

"Once" means one provider discovery operation, not necessarily one HTTP request: pagination, fallback lookups and language-specific APIs may still require several requests. Providers that cannot batch should retain their necessary internal calls.

This reduces duplicate requests and parsing even without parallel Wanted processing.

### FR 3

**Title**

Provider-aware parallel Wanted searches with per-provider limits and queued persistence

**Description**

Wanted movie/episode searches process media items sequentially, even when providers are searched simultaneously for the current item. Large backlogs could progress faster by using different providers for different items at the same time.

Please add a bounded Wanted scheduler:
- Keep several media items in flight, with only one active provider search per item.
- Pass all compatible remaining requirements together, and remove work satisfied by pack results.
- Assign the next available compatible provider that has not been tried for the remaining requirements; no fixed rotation or success ranking is needed.
- Track attempts per item/requirement. Requeue unresolved work, stop satisfied requirements, and recheck profile cutoff after saves.
- Enforce provider-specific concurrency, actual HTTP request rates, cooldowns and search/download quotas. Honor runtime limits and Retry-After; use conservative defaults where limits are unknown.
- Pause a throttled provider without blocking unrelated providers.
- Coordinate provider/session ownership and media locks across Wanted, manual and other search paths.
- Send persistence events through a manager that queues and batches related database writes by time or size, then triggers downstream notifications after commit.

Reserve requirements during saving/queued persistence so they cannot be dispatched twice. Stop at the first provider whose acceptable result is saved; this need not be the best result across all providers.

Preserve normal scoring, language, HI/SDH, forced and upgrade behavior. Bound memory and support orderly cancellation.

This concerns multiple items within one Wanted job, distinct from Concurrent Jobs (#3127) and provider fan-out for one item. The goal is greater throughput within each provider's limits, not multiplying the existing provider thread pools.

## 1. Pack reuse: research and implementation detail

### Existing behavior and provider groundwork

**Checked:** The series Wanted loop enumerates episodes and calls the download path for each. SubDL represents pack/range/full-season state using `is_pack`, `is_full_season`, `target_episode`, and API range/full-season metadata. Its archive extraction selects a target episode. The provider can also select an individual file exposed by the API's unpack response; therefore repeated full archive downloads are a possibility, not a claim that every provider always redownloads the same ZIP.

Sources: [bazarr/subtitles/wanted/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/series.py); [custom_libs/subliminal_patch/providers/subdl.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/subdl.py).

**Checked:** Common archive utilities already parse candidate filenames with GuessIt and select a matching member. This is a starting point for enumeration, not a ready-made bulk-save interface. SuperSubtitles has explicit pack logic. **Retained findings:** It tries season packs when episode-specific results are absent; SubSource, Titlovi, TurkceAltyazi and LegendasDivx also have provider-specific pack handling. Each adapter's metadata fidelity and archive format need an individual audit before enabling bulk reuse.

Sources: [custom_libs/subliminal_patch/providers/utils.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/utils.py); [custom_libs/subliminal_patch/providers/supersubtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/supersubtitles.py); [custom_libs/subliminal_patch/providers/subsource.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/subsource.py); [custom_libs/subliminal_patch/providers/titlovi.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/titlovi.py); [custom_libs/subliminal_patch/providers/turkcealtyazi.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/turkcealtyazi.py); [custom_libs/subliminal_patch/providers/legendasdivx.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/legendasdivx.py).

SubDL documents multi-language queries, full-season metadata and unpacked file access. Its individual-file endpoint may be preferable to downloading an entire large archive when only one member is missing. The optimization should choose an appropriate access strategy rather than mandate archive downloads. [SubDL API documentation](https://subdl.com/api-doc).

### Suggested optional provider interface

**Proposal:** Introduce an optional pack-capable result that leaves ordinary subtitle providers usable:

```text
SubtitlePack:
    provider, stable_pack_id, source/revision
    series identity, season or episode-range scope
    language/HI/forced metadata and confidence
    release metadata
    members or a lazy member-enumeration operation

PackMember:
    stable member identity, filename
    content or download reference
    season, episode(s), optional absolute episode
    language/HI/forced metadata and confidence
```

Map members to existing Sonarr episode records; do not create or assume missing media. Reuse parsing and episode-title matching where appropriate. Distinguish season numbering from absolute numbering and reject ambiguous mappings. Full-series packs may span seasons, so a triggering episode's season cannot be assigned blindly to all members.

Pack-level release group/source/resolution may inform member matching where reliable. It is evidence, not a blanket score inherited by every member. Compare each member with its corresponding media file; filenames, provider metadata and the actual library can disagree.

Partial success is essential: accept E01, E02 and E04 while leaving ambiguous E03 unresolved. Preserve individual history/provenance, blacklists, profile rules, monitoring/exclusions, scores and permitted upgrades. A pack should never bypass ordinary eligibility merely because it was found for another episode.

### Archive lifecycle and deduplication

**Proposal:** Read members safely rather than blindly extracting archive paths. Apply archive/member size limits; reject unsafe paths and unsupported/ambiguous members. Reuse decompression and parsing where practical, with bounded storage and cleanup.

Track pack identity and member outcomes for the run. Record successful, rejected, ambiguous and retryable-failure members separately. Seeing the same stable pack ID for E20 should not automatically redownload a pack already processed for E01–E19. A changed pack revision, transient failure or explicit retry can justify another attempt. Do not make a permanent negative cache that prevents later uploads or corrections from being found.

With parallel work, pack processing needs coordination beyond the triggering episode: acquire/recheck destination media ownership and missing state before each save. Another search may already have satisfied a member while the pack was downloading. Use a shared in-flight pack operation to avoid duplicate downloads by different episodes.

Coalesce series/season refreshes after saves and committed state, while retaining per-episode history. A failed member must not erase successfully saved members.

### Benefits and boundaries

A pack containing 20 useful members could replace many repeated searches/downloads with one discovery and one archive access. That is an illustrative reduction in that portion of work, not a measured 20x end-to-end speedup. Download-quota savings depend on the provider's accounting. No assumption is made that Addic7ed, OpenSubtitles or every provider offers suitable packs.

Related work:
- [Bazarr #764: season packs not grabbed](https://github.com/morpheus65535/bazarr/issues/764) is historical context for existing pack recognition, not proof of cross-episode reuse.
- [Upload compressed subtitles, single episode or season](https://bazarr.featureupvote.com/suggestions/180964/implement-upload-of-compressed-subtitles-single-episode-or-season) concerns manual uploads. Automatic reuse of provider-discovered packs is a separate workflow.

## 2. Shared provider discovery: research and implementation detail

### Why preserving the current loop's semantics matters

**Checked:** `generate_subtitles()` builds a video and loops through language requirements, checks whether each is still required, derives a per-language HI mode and invokes subtitle selection. The core download interface takes one hearing-impaired selection mode for a pass. A shared discovery pool therefore must not be resolved using one global HI preference.

Sources: [bazarr/subtitles/download.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/download.py); [custom_libs/subliminal_patch/core.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core.py).

**Checked historical reference:** [Commit 2e2626ce43dd2e364fa6b54498714c81aca20e3f](https://github.com/morpheus65535/bazarr/commit/2e2626ce43dd2e364fa6b54498714c81aca20e3f), in November 2022, fixes cutoff enforcement when searching multiple languages together. This supports preserving state-aware resolution; batching discovery is not a reason to undo that fix.

### Provider capability findings

| Provider | Candidate-discovery opportunity | Qualification |
|---|---|---|
| OpenSubtitles.com | **Checked:** Builds a comma-separated language query; forced filtering considers the requested language set. | Audit both remote parameters and local filtering so the union retains all needed variants. |
| SubDL | **Checked:** API accepts multiple languages and exposes pack/member metadata. | Pagination, unpack selection and fallback searches can still consume multiple requests. |
| Addic7ed | **Retained:** Show/season pages contain multiple languages, then rows are filtered locally. | Reuse fetched results without weakening authentication, pacing or daily tracking. |
| SuperSubtitles | **Retained:** Enumerates provider data then filters for requested languages. | Preserve provider pacing and limited HI verification. |
| YIFY | **Retained:** Movie page can enumerate multiple language candidates. | Movie-only suitability and candidate variant metadata still matter. |
| TVSubtitles | **Retained:** Episode pages contain multiple subtitle languages. | Shared page discovery does not imply support for every variant. |
| EmbeddedSubtitles | **Retained:** One container scan can discover multiple tracks. | Extraction of separate tracks remains local I/O work. |
| Gestdown | **Retained:** Subtitle API calls are language-specific. | One orchestration invocation may still make several HTTP calls. |

Code entry points:
- [custom_libs/subliminal_patch/providers/opensubtitlescom.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/opensubtitlescom.py)
- [custom_libs/subliminal_patch/providers/subdl.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/subdl.py)
- [custom_libs/subliminal_patch/providers/addic7ed.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/addic7ed.py)
- [custom_libs/subliminal_patch/providers/supersubtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/supersubtitles.py)
- [custom_libs/subliminal_patch/providers/yifysubtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/yifysubtitles.py)
- [custom_libs/subliminal_patch/providers/tvsubtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/tvsubtitles.py)
- [custom_libs/subliminal_patch/providers/embeddedsubtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/embeddedsubtitles.py)
- [custom_libs/subliminal_patch/providers/gestdown.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/gestdown.py)

### Candidate-pool contract

**Proposal:** For one media/provider pair, compute the union of still-missing compatible requirements and discover candidates once. Retain each candidate's provider identity, variant metadata and relevant release evidence. Resolve independently using validated profile/cutoff semantics. The current language collection is a set, so an established deterministic profile iteration order must not be assumed:

```text
discover(video, compatible remaining requirements)
for requirement in the validated resolution sequence:
    recheck missing state and cutoff
    filter/score shared candidates for this requirement
    download/save an acceptable candidate
    update state before resolving the next requirement
```

Example: a profile prefers French with English fallback. If saving French meets the cutoff, cached English candidates must not cause an unnecessary English download. Similarly, English normal and English HI may require different policies even though they share base-language discovery.

Keep normal, HI preference, Exclude HI and forced rules distinct. Preserve language equivalences, release restrictions, score thresholds, blacklists and upgrade rules. Treat unverifiable HI metadata according to current provider/profile policy; do not invent certainty.

Candidate caches should be scoped to the relevant media, provider, account/configuration and run. Avoid sharing mutable candidate objects if scoring mutates their state. A failed candidate download can fall through to another candidate without rerunning the entire listing unnecessarily.

A listing timeout/quota event is one provider operation failure, not one identical failure for every requested variant. A genuinely unsupported requirement should never be marked searched merely because another requirement used that provider.

Batching discovery reduces redundant work independently of parallelism. “One provider search” is an orchestration boundary, not a guarantee of exactly one network request.

## 3. Provider-limit research beyond the original long request

These are the eight providers discussed in the conversation, not an exhaustive audit of every Bazarr adapter. Distinguish: active operations, request rate, burst allowance, daily search allowance, daily download allowance, account/IP scope, and file-serving limits. One in-flight operation is a conservative proposed default, not a published provider limit.

| Provider | Evidence and limitations | Proposed initial treatment |
|---|---|---|
| OpenSubtitles.com | **Checked:** Official documentation limits login to 1 request/second; returned base_url can have different limits. Official support distinguishes API operations from generated static download URLs. A 2026 example had 50 API requests/second and a separate 6/second file-serving header; those are not universal consumer limits. | Separate login/API/file scopes and honor actual response headers and account quota. |
| SubDL Pro | **Checked:** v1 documentation lists 30,000 API requests/day and 2,000 authenticated downloads/day. /api/v1/me reports usage. The 600 requests/minute/key figure applies to paid discovery endpoints, not automatically every subtitle endpoint. | Account-wide accounting, endpoint-aware limits, runtime feedback. Key rotation must not multiply account allowance. |
| Gestdown | **Checked source defaults:** IP-partitioned token bucket: capacity 200, refill 50 each minute, server queue 2; emits 429 and Retry-After when metadata is available. Deployment configuration can override or disable settings. | Start with one operation; respect server feedback. Distinguish burst capacity from sustained refill (50/60 ≈ 0.83 tokens/sec on average, not necessarily smooth refill). |
| Addic7ed | **Retained official-page finding:** 15 anonymous / 40 registered / 80 VIP downloads per 24 hours. No verified numeric search-rate allowance. The official page was intermittently unavailable during rechecking. | Serialized operations, existing delays and backoff; verify current account allowance before hardcoding anything. |
| SuperSubtitles | **Checked Bazarr code:** multi_result_throttle = 2 seconds in its multi-result path; HI is not verifiable. No authoritative general service rate established. | Preserve existing path-specific pacing; one operation initially. This is not evidence of a universal provider-wide 2-second rule. |
| TVSubtitles | No authoritative public numeric request rate established in the prior research. | Conservative serialized operation and dynamic backoff. |
| YIFY Subtitles | No authoritative public numeric request rate established in the prior research. | Conservative serialized operation and dynamic backoff. |
| EmbeddedSubtitles | Local operations have no Internet quota. **Retained finding:** extraction timeout defaults to 600 seconds. | Separate bounded disk/CPU/extraction resources, not a network slot. |

Provider references:
- [OpenSubtitles login and base_url documentation](https://ai.opensubtitles.com/docs).
- [OpenSubtitles administrator clarification: 1/second applies to login](https://forum.opensubtitles.com/t/does-the-client-need-to-wait-after-a-successful-login/2247).
- [OpenSubtitles administrator explanation of API versus static download limits](https://forum.opensubtitles.com/t/download-rate-limit/6415).
- [SubDL v1 API, account usage and endpoint allowances](https://subdl.com/api-doc).
- [SubDL current developer documentation](https://subdl.com/developers) and [plan page](https://subdl.com/pro).
- [Gestdown backend configuration](https://github.com/Belphemur/AddictedProxy/blob/main/AddictedProxy/appsettings.json).
- [Gestdown rate-limiter implementation](https://github.com/Belphemur/AddictedProxy/blob/main/AddictedProxy/Controllers/Bootstrap/BootstrapRateLimiting.cs).
- [Gestdown backend architecture](https://github.com/Belphemur/AddictedProxy).
- [Addic7ed official download-limit page](https://www.addic7ed.com/downloadexceeded.php).
- SuperSubtitles and EmbeddedSubtitles source links appear in section 2.

Additional retained research: the prior conversation mentioned OpenSubtitles VIP's 1,000 downloads/24h allowance. That number was not reverified here; do not use it as a scheduler constant. Obtain current user/account download allowance instead. The prior Gestdown research also noted documented 423 and 429 responses; distinguish lock/unavailability from “no matching subtitle” and verify the current API contract.

Gestdown's repository describes its own database/import/refresh pipeline, including Addic7ed and SuperSubtitles sources. It should not be modeled as a direct one-request-in/one-Addic7ed-request-out proxy.

For an approximately 11,000-item backlog, multiple variants plus page/fallback requests can consume daily quotas quickly. Faster dispatch does not create more quota. Track requests and downloads separately, display remaining/reset information when available, and defer exhausted providers. Do not introduce historical-success ranking: the user's selected policy is availability plus compatibility.

## 4. Additional scheduler integration details

### Reuse the existing HTTP rate-management foundation

**Checked:** Bazarr has a `RateLimiting` mixin and a global rate tracker. `RetryingSession` inherits `CertifiSession`, without the mixin in that class declaration. Provider initialization injects `RetryingSession` into many providers. This is a promising integration point, not proof that every request across every adapter already passes through a working global limiter.

Sources: [custom_libs/subliminal_patch/http.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/http.py); [custom_libs/subliminal_patch/global_rate_limiter.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/global_rate_limiter.py); [custom_libs/subliminal_patch/providers/__init__.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/__init__.py).

**Retained finding:** The tracker is thread-safe and understands RateLimit, RateLimit-Policy and X-RateLimit headers. Audit its exact current parsing and reservation behavior before reusing it. Gate actual outgoing HTTP requests, including retries, pagination, login, fallback and downloads. Limiting provider invocations alone does not bound request rate.

Use a scope such as provider + account/IP policy + operation + host, with parent account budgets shared where required. Host-only keys can conflate login/API/CDN constraints; per-key-only budgets can incorrectly multiply an account-wide quota. Header updates and token reservations need atomic handling.

### Ownership and shared mutable state

**Retained source audit:** Pools are cached by media/profile in `_pools`; initialized providers hold sessions, tokens, cookies and mutable state. Pool updates can change providers, discarded providers, provider_configs, blacklist, ban_list, lang_equals and initialized_providers. Lazy initialization and lifecycle changes need synchronization with active work.

SubDL explicitly locks its AI-notice tracking set, but a lock on one field does not establish provider-wide thread safety. Addic7ed's local download accounting used a read/append/write cache sequence. Global provider throttle state also needs coordinated mutation and persistence.

Sources: [bazarr/subtitles/pool.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/pool.py); [custom_libs/subliminal_patch/core.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core.py); [bazarr/app/get_providers.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/get_providers.py); [custom_libs/subliminal_patch/providers/addic7ed.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/addic7ed.py); [custom_libs/subliminal_patch/providers/subdl.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/subdl.py).

**Proposal:** A provider lane owns its provider/session, or uses explicitly safe isolated instances while sharing the same global quotas. Its limits cover Wanted series, Wanted movies, manual searches and webhook work. Atomic media leases similarly span all entry points. Reconfiguration must drain or safely replace active provider instances.

Do not stack a new media executor onto the existing provider fan-out and accidentally multiply traffic. Decide explicitly how the new scheduler interacts with the existing simultaneous-provider setting. Existing scheduled-task max_instances=1 prevents overlapping copies of that task, not collisions across all search paths.

### Attempt outcomes, retries and progress

**Proposal:** Keep these outcomes distinct:

| Outcome | Scheduler action |
|---|---|
| Acceptable subtitle saved | Remove only satisfied requirements, then re-evaluate cutoff. |
| No match or all candidates below score | Mark provider completed for relevant requirements for this run. |
| One dead candidate/download | Try another suitable cached candidate where possible. |
| 429 / rate throttle | Cool down provider; do not mark the requirement permanently exhausted. |
| Transient outage | Bounded retry/backoff; release item for other eligible providers. |
| Authentication/configuration failure | Disable affected provider pending correction; avoid repeated login loops. |
| No untried eligible providers remain | Terminal exhausted outcome for this run; update adaptive search once. |

Provider attempts are normally run-scoped, because new subtitles may appear later. Update adaptive-search failedAttempts only after eligible providers for the requirement are exhausted, rather than once for every provider miss.

Prepare/refine/hash each video once while active and release it at a terminal state. Queue lightweight IDs, not 11,000 fully prepared Video objects. Bound candidate caches, archive storage, work queues and persistence queues, with backpressure when consumers fall behind.

Progress can use terminal media items / initial media items, with separate active/provider status. Cancellation stops new dispatch, allows safe save/commit boundaries, drains or records queued work and releases leases. Fair dispatch should prevent starvation without introducing provider success ranking.

### Persistence, files and side effects

The original FR already proposes a writer manager and timed/size batching. Additional detail: group logically related media changes transactionally, deduplicate events and define ordering explicitly. Illustrative flush thresholds from the discussion were 250–500 ms or 25–50 operations; these are tuning proposals, not established optimal values.

**Retained audit:** Bazarr uses thread-scoped SQLAlchemy sessions, SQLite WAL, a 60-second busy timeout and autocommit, with PostgreSQL support. A new batching manager must implement real transaction boundaries rather than assume queuing autocommitted statements makes them atomic. It also must account for existing write paths outside the new queue.

Source: [bazarr/app/database.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/database.py). [Issue #3274](https://github.com/morpheus65535/bazarr/issues/3274) documents concurrent-job database-lock failures and is closed/labeled bugfixed; it is historical evidence, not a claim that the current version remains affected.

Serialize final file changes per media item. File saves and database commits are not one atomic transaction. A crash after saving an SRT but before recording history needs idempotent recovery/reconciliation; a later index pass can rediscover a file but does not automatically restore every intended history/notification event.

Send Sonarr/Radarr notifications, Plex/Jellyfin refreshes and webhooks after committed state. Coalesce multiple variant saves into one appropriate media refresh, while preserving individual history. Source: [bazarr/subtitles/processing.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/processing.py).

Local extraction, synchronization and hashing need independently bounded CPU/disk resources. Network concurrency should not translate into unbounded simultaneous ffmpeg reads.

## 5. Validation and rollout notes

These are proposed acceptance checks, not tests executed for an implementation:

1. No media item has simultaneous provider leases, including manual/Wanted overlap.
2. Actual requests, retries and downloads respect each provider's scoped concurrency, sustained rate, burst and quota.
3. A throttled provider pauses independently; eligible work continues elsewhere.
4. Partial variant success removes only satisfied requirements; cutoff prevents unnecessary fallback downloads.
5. Normal, HI preference, Exclude HI and forced selection match existing behavior, including providers with unverifiable metadata.
6. Exhaustion updates adaptive search once; transient failures are not stored as definitive misses.
7. Provider initialization, configuration changes and session state cannot race active work.
8. A pack is downloaded once per stable identity/revision during a run; members are individually matched, with ambiguous/mismatched members skipped.
9. A pack and an individual search cannot overwrite the same subtitle concurrently.
10. File-save or database failure can be retried/reconciled without duplicate history or premature notifications.
11. Multiple variant saves coalesce downstream refreshes appropriately.
12. Cancellation, queue backpressure and shutdown preserve committed results and release ownership.
13. Providers without batching or pack support retain a working fallback.

A synthetic benchmark proposed in the discussion uses roughly six fake providers with 100 ms–2 s latency, explicit rate limits and 10,000 fake Wanted items. Compare throughput, total actual requests, duplicate archive downloads, limit violations, peak memory, persistence latency and cancellation behavior against the sequential baseline. No speedup figure has yet been measured.

The three requests remain independently useful: pack reuse reduces duplication across episodes; shared discovery reduces duplication across requirements; provider scheduling overlaps otherwise idle resources. A practical sequence is to establish safe discovery/selection boundaries and provider ownership, add pack reuse with deduplication, then scale bounded scheduling and persistence. This sequence is guidance, not a requirement to merge all features together.

## 6. Additional source map

- [bazarr/subtitles/wanted/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/series.py) — episode Wanted loop and adaptive-search path.
- [bazarr/subtitles/wanted/movies.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/movies.py) — movie Wanted loop.
- [bazarr/app/jobs_queue.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/jobs_queue.py) — top-level concurrent jobs.
- [bazarr/app/scheduler.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/scheduler.py) — scheduled task configuration.
- [Issue #3127](https://github.com/morpheus65535/bazarr/issues/3127) — top-level job-manager concurrency discussion; distinct from multiple items within one Wanted job.
- [Feature Upvote board](https://bazarr.featureupvote.com/) — posting destination.

No credentials, cookie values, personal screenshots or unrelated troubleshooting details from the original conversation are included.


## 7. End-to-end implementation contract

This section defines required outcomes; proposed class/type names are illustrative. “Must” statements are acceptance requirements for the combined feature. Reuse existing policy functions and verified behavior rather than implementing a competing set of rules.

### 7.1 Corrections and decisions from the deeper source review

1. **Discovery and selection already have separate lower-level entry points.** `SZProviderPool.list_subtitles()` and `SZProviderPool.download_best_subtitles(subtitles, ...)` exist. The persistent wrapper currently calls them together. Extend this boundary and its caller rather than invent an unrelated scoring engine. Source: [custom_libs/subliminal_patch/core_persistent.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core_persistent.py); [custom_libs/subliminal_patch/core.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core.py).
2. **Profile order is not established by the current generator.** `_get_language_obj()` returns a set. Earlier “profile order” examples describe the intended cutoff outcome, not a verified current ordering guarantee. Tests must establish compatible behavior and explicitly document any new deterministic resolution order. Reuse the real missing-state/cutoff evaluator, including audio rules, instead of substituting a simple preferred-language list. Sources: [bazarr/subtitles/download.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/download.py); [bazarr/subtitles/indexer/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/indexer/series.py); [bazarr/subtitles/indexer/movies.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/indexer/movies.py).
3. **First acceptable provider is an intentional selection-policy change.** Within the assigned provider's candidates, retain existing ranking and candidate fallback. Once an eligible result is successfully saved/committed, stop that satisfied requirement. Do not claim the selected subtitle will equal the highest-scoring result across every provider. A separate scheduled upgrade search remains available and must retain its own semantics.
4. **Adaptive searching has an existing detail to preserve or deliberately revise.** The current Wanted helpers stamp unsuccessful attempts only when no result was found for the item (`found_any` is false). Thus per-requirement exhaustion after partial success is more precise proposed behavior, not literal preservation of the existing implementation. For the new scheduler, stamp each genuinely exhausted requirement once per completed run, never once per provider; treat this as an explicit, regression-tested behavioral change. `updateFailedAttempts()` stores initial/latest timestamps, not an integer failure counter. Merge multiple changes from the latest state in one transaction so one requirement cannot overwrite another's timestamps. Sources: [bazarr/subtitles/wanted/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/series.py); [bazarr/subtitles/wanted/movies.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/movies.py); [bazarr/subtitles/adaptive_searching.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/adaptive_searching.py).
5. **Existing processing emits side effects before the Wanted caller records history.** `generate_subtitles()` saves and calls `process_subtitle()`, which can synchronize, run a post-processing command, notify media managers and emit events. The Wanted caller then indexes and writes history. Moving only the history write to a queue would leave notifications premature. Split processing into file work, persistence data and post-commit effects before enabling the new concurrency.
6. **Whisper fallback already exists.** The Wanted caller passes `use_whisper_fallback` through to the core. Under provider-by-provider scheduling, a miss from one provider must not be mistaken for exhaustion of all regular providers and trigger fallback early. Preserve current eligibility/opt-in rules and distinguish normal Whisper provider behavior from its fallback-only behavior. Sources: [bazarr/subtitles/wanted/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/series.py); [custom_libs/subliminal_patch/core.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core.py).

### 7.2 Existing components: reuse versus required extension

The following describes the pinned snapshot, not an assertion about all future releases.

| Existing component and source | What already exists | Required extension / invariant |
|---|---|---|
| [bazarr/subtitles/wanted/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/series.py) and [bazarr/subtitles/wanted/movies.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/wanted/movies.py) | Wanted selection, exclusions, adaptive-search gating, per-item dispatch, history/notification integration. | Replace sequential dispatch with bounded coordination; retain eligibility and distinguish search exhaustion from service unavailability. |
| [bazarr/subtitles/utils.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/utils.py) and [bazarr/subtitles/download.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/download.py) | Video preparation, score settings, language conversion, forced-provider configuration and per-requirement HI mode. | Prepare once per active item; pass immutable operation-specific policy instead of racing shared pool settings. |
| [custom_libs/subliminal_patch/core_persistent.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core_persistent.py) | Persistent pool wrapper combines listing and selection/download. | Expose a reusable discovery result and call existing selection with each requirement's policy. |
| [custom_libs/subliminal_patch/core.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/core.py) | Provider listing, matching/scoring, candidate fallback, validation, async provider pool, subtitle naming/saving and format support. | Preserve these capabilities; separate candidate evaluation state by requirement/video; do not invoke nested provider fan-out in the new Wanted path. |
| [bazarr/subtitles/pool.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/pool.py) | Reused pools, provider initialization/config updates, blacklists, ban lists and language equivalences. | Coordinate initialization, updates and ownership; keep profile-specific policy separate from global account/rate ownership. |
| [bazarr/app/get_providers.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/get_providers.py) | Enabled-provider filtering, throttles, provider auth, provider-specific reset rules and blacklist handling. | Integrate global request/operation limits with these mechanisms; do not create conflicting cooldown records or bypass established provider resets. |
| [custom_libs/subliminal_patch/http.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/http.py) and [custom_libs/subliminal_patch/global_rate_limiter.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/global_rate_limiter.py) | Retry/session plumbing and rate-limit parsing foundation. | Verify actual coverage, atomic reservations and time handling; include retries and all transport paths, not just injected requests sessions. |
| [custom_libs/subliminal_patch/providers/utils.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/custom_libs/subliminal_patch/providers/utils.py) and pack adapters in section 1 | Archive parsing and target-member selection. | Add optional member enumeration and per-destination validation with shared pack identity and bounded storage. |
| [bazarr/subtitles/processing.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/processing.py), [bazarr/subtitles/sync.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/sync.py), [bazarr/subtitles/post_processing.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/post_processing.py) | Optional sync, post-processing thresholds/commands, permissions, result metadata and downstream integrations. | Retain per-subtitle work; defer external success effects until committed state. A pack must run the same applicable processing for each accepted member. |
| [bazarr/subtitles/indexer/series.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/indexer/series.py) and [bazarr/subtitles/indexer/movies.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/indexer/movies.py) | Index actual subtitles and compute missing state with cutoff, audio and variant rules; emit UI updates. | Reuse policy evaluation with transaction-local/current state; make stale index scans unable to overwrite newer saves and defer UI success events. |
| [bazarr/sonarr/history.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/sonarr/history.py) and [bazarr/radarr/history.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/radarr/history.py) | Per-subtitle history and provenance. | Route new-path writes through idempotent persistence with member identity; retain upgrade relationships. |
| [bazarr/app/database.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/database.py) | SQLAlchemy sessions, SQLite WAL/timeout, PostgreSQL support and profile helpers. | Own writer session on writer thread; explicit transactions and bounded batches; coordinate other writers. Existing autocommit must not be mistaken for atomic multi-statement batches. |
| [bazarr/app/jobs_queue.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/jobs_queue.py) and [bazarr/app/scheduler.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/app/scheduler.py) | Top-level jobs, progress and scheduled execution limits. | Reuse job identity/cancellation/progress. New in-job capacity must be bounded globally even when series and movie jobs run together. |
| [bazarr/subtitles/manual.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/manual.py) and [bazarr/subtitles/upgrade.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/subtitles/upgrade.py) | Manual candidate selection/download and separate upgrade searches. | Share quotas and conflicting-file ownership without replacing manual choice or forcing upgrades to stop at an arbitrary first provider. |

The source tree also contains episode/movie subtitle APIs and Sonarr/Radarr webhook entry points. They must be included in the write/search call-site audit: [bazarr/api/episodes/episodes_subtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/api/episodes/episodes_subtitles.py), [bazarr/api/movies/movies_subtitles.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/api/movies/movies_subtitles.py), [bazarr/api/webhooks/sonarr.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/api/webhooks/sonarr.py), [bazarr/api/webhooks/radarr.py](https://github.com/morpheus65535/bazarr/blob/ec41fe82c03ccd556d168666595bd0be1202f77b/bazarr/api/webhooks/radarr.py). These paths are verified integration locations; every nested call has not been audited here.

### 7.3 Shared work and result contracts

The implementation must represent, whether using these names or existing equivalents:

- **Media identity:** media type plus Sonarr episode/Radarr movie ID; current path/file fingerprint and profile/config generation. An ID alone is insufficient if the file is replaced during a run.
- **Requirement identity:** the relevant profile item/policy, language/region, HI policy, forced policy and effective scoring/upgrade constraints. Do not collapse requirements to base language. Preserve existing supported combinations; do not introduce a new combined HI+forced encoding silently.
- **Media work:** lightweight ID, current unresolved requirements, per-provider coverage/outcomes, active lease, generation, and references to bounded prepared metadata/candidate pools.
- **Discovery coverage:** which requirements were actually queried, whether discovery completed, pagination/fallback continuation and error state. Partial results are not evidence that unqueried variants have no match.
- **Candidate evidence:** provider/candidate/member identity and immutable release/variant metadata. Scores/matches computed for E01 or HI must not be reused as E02 or non-HI evidence.
- **Pack registry:** provider/account scope, stable pack identity/revision, shared download/enumeration operation, per-member outcomes and cleanup lifetime. Do not put tokens or signed URLs into logs or durable identities.
- **Save operation:** unique operation ID, media generation, requirement identity, candidate/member provenance, expected previous state, resulting paths and completion phase.
- **Persistence acknowledgment:** committed state/version or recoverable failure; a queued event alone is never durable success.

Existing data classes may be extended. These contracts do not require a separate duplicate database model for everything.

### 7.4 Full combined workflow

1. The existing Wanted job obtains eligible lightweight media IDs using monitoring/exclusion/profile rules. Adaptive search controls which requirements are due. Newly discovered out-of-scope pack members do not silently expand the run to excluded/unmonitored media.
2. The coordinator prepares only as many media objects as bounded capacity permits. It reads current file/profile state and retains preparation/hash results while the item is active.
3. An available compatible provider is paired with a ready item. Acquire item ownership and a provider operation reservation atomically, or retry without holding partial resources. Different media/profile pools sharing one provider account must share its quota.
4. Pass **all currently compatible, unattempted remaining requirements together** to provider discovery. A legacy adapter may issue internal per-language requests; each actual request still goes through the governor. Reuse a completed candidate pool for the same coverage/generation instead of restarting discovery.
5. For each active requirement, use the existing match/score/filter rules on the assigned provider's candidates. Download the best acceptable candidate from that provider and try its next candidate on a candidate-specific failure. Do not dispatch the next provider for the item concurrently.
6. If the result is a pack, enumerate once and fan out *member proposals* to eligible episode work items. This is not a second network provider search for those items. Release the triggering provider/media locks before attempting other destination leases, so two overlapping packs cannot deadlock by holding different episode locks.
7. Each destination accepts a member only while it owns the media save reservation, after rechecking identity, missing state and policy. If another search is already running, retain a bounded member proposal and reconcile at its next safe boundary; do not cancel an unsafe file operation. Superseded search results must fail the generation/state recheck before writing.
8. Perform the existing applicable naming, encoding/modification, original-format, synchronization and post-processing work. Keep a reservation throughout. A matching candidate or downloaded ZIP is not yet a successful subtitle.
9. Submit persistence for the resulting subtitle index/history/missing state. The item stays unavailable for redispatch while the save/commit is pending. Group related database changes; acknowledge only after a real commit.
10. On acknowledgment, publish updated requirement state to the coordinator, invalidate queued stale work, re-evaluate cutoff and emit post-commit UI/notification work. A saved pack member can complete a different queued episode immediately; do not wait until that episode's scheduled turn to discover the success.
11. If requirements remain, return the item to READY for an available untried provider. If all requirements are satisfied or no longer needed under cutoff, finish the item. Exhausted, deferred and failed items remain distinguishable.
12. At run completion/cancellation, flush/reconcile saves, stop dispatch and release resources. Unresolved requirements remain Wanted. A future run may retry providers because provider-attempt records are not permanent “never search again” decisions.

### 7.5 Pending persistence, cutoff and crash behavior

Use an explicit lifecycle such as:

```text
READY -> LEASED -> SAVING -> COMMIT_PENDING -> COMMITTED
                   |              |
                   +---- recoverable failure -> RECONCILE
COMMITTED -> READY (remaining work) or COMPLETE
READY -> EXHAUSTED / DEFERRED / CANCELLED / FAILED
```

A SAVING or COMMIT_PENDING reservation suppresses duplicate dispatch but does **not** tell the user that the subtitle is durably completed. The simplest correct initial implementation holds that media item until commit acknowledgment before resolving its next requirement. Other media items can continue, and the writer can still batch events from them. An optimized in-memory overlay is optional, but it must reproduce real cutoff evaluation and roll back on failure.

Use fresh committed index/profile state for the next requirement. A failed save cannot satisfy a cutoff. A failed database commit cannot leave a permanent “done” marker in memory. Reconciliation must inspect the actual resulting file before retrying a download.

Use stable operation IDs to prevent duplicate history during retries. Prefer safe staged writes/replacement and retain an upgrade's previous valid file until the new result is safe. Account for legacy naming, single-language paths, original formats and permissions. Where multiple requirements resolve to the same output path under existing settings, preserve documented legacy behavior or surface the conflict explicitly; do not silently overwrite one required variant.

A restart need not resume every transient search operation. It must reconcile saved files, recover or explicitly report interrupted persistence, and leave unresolved work eligible for another run. Specify durable journaling or an equivalent recoverable scheme if history/effect delivery must survive the save/commit gap. Do not promise exactly-once external notifications: use idempotent/coalesced effects and bounded retries where recipients allow them.

Coalesce refreshes that are genuinely equivalent. Do not suppress per-subtitle post-processing commands or webhook payloads merely because multiple subtitles belong to one episode. Preserve their enabled state and meaningful per-subtitle data.

### 7.6 Existing-policy compatibility requirements

**Selection:** FR2 alone must retain the existing provider discovery scope and selection criteria; sharing candidate discovery must not itself introduce first-provider stopping. The first-acceptable-provider policy belongs to FR3's new Wanted scheduling mode. Manual searches still show appropriate candidates and honor user selection. Upgrade searches retain their current eligibility/score comparison rules.

**Profiles and files:** Preserve real cutoff behavior, normal/HI preference/Exclude HI/forced policies, language equivalences and region distinctions, audio exclusion/inclusion, release restrictions, blacklists, minimum scores, monitored/excluded state, existing-subtitle detection, path mappings, naming, format/encoding/modifications and permissions. Where current behavior appears defective, document and test a separate deliberate fix rather than claiming invisible compatibility.

**Fallback and generated subtitles:** Do not run a fallback-only provider simply because one regular provider missed. Reach genuine regular-provider exhaustion first. A provider in cooldown, lacking credentials or out of quota is unavailable, not a proven no-match. Defer fallback when required coverage is incomplete unless current explicitly configured fallback policy permits it. Preserve explicit AI/transcription/translation opt-ins and their quotas; these requests do not authorize adding new automatic paid operations.

**Adaptive search:** Stamp exhaustion only after complete compatible-provider coverage under the new policy. No providers enabled, all providers unavailable, cancellation and file/persistence errors are deferred/failed outcomes, not no-match evidence. Pack members for requirements not currently due under adaptive searching remain outside the initial run scope; any later opportunistic expansion is a separately documented policy.

**Concurrency settings:** In the new Wanted mode, bypass internal all-provider fan-out. Existing “Search Enabled Providers Simultaneously” remains applicable to legacy/manual paths as supported, but those paths share the request governor. “Concurrent Jobs” still caps top-level jobs, not media or HTTP concurrency. Expose or document bounded in-flight item capacity separately, with conservative defaults; never interpret a job limit as permission for equal per-provider concurrency.

**Rate limiting:** Unknown limits use conservative operation limits and existing adapter pacing. Parse Retry-After and reset values correctly, use monotonic time for local waits and bounded jitter/backoff, and cancel waits promptly. Header parsing must not loosen a stricter known account/endpoint constraint. Unknown or contradictory telemetry is not permission to raise concurrency. Request reservations are shared across all in-process entry points; other programs using the same account/IP remain outside Bazarr's control, so respond to runtime throttles.

### 7.7 Feature-by-feature implementation and completion criteria

#### FR1: complete pack-reuse path

Implementation:
1. Add capability-gated pack enumeration at the provider/archive boundary.
2. Implement stable pack/member identity, shared download handling and bounded archive storage.
3. Map members to current eligible media, using member-specific evidence and common scoring.
4. Route accepted members through the common save/processing/persistence path.
5. Publish cross-item completion events; retain partial/retryable outcomes.
6. Implement at least one real pack-capable adapter end to end, with explicit supported-adapter coverage.

Done when:
- A fixture pack fills multiple eligible episodes from one archive access and produces correct per-episode history.
- Wrong series/season, ambiguous numbering, low score, unsupported variants and excluded media remain unfilled.
- Overlapping pack and individual searches cannot duplicate or overwrite successful work.
- Unsafe/corrupt archives and partial download/save failures leave recoverable state and clean up bounded storage.
- Providers lacking enumeration continue through the original single-result path.
- The release notes name which adapters support bulk reuse; existing pack recognition elsewhere must not be advertised as completed bulk reuse.

#### FR2: complete shared-discovery path

Implementation:
1. Separate the persistent listing wrapper from per-requirement selection using existing core entry points.
2. Construct a union with explicit discovery coverage and provider capability handling.
3. Reuse candidate evidence without cross-requirement score/match mutation.
4. Recheck canonical missing/cutoff state after committed results.
5. Adapt supported providers and retain internal legacy query fallback where needed.
6. Route both standalone Wanted discovery and FR3 assignments through this path.

Done when:
- English normal/HI/forced uses one logical discovery for a compatible provider and resolves each policy correctly.
- A multi-language cutoff scenario stops unnecessary subsequent downloads after cutoff is committed.
- Paginated, language-specific and partially failed providers report truthful coverage.
- Listing failures are handled once; candidate failure can use another listed candidate.
- FR2 alone does not silently change cross-provider result choice.
- Existing unbatchable providers remain functional with no false “searched” outcomes.

#### FR3: complete provider-aware scheduler

Implementation:
1. Add global bounded scheduling, atomic item/provider ownership and run-scoped attempt tracking.
2. Integrate request-level rate/quota governance with provider lifecycle and existing throttles.
3. Dispatch FR2 discovery and consume FR1 cross-item completion events.
4. Refactor file processing, database transactions and post-commit effects.
5. Coordinate manual/webhook/upgrade/indexer paths that touch the same providers/files/state.
6. Wire progress, cancellation, settings, shutdown/recovery and fallbacks.
7. Document first-acceptable-provider semantics and controlled rollout/fallback.

Done when:
- Multiple items progress through different providers without overlapping provider searches for one item.
- All in-process provider traffic, including retries and other jobs, obeys the shared limits.
- A pending commit or pack completion cannot cause duplicate dispatch/save.
- Partial success, true exhaustion, unavailable providers and persistence failures remain distinct.
- SQLite and supported PostgreSQL paths pass transaction/retry tests.
- The existing processing/history/notification lifecycle remains complete.
- Cancellation and restart do not lose saved work, leave permanent locks or report false completion.

### 7.8 Combined acceptance scenarios

Use deterministic fake providers and fixtures; tests below are required evidence for implementation completion, not tests already run.

| Scenario | Expected result |
|---|---|
| E01–E20 missing; E01 discovers a valid season pack; E07 ambiguous | One pack access; 19 independently valid saves; E07 remains unresolved. |
| E02 queued while E01's pack satisfies it | E02 receives current committed state and performs no unnecessary later provider search. |
| E02 already searching when the pack offers a member | Common reservation/state checks allow only one accepted write; stale result cannot overwrite it. |
| Same provider has normal, HI and forced candidates | One covered discovery; independent scoring and variant policies; no score mutation leakage. |
| French save meets the actual profile cutoff | English remains undispatched after commit; failed French persistence cannot falsely meet cutoff. |
| Current provider offers 85%, another would offer 95%, minimum is 80% | New FR3 mode may save the 85% result and stop; legacy/upgrade behavior is tested separately. |
| Writer batch is deliberately delayed | Requirement stays reserved; no duplicate search; UI durable completion waits for acknowledgment. |
| Save succeeds, commit fails | Reconcile actual file and retry idempotently; no lost/duplicated history or premature success effect. |
| Two requirements exhaust in one item | Merge adaptive timestamps without lost updates; stamp each once under the new explicit policy. |
| One provider returns 429; others have capacity | Only affected scope cools down; no false no-match and no premature Whisper fallback. |
| Series, movies, manual search and webhook run together | Shared provider/account limits hold; conflicting file writes serialize; interactive work is not starved. |
| Pack members require sync, post-processing and different original formats | Each follows applicable existing settings; coalesced refreshes do not omit per-subtitle work. |
| Profile/path/media changes during search | Generation recheck rejects stale result and recalculates eligible work. |
| Legacy non-batch/non-pack adapter | Existing fallback succeeds without requiring an adapter rewrite. |
| Cancel while network, local extraction and commits are active | No new dispatch; bounded waits; safe saves/commits/reconciliation; remaining work stays Wanted. |

Benchmark against the pinned sequential baseline using identical policies, candidates and fake-provider timing. Report operation and actual HTTP counts separately; archive download/member counts; resolved requirements; peak memory; provider-limit violations; writer queue depth/latency; cancellation latency; and elapsed time. Correctness invariants must pass regardless of speedup. Publish the measured results rather than promising an arbitrary speed multiplier.

### 7.9 Delivery sequence and remaining verification

1. **Baseline characterization:** record current branch/commit, trace all search/save callers, and add compatibility fixtures for real profile, variant, fallback and output behaviors. The source audit here establishes entry points, not a completed proof over every caller.
2. **Common boundaries:** separate discovery, requirement evaluation, file processing, persistence and effects while keeping a working legacy path. Characterize mutable provider/candidate state.
3. **Independent optimizations:** deliver FR2 and at least one FR1 adapter using the common path; demonstrate value with sequential scheduling.
4. **Shared ownership/governance:** cover all provider transports and conflicting save paths; test rate scopes and cancellation without enabling item parallelism yet.
5. **Bounded scheduler/persistence:** wire FR3, cross-item pack completion and transaction acknowledgments; run the combined scenarios and database matrix.
6. **Release completion:** document supported adapters, changed selection/adaptive semantics, settings interaction, upgrade/migration/rollback behavior and measured performance. Provide a legacy-mode escape path for rollout and explicit cleanup/recovery if durable operation records are introduced.

For every adapter enabled for a new capability, record: supported media/languages/variants, batch/pack behavior, local filtering, endpoint/request amplification, auth/session mutability, rate/quota/reset sources, fallback/generation behavior and tests. Prefer existing capability metadata; add optional declarations only where it lacks necessary information.

The eight-provider research matrix is not an audit of every Bazarr provider. Unknown providers must continue through conservative legacy-compatible paths. Before release, verify retained source findings against the implementation branch and live provider contracts. Missing production limits are handled conservatively; they do not justify inventing numbers or claiming universal pack/batch support.

Completion means the applicable implementation stages, regression checks and combined acceptance scenarios have passed, with adapter coverage and remaining limitations stated. A working outer worker pool or a successful pack extraction alone does not complete these requests.
