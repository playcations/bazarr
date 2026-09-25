import ast
from types import SimpleNamespace

import pytest

from subtitles.wanted import movies as wanted_movies
from subtitles.wanted import series as wanted_series


def _stamped_attempts(executed):
    assert len(executed) == 1
    return ast.literal_eval(executed[0].compile().params["failedAttempts"])


@pytest.fixture
def episode():
    return SimpleNamespace(path="/tv/Show/S01E01.mkv", missing_subtitles="['en', 'fr']", sonarrEpisodeId=1,
                           sonarrSeriesId=1, audio_language="[]", sceneName=None, failedAttempts=None,
                           title="Show", profileId=1)


@pytest.fixture
def movie():
    return SimpleNamespace(path="/movies/Movie.mkv", missing_subtitles="['en', 'fr']", radarrId=1,
                           audio_language="[]", sceneName=None, failedAttempts=None, title="Movie", profileId=1)


@pytest.fixture
def executed(monkeypatch):
    statements = []
    for module in (wanted_series, wanted_movies):
        monkeypatch.setattr(module, "generate_subtitles", lambda *args, **kwargs: iter(()))
        monkeypatch.setattr(module, "get_audio_profile_languages", lambda *args, **kwargs: [])
        monkeypatch.setattr(module.database, "execute", statements.append)
    return statements


@pytest.mark.parametrize("module, item, wanted", [
    (wanted_series, "episode", wanted_series._wanted_episode),
    (wanted_movies, "movie", wanted_movies._wanted_movie),
])
def test_every_searched_language_is_stamped(request, monkeypatch, executed, module, item, wanted):
    monkeypatch.setattr(module, "get_providers", lambda: ["opensubtitlescom"])

    wanted(request.getfixturevalue(item), ["opensubtitlescom"])

    assert sorted(x[0] for x in _stamped_attempts(executed)) == ["en", "fr"]


@pytest.mark.parametrize("module, item, wanted", [
    (wanted_series, "episode", wanted_series._wanted_episode),
    (wanted_movies, "movie", wanted_movies._wanted_movie),
])
def test_existing_attempts_are_kept_for_every_language(request, monkeypatch, executed, module, item, wanted):
    monkeypatch.setattr(module, "get_providers", lambda: ["opensubtitlescom"])
    media = request.getfixturevalue(item)
    media.failedAttempts = "[['en', 1000.0], ['fr', 1000.0]]"

    wanted(media, ["opensubtitlescom"])

    attempts = _stamped_attempts(executed)
    for language in ("en", "fr"):
        timestamps = sorted(x[1] for x in attempts if x[0] == language)
        assert len(timestamps) == 2
        assert timestamps[0] == 1000.0


@pytest.mark.parametrize("module, item, wanted", [
    (wanted_series, "episode", wanted_series._wanted_episode),
    (wanted_movies, "movie", wanted_movies._wanted_movie),
])
@pytest.mark.parametrize("available", [["opensubtitlescom"], None])
def test_no_stamp_when_a_provider_got_throttled_during_search(request, monkeypatch, executed, module, item, wanted,
                                                              available):
    monkeypatch.setattr(module, "get_providers", lambda: available)

    wanted(request.getfixturevalue(item), ["opensubtitlescom", "subdl"])

    assert executed == []


@pytest.mark.parametrize("module, item, wanted", [
    (wanted_series, "episode", wanted_series._wanted_episode),
    (wanted_movies, "movie", wanted_movies._wanted_movie),
])
def test_no_stamp_when_something_was_found(request, monkeypatch, executed, module, item, wanted):
    monkeypatch.setattr(module, "get_providers", lambda: ["opensubtitlescom"])
    monkeypatch.setattr(module, "generate_subtitles",
                        lambda *args, **kwargs: iter([SimpleNamespace(message="downloaded")]))
    for name in ("store_subtitles", "store_subtitles_movie", "history_log", "history_log_movie",
                 "send_notifications", "send_notifications_movie", "event_stream"):
        monkeypatch.setattr(module, name, lambda *args, **kwargs: None, raising=False)

    wanted(request.getfixturevalue(item), ["opensubtitlescom"])

    assert executed == []
