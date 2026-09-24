# Bazarr Research Notes — Feature 2: Multi-Requirement Provider Searches

## Proposed feature

For one movie/episode, ask each provider once for all currently compatible missing subtitle requirements, then reuse that candidate listing to resolve individual requirements such as:

- English normal
- English HI/SDH
- English forced
- multiple languages

The optimization must preserve Bazarr's existing per-requirement scoring, cutoff, forced, and HI semantics.

---

## What Bazarr does today

Current `generate_subtitles()` builds the `Video` object once, then loops over `language_set`:

```python
for language in language_set:
    ...
    downloaded_subtitles = download_best_subtitles(
        videos={video},
        languages={language},
        pool_instance=pool,
        ...
    )
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/bazarr/subtitles/download.py

So if one episode needs:

```text
English
English HI
English forced
```

the subtitle-search path is restarted three times.

Each pass can invoke all enabled providers again.

---

## This per-language loop is deliberate

This is important historical context.

Before November 2022, Bazarr passed the entire `language_set` into one `download_best_subtitles()` call.

Commit `2e2626ce` changed this to a per-language loop:

> "Fixed issue with cutoff not enforced when searching for multiple languages at the same time."

The change lets Bazarr re-check `check_if_still_required()` after each successful subtitle so a satisfied cutoff can prevent unnecessary fallback downloads.

Commit history:

- https://github.com/morpheus65535/bazarr/commit/2e2626ce

Later changes made the separation even more important:

- forced provider handling
- HI-required handling
- Exclude-HI support
- per-profile HI mode

Notable commits:

- `0b8274ec` — forced-provider pool handling
- `0f19d79f` — correct HI-required behavior
- `42a7a765` — Exclude-HI support

Therefore the right feature is **not** simply "revert to one multi-language `download_best_subtitles()` call."

The correct separation is:

```text
provider candidate discovery
        !=
requirement-specific selection/scoring/saving
```

---

## Why provider listing can often be reused

Many providers already naturally return multiple relevant subtitle variants from one search/page.

### OpenSubtitles.com

Current code builds a comma-separated list of languages:

```python
langs_list = ...
langs = ','.join(langs_list)
params = [('languages', langs)]
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/opensubtitlescom.py

The provider can therefore search multiple language basenames in one API query.

Forced vs normal is filtered afterward based on result metadata.

HI is also represented in result metadata.

### SubDL

Current code similarly builds:

```python
langs = ','.join(langs_list)
base_params = {
    'languages': langs,
    ...
}
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/subdl.py

SubDL can return:

- multiple languages
- forced metadata
- HI metadata
- packs
- translation candidates

A single provider listing can therefore potentially supply candidates for several requirements.

### Addic7ed

Addic7ed downloads a show/season page and then filters rows locally by requested language/episode.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/addic7ed.py

The expensive provider request can already contain multiple subtitle variants.

### SuperSubtitles

SuperSubtitles retrieves provider data and filters the returned subtitles against the requested `languages` set.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/supersubtitles.py

### YIFY

YIFY fetches a movie page containing multiple subtitle rows and filters rows locally.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/yifysubtitles.py

### TVSubtitles

TVSubtitles retrieves an episode page containing subtitle rows for multiple languages.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/tvsubtitles.py

### EmbeddedSubtitles

EmbeddedSubtitles scans one container and obtains multiple subtitle tracks.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/embeddedsubtitles.py

Repeated provider invocations for different profile requirements may therefore repeat local media inspection.

### Gestdown

Gestdown is different.

Its current endpoint is language-specific:

```text
/subtitles/get/{show}/{season}/{episode}/{language}
```

and `list_subtitles()` loops languages internally.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/gestdown.py

This is fine.

The feature should mean:

> one Bazarr provider invocation per media item for all applicable requirements

not:

> every provider must use one HTTP request.

Provider internals remain free to issue multiple HTTP calls where required.

---

## Current core can already work with multiple languages

`SZProviderPool.download_best_subtitles()` accepts a set of languages and has logic intended to stop after all requested languages are downloaded.

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/core.py

However, it receives one `hearing_impaired` mode for the entire call.

That creates a problem for requirements such as:

```text
English normal
English HI
```

because these two requirements need different HI policies.

This reinforces the need to separate:

```text
list/search candidates once

then

resolve each requirement independently
```

rather than simply combining every requirement into the existing download pass.

---

## Proposed architecture

For one media item:

```text
Missing requirements
    EN normal
    EN HI
    EN forced
        |
        v
Provider.list_subtitles(video, union_of_supported_requirements)
        |
        v
Candidate set
        |
        +--> resolve EN normal
        +--> resolve EN HI
        +--> resolve EN forced
