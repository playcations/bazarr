# Bazarr Research Notes — Feature 3: Provider-Aware Parallel Wanted Scheduling

## Proposed feature

Replace the current one-media-at-a-time Wanted processing model with a bounded scheduler that lets multiple movies/episodes make progress at once while each provider independently enforces its own safe concurrency/rate limits.

This is **not** "wrap the Wanted loop in a ThreadPoolExecutor."

The desired model is:

```text
many media items active
+
one provider at a time per media item
+
provider-specific concurrency/rate control
+
controlled persistence
```

---

## Current Wanted processing is sequential

### Series

`wanted_search_missing_subtitles_series()`:

```python
for i, episode in enumerate(episodes, start=1):
    ...
    wanted_download_subtitles(episode.sonarrEpisodeId, job_id=job_id)
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/wanted/series.py

### Movies

The movie Wanted loop follows the same media-item-at-a-time pattern.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/wanted/movies.py

There is no media-item worker pool inside either Wanted job.

---

## Existing concurrency layers

Bazarr already has several forms of concurrency.

### 1. Top-level Concurrent Jobs

`bazarr/app/jobs_queue.py` starts one thread per Bazarr job while:

```python
len(self.jobs_running_queue) < settings.general.concurrent_jobs
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/app/jobs_queue.py

This means:

- Wanted Series
- Wanted Movies
- Sonarr sync
- Radarr sync
- other jobs

can run concurrently.

This does **not** make one Wanted job process multiple episodes simultaneously.

### 2. Provider-level parallel search

When **Search Enabled Providers Simultaneously** is enabled, Bazarr uses:

```python
SZAsyncProviderPool
```

`SZAsyncProviderPool.list_subtitles()` uses a `ThreadPoolExecutor`, normally with one worker per enabled provider.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/core.py

So one episode can already query several providers simultaneously.

### 3. Languages are currently sequential

`generate_subtitles()` loops `language_set` sequentially.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/download.py

This is deliberate for cutoff/HI/forced correctness.

---

## Why naive outer threading is dangerous

If current provider parallelism remains unchanged:

```text
4 media workers
x
6 providers
=
up to ~24 provider search calls in flight
```

That can create repeated concurrent calls to the same provider.

A safe implementation therefore needs provider-aware scheduling, not simply item-level threads around the current pool.

---

## Proposed scheduler behavior

Example:

```text
Worker / work item A -> OpenSubtitles
Worker / work item B -> SubDL
Worker / work item C -> Gestdown
Worker / work item D -> TVSubtitles
Movie E            -> YIFY
```

Each media item only has one active provider lease at a time.

If a provider returns no acceptable result:

```text
Item B:
    SubDL -> tried / no match
```

the item returns to the ready queue.

The scheduler selects the next:

```text
available
compatible
untried
```

provider.

There is no need for a fixed provider rotation.

Provider availability naturally distributes starting providers.

---

## State needed per work item

Conceptually:

```text
MediaWorkItem
    media_id
    media_type
    remaining requirements
    providers attempted
    current provider lease
    current state
```

If Feature 2 is implemented, `remaining requirements` can include all variants that are still missing.

If Feature 1 is implemented, a pack result can satisfy several other work items.

---

## Suggested state machine

```text
READY
  |
  | scheduler finds available compatible provider
  v
LEASED(provider)
  |
  +-- acceptable result
  |       |
  |       v
  |   SAVE / COMMIT
  |       |
  |       +-- requirements remain --> READY
  |       |
  |       +-- all satisfied --------> COMPLETE
  |
  +-- no acceptable result
  |       |
  |       +-- untried providers ----> READY
  |       |
  |       +-- none remain ----------> EXHAUSTED
  |
  +-- provider throttled
          |
          +-- release item ---------> READY
          +-- provider cooldown
```

Important:

- `NO_MATCH` marks that provider tried.
- `429` / throttling should **not** count as a completed search.
- auth/config errors can disable that provider.
- transient network errors should follow provider retry/backoff policy.

---

## Per-provider lanes

Provider state should be independent from worker count.

Conceptually:

```text
ProviderState
    provider_name
    max_in_flight
    min_request_interval
    next_available
    throttled_until
    quota state
    capabilities
```

A scheduler could have 8 media items active but still allow:

```text
Addic7ed max_in_flight = 1
```

while another API provider may safely allow more.

Provider concurrency and HTTP request-rate limits should be distinct.

One provider invocation can itself make multiple HTTP requests.

---

## Provider limits researched

### OpenSubtitles.com

Relevant characteristics:

