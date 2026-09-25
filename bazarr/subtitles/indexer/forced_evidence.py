# coding=utf-8

"""Decide which titles don't need forced subtitles.

Forced subtitles only exist for titles with foreign-language parts. For each series (or movie) and language:
1. it needs forced subtitles if it has any: an indexed forced subtitle (embedded track or external file) or a forced
   subtitle in its history;
2. otherwise, when TMDB knows the title's spoken languages, it needs them only if more than one language is spoken;
3. otherwise, it doesn't need them once forced subtitles have been searched for it longer than the grace period ago
   without finding any.
Titles that don't need forced subtitles get the forced requirement left out of their missing subtitles, so they aren't
wanted anymore. As soon as a forced subtitle shows up for the title, it's wanted again.
"""

import ast
import logging
import time

import requests
from subliminal import region

from app.config import settings
from app.database import (database, select, TableEpisodes, TableEpisodesSubtitles, TableHistory, TableMovies,
                          TableMoviesSubtitles, TableHistoryMovie, TableShows)

# the TMDB key bundled with Bazarr (also used by the Wizdom provider), unless one is configured
_BUNDLED_TMDB_API_KEY = 'a51ee051bcd762543373903de296e0a3'
_TMDB_URL = 'https://api.themoviedb.org/3'
# spoken languages rarely change: keep them in the subtitles cache for a month
_TMDB_CACHE_SECONDS = 30 * 24 * 3600
# after a TMDB error, don't try again for a while (a full recompute would otherwise wait on every title)
_TMDB_BACKOFF_SECONDS = 600
_tmdb_unavailable_until = 0.0


def enabled():
    return bool(settings.general.forced_only_when_available)


class ForcedNeeds:
    def __init__(self, evidence=None, spoken=None, first_search=None, searched_before=0.0):
        self.evidence = evidence or set()
        self.spoken = spoken or {}
        self.first_search = first_search or {}
        self.searched_before = searched_before

    def not_needed(self, media_id, language):
        """Whether forced subtitles in this alpha2 language can be left out for this series or movie."""
        if (media_id, language) in self.evidence:
            return False
        spoken = self.spoken.get(media_id)
        if spoken:
            return len(set(spoken)) < 2
        first = self.first_search.get((media_id, language))
        return first is not None and first <= self.searched_before


_NOTHING_TO_SKIP = ForcedNeeds()


def forced_needs(media_type, ids):
    """ForcedNeeds for these series or movie ids (nothing is left out while the option is disabled)."""
    ids = {x for x in ids if x is not None}
    if not enabled() or not ids:
        return _NOTHING_TO_SKIP

    if media_type == 'series':
        id_column, subtitles_table, history_table, media_table = (
            'sonarrSeriesId', TableEpisodesSubtitles, TableHistory, TableEpisodes)
    else:
        id_column, subtitles_table, history_table, media_table = (
            'radarrId', TableMoviesSubtitles, TableHistoryMovie, TableMovies)

    evidence = set()
    for row in database.execute(
            select(getattr(subtitles_table, id_column), subtitles_table.language)
            .where(subtitles_table.forced.is_(True), getattr(subtitles_table, id_column).in_(ids))
            .distinct()).all():
        evidence.add((row[0], row[1]))
    for row in database.execute(
            select(getattr(history_table, id_column), history_table.language)
            .where(history_table.language.like('%:forced'), getattr(history_table, id_column).in_(ids))
            .distinct()).all():
        evidence.add((row[0], row[1].split(':')[0]))

    # first time forced subtitles were searched (and not found) for each title and language
    first_search = {}
    for row in database.execute(
            select(getattr(media_table, id_column), media_table.failedAttempts)
            .where(media_table.failedAttempts.is_not(None), getattr(media_table, id_column).in_(ids))).all():
        try:
            attempts = ast.literal_eval(row[1])
        except (ValueError, SyntaxError):
            continue
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if (isinstance(attempt, (list, tuple)) and len(attempt) > 1 and isinstance(attempt[0], str)
                    and attempt[0].endswith(':forced')):
                key = (row[0], attempt[0].split(':')[0])
                try:
                    first_search[key] = min(first_search.get(key, float(attempt[1])), float(attempt[1]))
                except (TypeError, ValueError):
                    continue

    spoken = _spoken_languages(media_type, ids) if settings.general.forced_evidence_use_tmdb else {}
    searched_before = time.time() - max(0, int(settings.general.forced_evidence_grace_days)) * 86400
    return ForcedNeeds(evidence, spoken, first_search, searched_before)