```

Each requirement-specific resolver retains:

- min score
- HI policy
- forced policy
- profile ordering
- cutoff semantics
- fallback semantics

The candidate discovery result is shared.

---

## Cutoff behavior must remain state-aware

Example profile:

```text
1. French
2. English
Cutoff: French
```

A shared OpenSubtitles query could return both French and English candidates.

Bazarr should:

```text
save French
re-index / update missing state
check cutoff
stop before saving English if cutoff is now satisfied
```

This preserves the reason the per-language loop was introduced in 2022.

Candidate discovery can be batched.

Requirement resolution must remain ordered and state-aware.

---

## Normal / HI / forced distinctions

Requirements cannot be collapsed by basename alone.

These are distinct:

```text
en
en:hi
en:forced
```

Provider result metadata must be preserved so the same candidate cache can be filtered differently for each requirement.

For hearing-impaired-verifiable providers:

- normal requirement may reject HI when Exclude HI is configured
- HI requirement must require HI
- default/non-preferred mode may accept either according to current scoring behavior

Forced needs the same distinction.

---

## Potential candidate-cache interface

A provider listing result could be scoped to:

```text
media item
provider
current Wanted run/search invocation
```

Example:

```text
ProviderCandidateSet
    provider
    video
    requested basenames/variants
    candidates[]
```

Then the resolver could call existing scoring code against the same candidates multiple times.

The cache should be short-lived.

It should not persist indefinitely because:

- provider results change
- new subtitles appear
- account/provider state changes
- Wanted state can change during a run

---

## Provider failures

This optimization also improves error semantics.

Current per-requirement invocation can theoretically repeat the same provider problem for several requirements.

A single provider listing failure should normally apply once to that media/provider attempt.

Examples:

- timeout
- 429
- authentication failure
- provider outage
- parser failure

That avoids turning one provider failure into repeated equivalent provider failures for:

```text
en
en:hi
en:forced
```

---

## Provider quota impact

Potential savings scale with profile complexity.

Example:

```text
6 enabled providers
3 missing subtitle requirements
```

The current orchestration can result in provider-listing work being repeated across each requirement.

The optimized model can often reduce the discovery phase closer to:

```text
6 provider listing operations
```

rather than a maximum resembling:

```text
18 provider listing operations
```

Actual savings depend on provider internals and whether later cutoff evaluation cancels remaining work.

---

## Relationship to provider-level parallelism

Current `SZAsyncProviderPool` already parallelizes provider listing for one video:

```python
ThreadPoolExecutor(...)
executor.map(
    self.list_subtitles_provider,
    self.providers,
    ...
)
```

Source:

- https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/core.py

The proposed feature does not require changing that first.

It reduces how many times Bazarr invokes the provider pool for the same video.

---

## Relationship to pack reuse

These solve different duplicate-work dimensions.

Pack-aware acquisition:

```text
one provider result -> many episodes
```

Multi-requirement search reuse:

```text
one provider listing -> many subtitle requirements for one media item
```

They can be implemented independently.

---

## Relationship to parallel Wanted scheduling

This optimization is valuable before parallelism.

Reducing provider invocations:

- reduces scheduler load
- reduces provider quota consumption
- reduces nested concurrency
- makes later provider-aware parallelism safer

The parallel scheduler should ideally consume these more efficient per-media work items.

---

## Existing issue history

GitHub issue #1978 ("Bazarr not finding/downloading multiple languages") shows that multi-language/forced behavior has historically been sensitive.

Source:

- https://github.com/morpheus65535/bazarr/issues/1978

The 2022 cutoff fix is the key architectural constraint for this feature.

Other HI/forced issues also reinforce that normal, forced, and HI must remain separately resolved rather than naively grouped.

Examples:

- https://github.com/morpheus65535/bazarr/issues/1494
- https://github.com/morpheus65535/bazarr/issues/2350

---

## Suggested test matrix

At minimum:

### Profile semantics

- one language normal
- normal + HI same language
- normal + forced same language
- normal + HI + forced same language
- two languages with cutoff on first
- fallback language not saved after cutoff satisfied
- Exclude HI
- Force HI
- default HI preference

### Provider behavior

- provider returns all requirements
- provider returns only one requirement
- provider returns no candidate
- provider timeout
- provider throttled
- provider does not support one requested variant
- provider internally requires multiple HTTP calls

### Regression tests

Verify existing cutoff behavior remains identical to current Bazarr after each successfully saved subtitle.

---

## Succinct Feature Upvote draft

### Title

Search each provider once per media item for all missing subtitle requirements

### Description

Bazarr currently loops through missing subtitle requirements in `generate_subtitles()` and runs the provider search path separately for each one. A profile needing English normal, English HI and English forced can therefore query the same provider multiple times for the same movie/episode.

Many providers already return several usable variants from one lookup: OpenSubtitles and SubDL accept multiple languages, Addic7ed/SuperSubtitles/TVSubtitles return multi-row pages, YIFY returns a movie subtitle list, and EmbeddedSubtitles scans multiple tracks at once.

I am not suggesting reverting Bazarr's per-language cutoff logic. That loop was added so cutoff/missing state can be re-evaluated after each successful save.

Instead, separate provider candidate discovery from requirement-specific selection:

1. Ask a provider once for all compatible missing requirements.
2. Reuse that candidate set.
3. Score/save normal, HI and forced requirements independently.
4. Re-check cutoff after each successful save and stop when appropriate.

Providers like Gestdown that require language-specific HTTP calls can still do so internally.

This could substantially reduce provider requests, parsing, quota use and Wanted processing time without adding any parallelism.
