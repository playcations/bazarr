# coding=utf-8

"""Decide which titles and episodes don't need forced subtitles.

Forced subtitles only exist for titles with foreign-language parts, often only in a few episodes of a series. Nothing
in Sonarr, Radarr or TMDB says which episodes, so it's learned from what is found (indexed forced subtitles, embedded
or external, and forced subtitles in history) versus what was searched without result (failedAttempts):
- a movie needs forced subtitles if it has any, else if TMDB lists more than one spoken language for it, else until
  they were searched for it longer than the grace period ago;
- an episode of a series TMDB lists with a single spoken language and without any forced subtitle doesn't need them;
- otherwise every episode is searched once; an episode searched longer than the grace period ago without result keeps
  wanting forced subtitles only if the series needs them throughout: enough of its checked episodes (at least
  MIN_EPISODES_CHECKED, a share of at least general.forced_series_ratio percent) have forced subtitles.
Whatever doesn't need them gets the forced requirement left out of its missing subtitles, so it isn't wanted.
"""

import ast
import logging
import time

import requests
from subliminal import region
from subliminal.cache import SHOW_EXPIRATION_TIME

from app.config import settings
from app.database import (database, select, TableEpisodes, TableEpisodesSubtitles, TableHistory, TableMovies,
                          TableMoviesSubtitles, TableHistoryMovie, TableShows)

# the TMDB key bundled with Bazarr (also used by the Wizdom provider), unless one is configured
_BUNDLED_TMDB_API_KEY = 'a51ee051bcd762543373903de296e0a3'
_TMDB_URL = 'https://api.themoviedb.org/3'
# after a TMDB error, don't try again for a while (a full recompute would otherwise wait on every title)
_TMDB_BACKOFF_SECONDS = 600
_tmdb_unavailable_until = 0.0


def enabled():
    return bool(settings.general.forced_only_when_available)


# a series needs forced subtitles throughout only when at least this many of its episodes were checked
MIN_EPISODES_CHECKED = 4


class ForcedNeeds:
    def __init__(self, evidence=None, spoken=None, first_search=None, searched_before=0.0, series_ratio=0.25):
        # {(title id, language): set of episode ids (series) or {None} (movies) with a forced subtitle}
        self.evidence = evidence or {}
        self.spoken = spoken or {}
        # {(title id, language): {episode id (series) or None (movies): first unsuccessful forced search timestamp}}
        self.first_search = first_search or {}
        self.searched_before = searched_before
        self.series_ratio = series_ratio

    def not_needed(self, media_id, language, episode_id=None):
        """Whether forced subtitles in this alpha2 language can be left out for this movie, or this episode of the
        series when episode_id is given."""
        key = (media_id, language)
        found = self.evidence.get(key, set())
        searched = self.first_search.get(key, {})

        if episode_id is None:
            if found:
                return False
            spoken = self.spoken.get(media_id)
            if spoken:
                return len(set(spoken)) < 2
            first = min(searched.values()) if searched else None
            return first is not None and first <= self.searched_before

        if episode_id in found:
            return False
        spoken = self.spoken.get(media_id)
        if not found and spoken and len(set(spoken)) < 2:
            return True
        first = searched.get(episode_id)
        if first is None or first > self.searched_before:
            # search every episode once (and let providers catch up during the grace period)
            return False
        checked = len(found | set(searched))
        return not (checked >= MIN_EPISODES_CHECKED and len(found) / checked >= self.series_ratio)


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

    series = media_type == 'series'
    item_column = 'sonarrEpisodeId' if series else id_column

    def item_id(row):
        return row[2] if series else None

    evidence = {}
    for row in database.execute(
            select(getattr(subtitles_table, id_column), subtitles_table.language,
                   getattr(subtitles_table, item_column))
            .where(subtitles_table.forced.is_(True), getattr(subtitles_table, id_column).in_(ids))
            .distinct()).all():
        evidence.setdefault((row[0], row[1]), set()).add(item_id(row))
    for row in database.execute(
            select(getattr(history_table, id_column), history_table.language, getattr(history_table, item_column))
            .where(history_table.language.like('%:forced'), getattr(history_table, id_column).in_(ids))
            .distinct()).all():
        evidence.setdefault((row[0], row[1].split(':')[0]), set()).add(item_id(row))

    # first time forced subtitles were searched (and not found) for each episode/movie and language
    first_search = {}
    for row in database.execute(
            select(getattr(media_table, id_column), media_table.failedAttempts, getattr(media_table, item_column))
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
                searched = first_search.setdefault((row[0], attempt[0].split(':')[0]), {})
                try:
                    searched[item_id(row)] = min(searched.get(item_id(row), float(attempt[1])), float(attempt[1]))
                except (TypeError, ValueError):
                    continue

    spoken = _spoken_languages(media_type, ids) if settings.general.forced_evidence_use_tmdb else {}
    searched_before = time.time() - max(0, int(settings.general.forced_evidence_grace_days)) * 86400
    return ForcedNeeds(evidence, spoken, first_search, searched_before,
                       series_ratio=max(0, min(100, int(settings.general.forced_series_ratio))) / 100)


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
                                    expiration_time=SHOW_EXPIRATION_TIME,
                                    should_cache_fn=lambda value: value is not None)
    except Exception:
        logging.debug('BAZARR unable to use the subtitles cache for TMDB spoken languages', exc_info=True)
        return None