def _spoken_languages(media_type, ids):
    """{series or movie id: [alpha2 spoken languages]} from TMDB, for the titles it knows."""
    if media_type == 'series':
        rows = database.execute(select(TableShows.sonarrSeriesId, TableShows.tvdbId)
                                .where(TableShows.sonarrSeriesId.in_(ids))).all()
        lookups = {row[0]: ('tv', row[1]) for row in rows if row[1]}
    else:
        rows = database.execute(select(TableMovies.radarrId, TableMovies.tmdbId)
                                .where(TableMovies.radarrId.in_(ids))).all()
        lookups = {row[0]: ('movie', row[1]) for row in rows if row[1]}

    spoken = {}
    for media_id, (kind, external_id) in lookups.items():
        languages = _tmdb_spoken_languages(kind, external_id)
        if languages:
            spoken[media_id] = languages
    return spoken


def _tmdb_spoken_languages(kind, external_id):
    """Spoken languages of a TMDB movie (by TMDB id) or tv show (by TVDB id); [] when unknown, None on errors."""
    def fetch():
        global _tmdb_unavailable_until
        if time.time() < _tmdb_unavailable_until:
            return None
        api_key = settings.general.tmdb_api_key or _BUNDLED_TMDB_API_KEY
        try:
            if kind == 'tv':
                response = requests.get(f'{_TMDB_URL}/find/{external_id}',
                                        params={'api_key': api_key, 'external_source': 'tvdb_id'}, timeout=5)
                response.raise_for_status()
                results = response.json().get('tv_results') or []
                if not results:
                    return []
                url = f"{_TMDB_URL}/tv/{results[0]['id']}"
            else:
                url = f'{_TMDB_URL}/movie/{external_id}'
            response = requests.get(url, params={'api_key': api_key}, timeout=5)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return sorted({x.get('iso_639_1') for x in response.json().get('spoken_languages') or []
                           if x.get('iso_639_1')})
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            logging.debug(f'BAZARR unable to get spoken languages from TMDB: {error!r}')
            _tmdb_unavailable_until = time.time() + _TMDB_BACKOFF_SECONDS
            return None

    try:
        return region.get_or_create(f'tmdb.spoken_languages.{kind}.{external_id}', fetch,
                                    expiration_time=_TMDB_CACHE_SECONDS,
                                    should_cache_fn=lambda value: value is not None)
    except Exception:
        logging.debug('BAZARR unable to use the subtitles cache for TMDB spoken languages', exc_info=True)
        return None


def has_forced_evidence(media_type, media_id, language, exclude_episode_id=None):
    """Whether the title already has a forced subtitle in this language (optionally ignoring one episode)."""
    if media_type == 'series':
        stmt = select(TableEpisodesSubtitles.id).where(TableEpisodesSubtitles.sonarrSeriesId == media_id,
                                                       TableEpisodesSubtitles.language == language,
                                                       TableEpisodesSubtitles.forced.is_(True))
        if exclude_episode_id is not None:
            stmt = stmt.where(TableEpisodesSubtitles.sonarrEpisodeId != exclude_episode_id)
    else:
        stmt = select(TableMoviesSubtitles.id).where(TableMoviesSubtitles.radarrId == media_id,
                                                     TableMoviesSubtitles.language == language,
                                                     TableMoviesSubtitles.forced.is_(True))
    return database.execute(stmt.limit(1)).first() is not None
