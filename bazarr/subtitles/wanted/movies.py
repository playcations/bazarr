# coding=utf-8
# fmt: off

import ast
import logging
import operator

from functools import reduce

from utilities.path_mappings import path_mappings
from subtitles.indexer.movies import store_subtitles_movie, list_missing_subtitles_movies
from radarr.history import history_log_movie
from app.notifier import send_notifications_movie
from app.get_providers import get_providers
from app.database import (get_exclusion_clause, get_audio_profile_languages, TableMovies, database, update, select,
                          get_subtitles)
from app.event_handler import event_stream
from app.jobs_queue import jobs_queue
from app.config import settings

from ..adaptive_searching import is_search_active, updateFailedAttempts
from ..download import generate_subtitles
from ..locks import media_lock
from .parallel import run_parallel_wanted


def _movie_due_languages(movie):
    """Missing languages of this movie that adaptive search allows to search now."""
    languages = []
    for language in ast.literal_eval(movie.missing_subtitles or '[]'):
        if is_search_active(desired_language=language, attempt_string=movie.failedAttempts):
            languages.append(language)
        else:
            logging.info(f"BAZARR Search is throttled by adaptive search for this movie {movie.path} and "
                         f"language: {language}")
    return languages


def _search_movie(movie, languages, job_id=None, fallback_allowed=False, only_providers=None, video_cache=None):
    """Search and save subtitles for these languages of the movie. Returns how many subtitles were saved."""
    audio_language_list = get_audio_profile_languages(movie.audio_language)
    if len(audio_language_list) > 0:
        audio_language = audio_language_list[0]['name']
    else:
        audio_language = 'None'

    language_tuples = [(language.split(":")[0],
                        "True" if language.endswith(':hi') else "False",
                        "True" if language.endswith(':forced') else "False") for language in languages]

    saved = 0
    for result in generate_subtitles(path_mappings.path_replace_movie(movie.path),
                                     language_tuples,
                                     audio_language,
                                     str(movie.sceneName),
                                     movie.title,
                                     'movie',
                                     movie.profileId,
                                     check_if_still_required=True,
                                     job_id=job_id,
                                     fallback_allowed=fallback_allowed,
                                     only_providers=only_providers,
                                     video_cache=video_cache):

        if result:
            saved += 1
            store_subtitles_movie(movie.radarrId)
            history_log_movie(1, movie.radarrId, result)
            send_notifications_movie(movie.radarrId, result.message)
            event_stream(type='movie-wanted', action='delete', payload=movie.radarrId)
    return saved


def _stamp_movie_attempts(movie, languages):
    # chain the updates so every searched language keeps its own timestamps
    updated = movie.failedAttempts
    for language in languages:
        updated = updateFailedAttempts(desired_language=language, attempt_string=updated)
    database.execute(
        update(TableMovies)
        .values(failedAttempts=updated)
        .where(TableMovies.radarrId == movie.radarrId))


def _wanted_movie(movie, providers_list, job_id=None):
    languages_to_stamp = _movie_due_languages(movie)

    found_any = _search_movie(movie, languages_to_stamp, job_id=job_id,
                              fallback_allowed=settings.general.use_whisper_fallback)

    if not found_any and providers_list and languages_to_stamp:
        # a provider that got throttled during this search didn't really search, so it isn't a definitive miss
        available_providers = get_providers() or []
        if any(provider not in available_providers for provider in providers_list):
            logging.debug(f"BAZARR Not updating adaptive search attempts for {movie.path} because some providers "
                          f"got throttled during the search")
            return

        _stamp_movie_attempts(movie, languages_to_stamp)


def _load_movie(radarr_id, refresh_index=True):
    stmt = select(TableMovies.path,
                  TableMovies.missing_subtitles,
                  TableMovies.radarrId,
                  TableMovies.audio_language,
                  TableMovies.sceneName,
                  TableMovies.failedAttempts,
                  TableMovies.title,
                  TableMovies.profileId) \
        .where(TableMovies.radarrId == radarr_id)
    movie = database.execute(stmt).first()
    if not refresh_index:
        return movie

    previously_indexed_subtitles = get_subtitles(radarr_id=radarr_id)

    if not movie:
        logging.debug(f"BAZARR no movie with that radarrId can be found in database: {radarr_id}")
        return None
    elif not len(previously_indexed_subtitles) or \
            any([not x['embedded_track_id'] for x in previously_indexed_subtitles if not x['path']]):
        # subtitles indexing for this movie might be incomplete, we'll do it again
        store_subtitles_movie(radarr_id)
        movie = database.execute(stmt).first()
    elif movie.missing_subtitles is None:
        # missing subtitles calculation for this movie is incomplete, we'll do it again
        list_missing_subtitles_movies(no=radarr_id)
        movie = database.execute(stmt).first()
    return movie


def wanted_download_subtitles_movie(radarr_id, job_id=None):
    with media_lock('movie', radarr_id):
        movie = _load_movie(radarr_id)
        if not movie:
            return

        providers_list = get_providers()

        if providers_list:
            _wanted_movie(movie, providers_list, job_id=job_id)
        else:
            logging.info("BAZARR All providers are throttled")


class _MovieHandler:
    media_type = 'movie'
    load = staticmethod(_load_movie)
    due_languages = staticmethod(_movie_due_languages)
    search = staticmethod(_search_movie)
    stamp = staticmethod(_stamp_movie_attempts)

    @staticmethod
    def item_id(row):
        return row.radarrId

    @staticmethod
    def label(row):
        return row.title


def wanted_search_missing_subtitles_movies(job_id=None, wait_for_completion=False):
    if not job_id:
        jobs_queue.add_job_from_function("Searching for missing movies subtitles", is_progress=True,
                                         wait_for_completion=wait_for_completion)
        return

    conditions = [(TableMovies.missing_subtitles.is_not(None)),
                  (TableMovies.missing_subtitles != '[]')]
    conditions += get_exclusion_clause('movie')
    movies = database.execute(
        select(TableMovies.radarrId,
               TableMovies.tags,
               TableMovies.monitored,
               TableMovies.title)
        .where(reduce(operator.and_, conditions))) \
        .all()

    count_movies = len(movies)
    jobs_queue.update_job_progress(job_id=job_id, progress_max=count_movies)

    if count_movies == 0:
        jobs_queue.update_job_progress(job_id=job_id, progress_value='max')

    if settings.general.wanted_parallel_enabled:
        throttled = run_parallel_wanted(_MovieHandler, movies, job_id)
        movies = []
    else:
        throttled = False
    for i, movie in enumerate(movies, start=1):
        jobs_queue.update_job_progress(job_id=job_id, progress_value=i, progress_message=movie.title)

        providers = get_providers()
        if providers:
            wanted_download_subtitles_movie(movie.radarrId, job_id=job_id)

            # make sure to override the progress value updated by the subtitles synchronization
            jobs_queue.update_job_progress(job_id=job_id, progress_value=i, progress_max=count_movies)
        else:
            logging.info("BAZARR All providers are throttled")
            throttled = True
            break

    outcome_msg = ("All providers throttled" if throttled
                   else "Search completed")
    jobs_queue.update_job_progress(job_id=job_id, progress_message=outcome_msg)
    jobs_queue.update_job_name(job_id=job_id, new_job_name="Searched for missing movies subtitles")
    logging.info('BAZARR Finished searching for missing Movies Subtitles. Check History for more information.')
