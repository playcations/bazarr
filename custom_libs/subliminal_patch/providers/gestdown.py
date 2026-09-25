# -*- coding: utf-8 -*-

import logging
import threading
import time

from requests import JSONDecodeError
from requests import Session
from subliminal.score import get_equivalent_release_groups
from subliminal.utils import sanitize_release_group
from subliminal_patch.core import Episode
from subliminal_patch.language import PatchedAddic7edConverter
from subliminal_patch.providers import Provider
from subliminal_patch.providers.utils import update_matches
from subliminal.exceptions import DownloadLimitExceeded
from subliminal_patch.exceptions import TooManyRequests
from subliminal_patch.subtitle import Subtitle
from subzero.language import Language

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.gestdown.info"
# show lookups rarely change; season listings are refreshed regularly by Gestdown
_SHOW_TTL = 24 * 3600
_SEASON_TTL = 3600
_MAX_CACHE_ENTRIES = 5000
# longest Retry-After waited for inline instead of throttling the provider
_MAX_INLINE_WAIT = 10


class GestdownSubtitle(Subtitle):
    provider_name = "gestdown"
    hash_verifiable = False
    hearing_impaired_verifiable = True

    def __init__(self, language, data: dict, tvdbid_matching: bool = False):
        super().__init__(language, hearing_impaired=data["hearingImpaired"])
        self.page_link = _BASE_URL + data["downloadUri"]
        self._id = data["subtitleId"]
        self.releases = [v.strip() for v in data["version"].split(",")]
        self.qualities = data.get("qualities") or []
        self.release_info = "\n".join(self.releases)
        self.matches = set()
        self.tvDbId_matching = tvdbid_matching

    def get_matches(self, video):
        self.matches = {"title", "series", "season", "episode", "tvdb_id"}

        update_matches(self.matches, video, self.release_info)

        # release_group
        if (
            "release_group" not in self.matches
            and video.release_group
            and self.releases
        ):
            video_release_groups = get_equivalent_release_groups(
                sanitize_release_group(video.release_group)
            )
            for release in self.releases:
                if any(
                    r in sanitize_release_group(release) for r in video_release_groups
                ):
                    self.matches.add("release_group")
                    break

        # resolution
        if video.resolution and self.qualities and video.resolution in self.qualities:
            self.matches.add("resolution")

        # year
        if self.tvDbId_matching:
            self.matches.add("year")

        return self.matches

    @property
    def id(self):
        return self._id


