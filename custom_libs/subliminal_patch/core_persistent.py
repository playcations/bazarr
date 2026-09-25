# coding=utf-8
from __future__ import absolute_import

from collections import defaultdict
import copy
import logging
import time

from subliminal.core import check_video

logger = logging.getLogger(__name__)

# list_all_subtitles, list_supported_languages, list_supported_video_types, download_subtitles, download_best_subtitles
def list_all_subtitles(videos, languages, pool_instance):
    listed_subtitles = defaultdict(list)

    # return immediatly if no video passed the checks
    if not videos:
        return listed_subtitles

    for video in videos:
        logger.info("Listing subtitles for %r", video)
        subtitles = pool_instance.list_subtitles(
            video, languages - video.subtitle_languages
        )
        listed_subtitles[video].extend(subtitles)
        logger.info("Found %d subtitle(s)", len(subtitles))

    return listed_subtitles


def list_supported_languages(pool_instance):
    return pool_instance.list_supported_languages()


def list_supported_video_types(pool_instance):
    return pool_instance.list_supported_video_types()


def download_subtitles(subtitles, pool_instance):
    for subtitle in subtitles:
        logger.info("Downloading subtitle %r with score %s", subtitle, subtitle.score)
        pool_instance.download_subtitle(subtitle)


def list_candidates(video, languages, pool_instance):
    """List subtitles once for several languages so each of them can then be resolved with select_best_subtitles."""
    languages = set(languages) - video.subtitle_languages
    if not languages:
        return []

    logger.info("Listing subtitles for %r and languages %r", video, languages)
    subtitles = pool_instance.list_subtitles(video, languages)
    logger.info("Found %d subtitle(s)", len(subtitles))
    return subtitles


def select_best_subtitles(
    candidates,
    video,
    language,
    pool_instance,
    min_score=0,
    hearing_impaired=False,
    use_original_format=False,
    fallback_allowed=False,
    exclude_ids=None,
    reject_detected_hi=False,
):
    """Download the best subtitles for a single language out of candidates previously listed with list_candidates.

    Equivalent to download_best_subtitles(languages={language}) without listing the providers again.
    """
    downloaded_subtitles = defaultdict(list)

    if not check_video(video, languages={language}):
        logger.info("Skipping video %r", video)
        return downloaded_subtitles

    exclude_ids = exclude_ids or set()
    subtitles = []
    for candidate in candidates:
        # a provider asked for a single language never returns the other forced variant
        if bool(candidate.language.forced) != bool(language.forced):
            continue
        if (candidate.provider_name, candidate.id) in exclude_ids:
            continue
        # scoring and downloading modify the subtitle, so every language works on its own copy
        subtitle = copy.copy(candidate)
        if isinstance(getattr(candidate, 'matches', None), set):
            subtitle.matches = set(candidate.matches)
        subtitles.append(subtitle)

    logger.info("Downloading best subtitles for %r and language %r", video, language)
    subtitles = pool_instance.download_best_subtitles(
        subtitles,
        video,
        {language},
        min_score=min_score,
        hearing_impaired=hearing_impaired,
        use_original_format=use_original_format,
        fallback_allowed=fallback_allowed,
        reject_detected_hi=reject_detected_hi,
    )
    logger.info("Downloaded %d subtitle(s)", len(subtitles))
    downloaded_subtitles[video].extend(subtitles)

    return downloaded_subtitles


def download_best_subtitles(
    videos,
    languages,
    pool_instance,
    min_score=0,
    hearing_impaired=False,
    only_one=False,
    use_original_format=False,
    fallback_allowed=False,
    reject_detected_hi=False,
    **kwargs
):
    downloaded_subtitles = defaultdict(list)

    # check videos
    checked_videos = []
    for video in videos:
        if not check_video(video, languages=languages, undefined=only_one):
            logger.info("Skipping video %r", video)
            continue
        checked_videos.append(video)

    # return immediately if no video passed the checks
    if not checked_videos:
        return downloaded_subtitles

    # download best subtitles
    for video in checked_videos:
        logger.info("Downloading best subtitles for %r", video)
        subtitles = pool_instance.download_best_subtitles(
            pool_instance.list_subtitles(video, languages - video.subtitle_languages),
            video,
            languages,
            min_score=min_score,
            hearing_impaired=hearing_impaired,
            only_one=only_one,
            use_original_format=use_original_format,
            fallback_allowed=fallback_allowed,
            reject_detected_hi=reject_detected_hi,
        )
        logger.info("Downloaded %d subtitle(s)", len(subtitles))
        downloaded_subtitles[video].extend(subtitles)

    return downloaded_subtitles