- login endpoint has a documented strict rate limit
- normal API limits can differ from login
- returned API host/base URL can have its own limits
- runtime rate-limit headers should be honored
- daily subtitle-download allowance is separate from search/API throughput
- generated/static subtitle-file download infrastructure can have separate limits from API calls

Implementation implication:

Do not hardcode one OpenSubtitles "requests/sec" value for every operation.

Prefer operation-aware or runtime-header-aware limits.

### SubDL

Relevant characteristics:

- Pro tier: 30,000 API requests/day
- Pro tier: 2,000 downloads/day
- some paid endpoints document high per-minute rates
- provider handles service busy / rate-limit payloads
- provider can make additional fallback/search requests for one media item

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/subdl.py
- https://subdl.com/api-doc

Implementation implication:

Track API-request quota separately from download quota.

### Gestdown

Current Bazarr provider contains:

```python
# TODO: implement rate limiting
```

and retries HTTP 423 up to 3 times with 30-second sleeps.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/gestdown.py

The open-source AddictedProxy/Gestdown backend includes an IP-based token-bucket rate limiter.

Checked-in defaults researched earlier:

```text
TokenLimit: 200
TokensPerPeriod: 50
ReplenishmentPeriod: 1 minute
QueueLimit: 2
```

Production can override those settings, so these should not be treated as guaranteed live limits.

Implementation implication:

Use 429/Retry-After/runtime behavior rather than hardcoding repository defaults.

### Addic7ed

Bazarr provider has strong evidence of sensitivity:

- explicit sleeps in login/search flows
- `TooManyRequests`
- local daily download cap accounting
- current Bazarr code uses:
  - 40 downloads/day regular
  - 80 VIP

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/addic7ed.py

A real 429 was observed during the user's setup.

Implementation implication:

Default to one in-flight provider operation and preserve conservative pacing.

### SuperSubtitles

Current provider explicitly defines:

```python
multi_result_throttle = 2  # seconds
```

and sleeps after a search.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/supersubtitles.py

Implementation implication:

Preserve provider-specific pacing.

### TVSubtitles

No reliable current published numeric request limit found.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/tvsubtitles.py

Implementation implication:

Start conservatively, probably one in-flight operation, and react to provider errors/throttling.

### YIFY Subtitles

No reliable current published request-rate limit found.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/yifysubtitles.py

Implementation implication:

Start conservatively and dynamically back off.

### EmbeddedSubtitles

No network quota.

However, it can:

- ffprobe media
- inspect subtitle tracks
- extract subtitle streams with ffmpeg
- hold local cache state
- run with extraction timeout up to 600 seconds

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/embeddedsubtitles.py

Implementation implication:

Use a separate bounded local-I/O lane rather than treating it like an Internet provider.

---

## Existing global rate-limit infrastructure

Bazarr already contains:

- `custom_libs/subliminal_patch/global_rate_limiter.py`
- a `RateLimiting` HTTP-session mixin in `http.py`

Sources:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/global_rate_limiter.py
- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/http.py

`DomainThrottler` is thread-safe and can parse:

```text
RateLimit
RateLimit-Policy
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
Retry-After (handled in http.py)
```

It can:

- wait for exhausted windows
- spread low remaining quota
- react to 429
- track per-domain state

However, the ordinary `RetryingSession` injected into providers derives from `CertifiSession`, not the `RateLimiting` mixin.

So this infrastructure appears not to govern normal provider traffic today.

This is useful implementation groundwork for the scheduler.

---

## Rate-limit key scope

Per-domain state may not always be enough.

Example:

```text
OpenSubtitles login
OpenSubtitles API search
OpenSubtitles generated/static file download
```

can have different limits.

A generalized scheduler/rate governor may need a key such as:

```text
provider
operation class
hostname
```

rather than hostname alone.

---

## Shared provider pools and mutable state

Bazarr caches provider pools globally in `bazarr/subtitles/pool.py` keyed by:

```text
media_type + profile_id
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/pool.py

Within `SZProviderPool`, mutable state includes:

- providers set
- initialized provider objects
- discarded providers
- blacklist
- ban list
- provider configs
- language equals

Lazy provider initialization occurs when a provider is first indexed.

A naive outer item worker pool would make simultaneous pool initialization/update more common.

This should be audited for thread safety.

---

## Shared provider objects

Provider instances often contain mutable state:

### OpenSubtitles

- `Session`
- token
- server hostname
- `self.video`

### Addic7ed

- `Session`
- cookies/auth state
- local daily-download accounting

### SubDL

- `Session`
- policy state
- AI translation quota state
- explicit lock around at least one shared mutable set

A current SubDL comment explicitly says:

> Bazarr shares one provider instance across threads, so guard the set.

This proves provider instances are already shared across threaded paths and need deliberate state protection when concurrency expands.

---

## Addic7ed race risk

Current download accounting is a read-modify-write sequence against cached `addic7ed_dls`:

```text
read list
filter list
check count
download
append timestamp
write list
```

There is no obvious lock around the entire sequence.

Multiple same-provider download workers could race this accounting.

This is another reason provider-aware serialized lanes are safer than unrestricted item threading.

---

## Throttle state

`bazarr/app/get_providers.py` maintains global provider throttle state:

```text
tp
throttle_count
```

and provider-specific cooldown mappings.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/app/get_providers.py

Current cooldown examples include:

```text
OpenSubtitles TooManyRequests -> 1 minute
OpenSubtitles DownloadLimitExceeded -> 6 hours