class GestdownProvider(Provider):
    provider_name = "gestdown"

    video_types = (Episode,)

    # fmt: off
    languages = {Language('por', 'BR')} | {Language(l) for l in [
        'ara', 'aze', 'ben', 'bos', 'bul', 'cat', 'ces', 'dan', 'deu', 'ell', 'eng', 'eus', 'fas', 'fin', 'fra', 'glg',
        'heb', 'hrv', 'hun', 'hye', 'ind', 'ita', 'jpn', 'kor', 'mkd', 'msa', 'nld', 'nor', 'pol', 'por', 'ron', 'rus',
        'slk', 'slv', 'spa', 'sqi', 'srp', 'swe', 'tha', 'tur', 'ukr', 'vie', 'zho'
    ]} | {Language.fromietf(l) for l in ["sr-Latn", "sr-Cyrl"]}
    languages.update(set(Language.rebuild(l, hi=True) for l in languages))
    # fmt: on

    _converter = PatchedAddic7edConverter()

    def __init__(self):
        # The instance is shared by concurrent searches and lives across Wanted runs: shows and whole season
        # listings are cached so the other episodes of a season don't need any listing request.
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._fetch_locks = {}

    def initialize(self):
        self._session = Session()
        self._session.headers.update({"User-Agent": "Bazarr"})

    def terminate(self):
        self._session.close()

    def _cached(self, key, ttl, fetch):
        """Return the cached value for key or fetch it once, even when several threads ask for it together."""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry and entry[1] > time.monotonic():
                return entry[0]
            lock = self._fetch_locks.setdefault(key, threading.Lock())
        with lock:
            with self._cache_lock:
                entry = self._cache.get(key)
                if entry and entry[1] > time.monotonic():
                    return entry[0]
            value = fetch()
            with self._cache_lock:
                self._cache[key] = (value, time.monotonic() + ttl)
                if len(self._cache) > _MAX_CACHE_ENTRIES:
                    now = time.monotonic()
                    for stale in [k for k, (_, expires) in self._cache.items() if expires <= now]:
                        self._cache.pop(stale, None)
                        self._fetch_locks.pop(stale, None)
            return value

    def _get(self, url, download=False):
        """GET an API url, handling Gestdown's rate limiting (429 + Retry-After)."""
        for attempt in range(2):
            response = self._session.get(url, allow_redirects=True, timeout=30)
            if response.status_code != 429:
                return response

            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after is not None else None
            except ValueError:
                wait = None
            if download and wait is None:
                # not the rate limiter: Gestdown's own Addic7ed accounts are out of downloads
                raise DownloadLimitExceeded("Gestdown download limit reached")
            if attempt == 0 and wait is not None and wait <= _MAX_INLINE_WAIT:
                logger.debug("Gestdown rate limit reached, waiting %s seconds", wait)
                time.sleep(wait)
                continue
            error = TooManyRequests(f"Gestdown rate limit reached (Retry-After: {retry_after})")
            error.retry_after = wait
            raise error
        return response

    def _search_show(self, video):
        def fetch():
            response = self._get(f"{_BASE_URL}/shows/external/tvdb/{video.series_tvdb_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            try:
                return response.json()["shows"]
            except (JSONDecodeError, KeyError):
                logger.debug("Couldn't get shows from JSON for %s", video)
                return None

        return self._cached(("show", video.series_tvdb_id), _SHOW_TTL, fetch)

    def _season(self, show_id, season, lang):
        """{episode number: [subtitle dicts]} for a whole season in one request."""
        def fetch():
            response = self._get(f"{_BASE_URL}/shows/{show_id}/{season}/{lang}")
            if response.status_code in (404, 423):
                return {}
            response.raise_for_status()
            try:
                episodes = response.json()["episodes"]
            except (JSONDecodeError, KeyError, TypeError):
                logger.debug("Couldn't get the season listing for show %s season %s", show_id, season)
                return {}
            return {episode.get("number"): episode.get("subtitles") or [] for episode in episodes
                    if episode.get("season") == season}

        return self._cached(("season", show_id, season, lang), _SEASON_TTL, fetch)

    def _episode(self, show_id, season, episode, lang):
        """Per-episode search, only when the season listing doesn't know the episode (it makes Gestdown refresh it
        from Addic7ed). Misses are remembered for the season listing's lifetime."""
        def fetch():
            response = self._get(f"{_BASE_URL}/subtitles/get/{show_id}/{season}/{episode}/{lang}")
            if response.status_code in (404, 423):
                return []
            if response.status_code >= 500:
                # this endpoint refreshes the episode from Addic7ed and sometimes fails: a miss for this episode,
                # not a reason to stop using the provider
                logger.debug("Gestdown returned %s for show %s S%sE%s", response.status_code, show_id, season,
                             episode)
                return []
            response.raise_for_status()
            try:
                return response.json()["matchingSubtitles"] or []
            except (JSONDecodeError, KeyError):
                logger.debug("Couldn't get matching subtitles for show %s S%sE%s", show_id, season, episode)
                return []

        return self._cached(("episode", show_id, season, episode, lang), _SEASON_TTL, fetch)

    def list_subtitles(self, video, languages):
        shows = self._search_show(video)
        if not shows:
            logger.debug("Couldn't find the show")
            return []

        # regular and hearing-impaired subtitles come in the same response, so each language is requested once
        base_languages = {}
        for language in languages:
            base_languages.setdefault(language.basename, Language.rebuild(language, hi=False, forced=False))

        subtitles = []
        for language in base_languages.values():
            lang = self._converter.convert(language.alpha3)
            for show in shows:
                season_listing = self._season(show["id"], video.season, lang)
                subtitle_dicts = season_listing.get(video.episode)
                if not subtitle_dicts:
                    subtitle_dicts = self._episode(show["id"], video.season, video.episode, lang)
                if not subtitle_dicts:
                    continue

                tvdbid_matching = bool(video.series_tvdb_id and show.get("tvDbId") == video.series_tvdb_id)
                for subtitle_dict in subtitle_dicts:
                    if not subtitle_dict.get("completed"):
                        continue
                    sub = GestdownSubtitle(language, subtitle_dict, tvdbid_matching)
                    logger.debug("Found subtitle: %s", sub)
                    subtitles.append(sub)
                # the first show with subtitles is the right one
                break

        return subtitles

    def download_subtitle(self, subtitle: GestdownSubtitle):
        response = self._get(subtitle.page_link, download=True)
        if response.status_code == 404 or response.status_code >= 500:
            # a subtitle that disappeared or failed fails this download only; the next candidate is tried
            logger.warning("Gestdown returned %s when downloading %s", response.status_code, subtitle.id)
            return
        response.raise_for_status()
        subtitle.content = response.content
