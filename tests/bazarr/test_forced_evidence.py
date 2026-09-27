import pytest
import requests_mock as requests_mock_module
from dogpile.cache import make_region

from subtitles.indexer import forced_evidence
from subtitles.indexer.forced_evidence import ForcedNeeds

TMDB = "https://api.themoviedb.org/3"


OLD = 0.0          # searched long before the grace period
NOW = 10 ** 10     # searched too recently


def _series(found, searched, spoken=None):
    """Series 1: episodes with forced subtitles, {episode: first unsuccessful search}."""
    return ForcedNeeds(evidence={(1, "en"): set(found)} if found else {},
                       first_search={(1, "en"): dict(searched)},
                       spoken={1: spoken} if spoken else {}, searched_before=1.0)


def test_single_language_series_without_forced_subtitles_doesnt_want_them():
    needs = _series(found=[], searched={}, spoken=["en"])
    assert needs.not_needed(1, "en", episode_id=5)


def test_every_episode_is_searched_once_first():
    needs = _series(found=[1], searched={2: OLD}, spoken=["en", "es"])
    assert not needs.not_needed(1, "en", episode_id=3)          # never searched
    assert not _series(found=[1], searched={3: NOW}).not_needed(1, "en", episode_id=3)  # grace period


def test_episodes_keep_forced_subtitles_only_where_found():
    # e.g. Breaking Bad: 23 of 62 episodes have forced subtitles, the other episodes were searched without result
    needs = _series(found=range(1, 24), searched={e: OLD for e in range(24, 63)}, spoken=["en", "de", "es"])
    assert not needs.not_needed(1, "en", episode_id=10)
    assert needs.not_needed(1, "en", episode_id=40)


def test_forced_subtitles_found_in_a_single_language_series_count():
    needs = _series(found=[1, 2, 3], searched={4: NOW}, spoken=["en"])
    assert not needs.not_needed(1, "en", episode_id=1)
    # TMDB is wrong about this series, so its other episodes are searched once too
    assert not needs.not_needed(1, "en", episode_id=4)
    assert not needs.not_needed(1, "en", episode_id=5)


def test_single_language_movie_doesnt_want_forced_subtitles():
    assert ForcedNeeds(spoken={7: ["en"]}).not_needed(7, "en")


def test_movies_are_searched_once():
    needs = ForcedNeeds(first_search={(7, "en"): {None: 5.0}, (8, "en"): {None: NOW}}, spoken={7: ["en", "es"]},
                        searched_before=10.0)
    assert needs.not_needed(7, "en")           # several spoken languages, searched without result
    assert not needs.not_needed(8, "en")       # grace period
    assert not needs.not_needed(9, "en")       # never searched


def test_movies_with_forced_subtitles_keep_wanting_them():
    assert not ForcedNeeds(evidence={(7, "en"): {None}}, spoken={7: ["en"]},
                           first_search={(7, "en"): {None: 5.0}}, searched_before=10.0).not_needed(7, "en")


@pytest.fixture
def tmdb(monkeypatch):
    monkeypatch.setattr(forced_evidence, "region", make_region().configure("dogpile.cache.memory"))
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


def test_tmdb_errors_are_not_cached(tmdb):
    tmdb.get(f"{TMDB}/movie/310", [{"status_code": 500},
                                   {"json": {"spoken_languages": [{"iso_639_1": "en"}]}}])

    assert forced_evidence._tmdb_spoken_languages("movie", 310) is None
    assert forced_evidence._tmdb_spoken_languages("movie", 310) == ["en"]


def test_a_recompute_stops_asking_tmdb_after_an_error(tmdb, monkeypatch):
    calls = []

    def lookup(kind, external_id, session=None):
        calls.append(external_id)
        return None

    monkeypatch.setattr(forced_evidence, "_tmdb_spoken_languages", lookup)
    monkeypatch.setattr(forced_evidence.database, "execute",
                        lambda stmt: type("R", (), {"all": lambda self: [(1, 11), (2, 22), (3, 33)]})())
    monkeypatch.setattr(forced_evidence.region, "backend", type("B", (), {"sync": lambda self: None})(),
                        raising=False)
    assert forced_evidence._spoken_languages("movie", {1, 2, 3}) == {}
    assert len(calls) == 1


def test_disabled_leaves_everything(monkeypatch):
    monkeypatch.setitem(forced_evidence.settings.general, "forced_only_when_available", False)
    assert not forced_evidence.forced_needs("series", {1, 2}).not_needed(1, "en")


@pytest.mark.parametrize("media_type", ["series", "movie"])
def test_database_queries_run(monkeypatch, media_type):
    monkeypatch.setitem(forced_evidence.settings.general, "forced_only_when_available", True)
    monkeypatch.setitem(forced_evidence.settings.general, "forced_evidence_use_tmdb", False)
    needs = forced_evidence.forced_needs(media_type, {123456})
    assert not needs.not_needed(123456, "en", episode_id=1 if media_type == "series" else None)
