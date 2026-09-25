import pytest
import requests_mock as requests_mock_module
from dogpile.cache import make_region

from subtitles.indexer import forced_evidence
from subtitles.indexer.forced_evidence import ForcedNeeds

TMDB = "https://api.themoviedb.org/3"


OLD = 0.0          # searched long before the grace period
NOW = 10 ** 10     # searched too recently


def _series(found, searched, spoken=None, ratio=0.25):
    """Series 1: episodes with forced subtitles, {episode: first unsuccessful search}."""
    return ForcedNeeds(evidence={(1, "en"): set(found)} if found else {},
                       first_search={(1, "en"): dict(searched)},
                       spoken={1: spoken} if spoken else {}, searched_before=1.0, series_ratio=ratio)


def test_single_language_series_without_forced_subtitles_doesnt_want_them():
    needs = _series(found=[], searched={}, spoken=["en"])
    assert needs.not_needed(1, "en", episode_id=5)


def test_every_episode_is_searched_once_first():
    needs = _series(found=[1], searched={2: OLD}, spoken=["en", "es"])
    assert not needs.not_needed(1, "en", episode_id=3)          # never searched
    assert not _series(found=[1], searched={3: NOW}).not_needed(1, "en", episode_id=3)  # grace period


def test_series_with_forced_in_a_single_episode_only_keeps_that_one():
    # e.g. Arrested Development: 1 forced episode out of 84
    needs = _series(found=[1], searched={e: OLD for e in range(2, 85)}, spoken=["en", "es"])
    assert needs.not_needed(1, "en", episode_id=40)


def test_series_needing_forced_throughout_keeps_wanting_them():
    # e.g. Breaking Bad: 23 of 62 episodes have forced subtitles (37%)
    needs = _series(found=range(1, 24), searched={e: OLD for e in range(24, 63)}, spoken=["en", "de", "es"])
    assert not needs.not_needed(1, "en", episode_id=40)
    # with a stricter threshold it doesn't
    assert _series(found=range(1, 24), searched={e: OLD for e in range(24, 63)}, ratio=0.5).not_needed(
        1, "en", episode_id=40)


def test_too_few_checked_episodes_to_judge_a_series():
    needs = _series(found=[1], searched={2: OLD}, spoken=["en", "es"])
    assert needs.not_needed(1, "en", episode_id=2)


def test_forced_subtitles_found_in_a_single_language_series_count():
    needs = _series(found=[1, 2, 3], searched={4: OLD}, spoken=["en"])
    assert not needs.not_needed(1, "en", episode_id=4)


@pytest.mark.parametrize("spoken, expected", [(["en"], True), (["en", "es"], False)])
def test_movies_follow_tmdb_spoken_languages(spoken, expected):
    assert ForcedNeeds(spoken={7: spoken}).not_needed(7, "en") is expected


def test_movies_with_forced_subtitles_or_searched_recently_keep_wanting_them():
    assert not ForcedNeeds(evidence={(7, "en"): {None}}, spoken={7: ["en"]}).not_needed(7, "en")
    needs = ForcedNeeds(first_search={(7, "en"): {None: 5.0}, (8, "en"): {None: NOW}}, searched_before=10.0)
    assert needs.not_needed(7, "en")
    assert not needs.not_needed(8, "en")
    assert not needs.not_needed(9, "en")


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

    def lookup(kind, external_id):
        calls.append(external_id)
        return None

    monkeypatch.setattr(forced_evidence, "_tmdb_spoken_languages", lookup)
    monkeypatch.setattr(forced_evidence.database, "execute",
                        lambda stmt: type("R", (), {"all": lambda self: [(1, 11), (2, 22), (3, 33)]})())
    assert forced_evidence._spoken_languages("movie", {1, 2, 3}) == {}
    assert len(calls) == 1


def test_disabled_leaves_everything(monkeypatch):
    monkeypatch.setitem(forced_evidence.settings.general, "forced_only_when_available", False)
    assert not forced_evidence.forced_needs("series", {1, 2}).not_needed(1, "en")


@pytest.mark.parametrize("media_type", ["series", "movie"])
def test_database_queries_run(monkeypatch, media_type):
    monkeypatch.setitem(forced_evidence.settings.general, "forced_only_when_available", True)
    monkeypatch.setitem(forced_evidence.settings.general, "forced_evidence_use_tmdb", False)
    monkeypatch.setitem(forced_evidence.settings.general, "forced_series_ratio", 25)
    needs = forced_evidence.forced_needs(media_type, {123456})
    assert not needs.not_needed(123456, "en", episode_id=1 if media_type == "series" else None)
