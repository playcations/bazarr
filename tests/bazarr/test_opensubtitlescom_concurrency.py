import threading
from types import SimpleNamespace

from subliminal.video import Episode
from subliminal_patch.providers.opensubtitlescom import OpenSubtitlesComProvider
from subzero.language import Language


def _item(season, episode, imdb):
    return {"attributes": {
        "language": "en", "foreign_parts_only": False, "hearing_impaired": False, "url": "", "release": "Show.WEB",
        "uploader": {"name": "u"}, "files": [{"file_id": season * 100 + episode}],
        "feature_details": {"season_number": season, "episode_number": episode, "year": 2020, "movie_name": "Show",
                            "parent_imdb_id": imdb, "imdb_id": None},
    }}


def test_concurrent_queries_use_their_own_video(monkeypatch):
    provider = OpenSubtitlesComProvider(username="u", password="p", use_hash=False, api_key="k")
    provider.server_hostname = "api.opensubtitles.com"
    both_waiting = threading.Barrier(2)

    def fake_retry(func, amount=None):
        return func()

    def fake_checked(func, **kwargs):
        response = func()
        # make both searches send their request before either parses its response
        both_waiting.wait(2)
        return response

    def fake_get(url, params, timeout):
        values = dict(params)
        data = [_item(values["season_number"], values["episode_number"], values["parent_imdb_id"])]
        return SimpleNamespace(json=lambda: {"data": data})

    monkeypatch.setattr(provider, "retry", fake_retry)
    monkeypatch.setattr(provider, "checked", fake_checked)
    monkeypatch.setattr(provider.session, "get", fake_get)

    first = Episode("/tv/A.S01E01.mkv", "A", 1, 1, series_imdb_id="tt0000111")
    second = Episode("/tv/B.S05E09.mkv", "B", 5, 9, series_imdb_id="tt0000222")
    results = {}

    def search(name, video):
        results[name] = provider.query({Language("eng")}, video)

    threads = [threading.Thread(target=search, args=("first", first)),
               threading.Thread(target=search, args=("second", second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for name, video in (("first", first), ("second", second)):
        (subtitle,) = results[name]
        assert (subtitle.season, subtitle.episode) == (video.season, video.episode)
        assert subtitle.imdb_match
        assert {"season", "episode"} <= subtitle.matches
