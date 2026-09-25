import time

import pytest
import requests_mock as requests_mock_module
from dogpile.cache import make_region

from subtitles.indexer import forced_evidence
from subtitles.indexer.forced_evidence import ForcedNeeds

TMDB = "https://api.themoviedb.org/3"


def test_forced_evidence_always_wins():
    needs = ForcedNeeds(evidence={(1, "en")}, spoken={1: ["en"]})
    assert not needs.not_needed(1, "en")


@pytest.mark.parametrize("spoken, expected", [
    (["en"], True),              # single spoken language: no foreign parts
    (["en", "es"], False),       # e.g. Breaking Bad
    (["de", "en", "fr", "it"], False),
])
def test_tmdb_spoken_languages_decide(spoken, expected):
    assert ForcedNeeds(spoken={1: spoken}).not_needed(1, "en") is expected


def test_without_tmdb_data_forced_is_dropped_after_the_grace_period():
    now = time.time()
    needs = ForcedNeeds(first_search={(1, "en"): now - 10 * 86400, (2, "en"): now - 86400},
                        searched_before=now - 7 * 86400)
    assert needs.not_needed(1, "en")
    assert not needs.not_needed(2, "en")
    # never searched: search it first
    assert not needs.not_needed(3, "en")


@pytest.fixture
def tmdb(monkeypatch):
    monkeypatch.setattr(forced_evidence, "region", make_region().configure("dogpile.cache.memory"))
    monkeypatch.setattr(forced_evidence, "_tmdb_unavailable_until", 0.0)
    monkeypatch.setitem(forced_evidence.settings.general, "tmdb_api_key", "")
    with requests_mock_module.Mocker() as mock:
        yield mock


def test_tmdb_tv_show_by_tvdb_id(tmdb):
    tmdb.get(f"{TMDB}/find/81189", json={"tv_results": [{"id": 1396}]})
    details = tmdb.get(f"{TMDB}/tv/1396", json={"spoken_languages": [{"iso_639_1": "en"}, {"iso_639_1": "es"}]})

    assert forced_evidence._tmdb_spoken_languages("tv", 81189) == ["en", "es"]
    # cached: TMDB isn't asked again
    assert forced_evidence._tmdb_spoken_languages("tv", 81189) == ["en", "es"]
    assert details.call_count == 1


def test_tmdb_movie_and_unknown_titles(tmdb):
    tmdb.get(f"{TMDB}/movie/310", json={"spoken_languages": [{"iso_639_1": "en"}]})
    tmdb.get(f"{TMDB}/movie/999", status_code=404)
    tmdb.get(f"{TMDB}/find/1", json={"tv_results": []})

    assert forced_evidence._tmdb_spoken_languages("movie", 310) == ["en"]
    assert forced_evidence._tmdb_spoken_languages("movie", 999) == []
    assert forced_evidence._tmdb_spoken_languages("tv", 1) == []


def test_tmdb_errors_back_off_and_are_not_cached(tmdb):
    failing = tmdb.get(f"{TMDB}/movie/310", status_code=500)

    assert forced_evidence._tmdb_spoken_languages("movie", 310) is None
    assert forced_evidence._tmdb_spoken_languages("movie", 310) is None
    assert failing.call_count == 1

    forced_evidence._tmdb_unavailable_until = 0.0
    tmdb.get(f"{TMDB}/movie/310", json={"spoken_languages": [{"iso_639_1": "en"}]})
    assert forced_evidence._tmdb_spoken_languages("movie", 310) == ["en"]


def test_disabled_leaves_everything(monkeypatch):
    monkeypatch.setitem(forced_evidence.settings.general, "forced_only_when_available", False)
    assert not forced_evidence.forced_needs("series", {1, 2}).not_needed(1, "en")


@pytest.mark.parametrize("media_type", ["series", "movie"])
def test_database_queries_run(monkeypatch, media_type):
    monkeypatch.setitem(forced_evidence.settings.general, "forced_only_when_available", True)
    monkeypatch.setitem(forced_evidence.settings.general, "forced_evidence_use_tmdb", False)
    needs = forced_evidence.forced_needs(media_type, {123456})
    assert not needs.not_needed(123456, "en")
    assert forced_evidence.has_forced_evidence(media_type, 123456, "en") is False