Addic7ed TooManyRequests -> 5 minutes
Addic7ed DownloadLimitExceeded -> 3 hours

SubDL APIThrottled -> 15 minutes
SubDL download-limit reset -> midnight GMT
```

The scheduler should integrate with this state rather than create an unrelated second throttle system.

---

## Database concurrency

Bazarr uses:

- SQLAlchemy `scoped_session`
- thread-local sessions
- SQLite WAL
- `busy_timeout=60000`
- `NullPool`
- `AUTOCOMMIT`

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/app/database.py

This makes concurrent threads possible, but SQLite still has limited concurrent write behavior.

Actual Bazarr issues have reported:

```text
sqlite3.OperationalError: database is locked
```

when multiple jobs run concurrently.

Relevant issues:

- https://github.com/morpheus65535/bazarr/issues/3274
- https://github.com/morpheus65535/bazarr/issues/3225

Therefore a persistence queue/manager is based on real failure history.

---

## Proposed persistence manager

Search workers should produce logical events rather than independently performing every write.

Examples:

```text
SubtitleSaved
HistoryEntry
MissingStateChanged
FailedAttemptUpdated
WantedStateChanged
```

A central writer can flush:

```text
every N operations
or
every N milliseconds
```

Potential benefits:

- fewer SQLite transactions
- predictable write ordering
- easier batching
- less lock contention
- easier progress accounting
- one place to deduplicate conflicting updates

---

## File save vs DB commit

A subtitle file normally has to be written before Bazarr records it as present.

Safe conceptual ordering:

```text
provider download
    ->
subtitle save to disk
    ->
DB/index update
    ->
Wanted/history update
    ->
external side effects
```

A crash between file save and DB update is recoverable because later filesystem indexing can rediscover subtitles.

A DB row saying a subtitle exists before the file is durable is less desirable.

---

## Side effects

Current `process_subtitle()` can immediately:

- notify Sonarr/Radarr
- emit event-stream updates
- refresh Plex/Jellyfin
- call external webhook
- track analytics

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/processing.py

With parallel workers this can create bursts.

The persistence/post-processing layer should consider coalescing or sequencing these effects after successful commit.

---

## Media-level leases / duplicate work

The scheduler should prevent the same media item from being worked by multiple provider workers simultaneously.

A lease key can be:

```text
(media_type, media_id)
```

This should ideally coordinate with:

- Wanted searches
- manual searches
- webhook-triggered searches
- bulk/mass-download jobs

Otherwise a manual search could race a Wanted worker and write the same subtitle.

---

## `check_if_still_required` helps but is not enough

Current `generate_subtitles()` can re-check whether a language is still missing before searching it.

This reduces some duplicate work.

But two concurrent jobs can still both observe the language as missing before either one saves it.

Media-level leasing/deduplication is the stronger solution.

---

## Adaptive-search state

`updateFailedAttempts()` stores per-language timestamps.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/adaptive_searching.py

Provider attempts should not directly equal adaptive-search attempts.

Correct conceptual behavior:

```text
OpenSubtitles -> no match
SubDL -> no match
Gestdown -> no match
TVSubtitles -> no match

=> one completed unsuccessful Wanted cycle
```

not four failed adaptive searches.

Only after compatible providers are exhausted should adaptive-search failure state be updated.

---

## Bounded queue / memory

Do not create thousands of fully prepared `Video` objects at Wanted-job start.

Large-library issue #3241 reported extreme memory growth during other full-library operations and specifically notes Wanted tasks as another full-library iterator.

Source:

- https://github.com/morpheus65535/bazarr/issues/3241

Safer approach:

```text
DB query / lightweight IDs
    ->
bounded ready queue
    ->
prepare only N active media items
```

The queue can contain IDs/metadata rather than fully refined objects.

---

## Video/hash preparation

`get_video()` can:

- parse filename
- hash file
- refine with scene name
- run registered refiners

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/utils.py

Within one media work item, construct/refine/hash once and reuse it across provider attempts.

Do not recreate/re-hash when an item moves from:

```text
SubDL -> Gestdown -> OpenSubtitles
```

This also reduces I/O.

---

## EmbeddedSubtitles and local I/O

Parallel Wanted processing changes the resource profile even if hashing is not today's bottleneck.

Multiple work items can cause concurrent:

- media hashing
- ffprobe
- ffmpeg subtitle extraction
- filesystem scans

These should have separate local-I/O limits from network provider concurrency.

---

## Progress accounting

The existing Wanted job progress is episode/movie count based.

With workers completing out of order, progress should be based on terminal items:

```text
completed_or_exhausted / initial_item_count
```

Worker threads should not each set progress based on their local index.

The manager should aggregate completion count centrally.

---

## Cancellation/shutdown

Safe cancellation behavior:

1. stop dispatching new provider leases
2. allow in-progress file saves / commits to reach a safe point
3. release provider/media leases
4. close worker resources
5. leave unfinished items Wanted for the next run

---

## Thread-local DB cleanup

Because new worker threads would use SQLAlchemy `scoped_session`, worker lifecycle should include explicit session cleanup when appropriate.

This prevents long-lived thread-local session state from accumulating.

---

## Existing issue #3127 is different

Issue #3127 discussed the new jobs manager and top-level tasks being serialized/queued.

It led to configurable simultaneous Bazarr jobs.

Source:

- https://github.com/morpheus65535/bazarr/issues/3127

This feature is distinct:

```text
#3127:
multiple independent Bazarr jobs

This proposal:
multiple Wanted media items inside one Wanted job
```

---

## Related bulk paths are also sequential

Source review found the same item-by-item pattern in:

- series mass download
- movie mass download
- upgrade processing

This suggests the limitation is broader than Wanted.

However, the feature request should stay focused on Wanted first unless maintainers prefer a generalized bulk-work scheduler.

---

## Recommended implementation strategy

A robust architecture could be:

```text
Wanted coordinator
      |
      +--> bounded media-item queue
      |
      +--> provider scheduler
              |
              +--> OpenSubtitles lane
              +--> SubDL lane
              +--> Gestdown lane
              +--> Addic7ed lane
              +--> ...
      |
      +--> local-I/O lane
              |
              +--> EmbeddedSubtitles
              +--> hashing
              +--> ffprobe/ffmpeg
      |
      +--> persistence queue
              |
              +--> DB/index/history
              +--> coalesced side effects
```

---

## Suggested tests

### Scheduler invariants

- one media item never has two simultaneous provider leases
- one provider never exceeds configured `max_in_flight`
- request pacing never exceeds provider limiter
- throttled provider pauses only itself
- other providers continue working

### Work-item state

- no match marks provider attempted
- 429 does not mark provider attempted
- auth failure disables provider appropriately
- requirement completion removes only satisfied requirements
- item becomes exhausted only after all compatible providers tried

### Persistence

- multiple workers do not cause SQLite lock regression
- file saved before state marked present
- duplicate history entries not created
- adaptive failure updated once per exhausted requirement/run

### Concurrency with other entry points

- manual search cannot race same media item
- webhook search cannot race same media item
- separate media items can progress independently

### Cancellation

- no new work after cancel
- in-flight commits finish safely
- unresolved items remain Wanted

---

## Succinct Feature Upvote draft

### Title

Provider-aware parallel processing for Wanted subtitle searches

### Description

Bazarr's Wanted series/movie jobs currently process one media item at a time. Providers may be searched concurrently for that item, but the next episode/movie waits until it finishes.

I would like a provider-aware scheduler that keeps multiple Wanted items in flight while each item uses only one provider at a time.

Example:

```text
Episode A -> OpenSubtitles
Episode B -> SubDL
Episode C -> Gestdown
Episode D -> TVSubtitles
Movie E   -> YIFY
```

If a provider returns no acceptable result, that item is requeued and assigned another available compatible provider it has not tried. No fixed rotation is needed.

Each provider should independently enforce its own concurrency/rate limits and cooldowns; a 429 on one provider should not stall the others. EmbeddedSubtitles/local ffmpeg work should have a separate local-I/O limit.

This should not be implemented by simply wrapping the current Wanted loop in a thread pool, because Bazarr already has provider-level threading and shared provider state.

A controlled persistence queue/batched writer would also help avoid SQLite lock contention seen with concurrent Bazarr jobs.

This is separate from Concurrent Jobs/#3127: it is concurrency inside one Wanted job, not between separate Bazarr jobs.
