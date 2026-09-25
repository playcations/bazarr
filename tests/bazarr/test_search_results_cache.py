import threading

import pytest
from dogpile.cache import make_region
from subliminal.video import Episode
from subliminal_patch import core
from subliminal_patch.core import SZProviderPool, search_results_cache
from subliminal_patch.subtitle import Subtitle
from subzero.language import Language


class FakeSubtitle(Subtitle):
    provider_name = "fake"

    def __init__(self, sub_id):
        super().__init__(Language("eng"))
        self.sub_id = sub_id

    @property
    def id(self):
        return self.sub_id


class FakeProvider:
    languages = {Language("eng"), Language("fra")}
    video_types = (Episode,)
    calls = 0

    def __init__(self, **kwargs):
        pass

    @classmethod
    def check(cls, video):
        return True

    def initialize(self):
        pass

    def terminate(self):
        pass

    def list_subtitles(self, video, languages):
        type(self).calls += 1
        return [FakeSubtitle(f"sub-{type(self).calls}")]


@pytest.fixture
def pool(monkeypatch):
    region = make_region(key_mangler=lambda key: key).configure("dogpile.cache.memory")
    monkeypatch.setattr(core, "region", region)
    monkeypatch.setattr("subliminal_patch.core.provider_registry", {"fake": FakeProvider})
    FakeProvider.calls = 0
    search_results_cache.configure(24)
    yield SZProviderPool(providers=["fake"])
    search_results_cache.configure(0)


def _episode(name="/tv/Show.S01E01.mkv"):
    return Episode(name, "Show", 1, 1)


def _list(pool, video=None, languages=None):
    return pool.list_subtitles(video or _episode(), languages or {Language("eng")})


def test_disabled_cache_always_asks_the_provider(pool):
    search_results_cache.configure(0)
    _list(pool)
    _list(pool)
    assert FakeProvider.calls == 2


def test_same_search_is_answered_from_the_cache(pool):
    first = _list(pool)
    second = _list(pool)

    assert FakeProvider.calls == 1
    assert [s.id for s in second] == [s.id for s in first]
    # callers get copies: changing them doesn't change the cached results
    second[0].sub_id = "changed"
    assert _list(pool)[0].id == "sub-1"


def test_different_file_or_languages_or_settings_search_again(pool):
    _list(pool)
    _list(pool, video=_episode("/tv/Show.S01E01.REPACK.mkv"))
    _list(pool, languages={Language("fra")})
    pool.provider_configs["fake"] = {"include_ai_translated": True}
    _list(pool)
    assert FakeProvider.calls == 4


def test_bypass_searches_again_and_refreshes_the_cache(pool):
    _list(pool)
    with search_results_cache.bypass():
        assert _list(pool)[0].id == "sub-2"
    assert _list(pool)[0].id == "sub-2"
    assert FakeProvider.calls == 2


def test_clear_makes_cached_results_unreachable(pool):
    _list(pool)
    search_results_cache.clear()
    _list(pool)
    assert FakeProvider.calls == 2


def test_file_backend_is_safe_with_concurrent_writes(tmp_path):
    from subzero.cache_backends.file import SZFileBackend

    backend = SZFileBackend({"appname": "test_cache", "app_cache_dir": str(tmp_path)})
    errors = []

    def write(start):
        try:
            for i in range(start, start + 200):
                backend.set(f"key-{i}", i)
                if i % 20 == 0:
                    backend.sync()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=write, args=(n * 1000,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    backend.sync(force=True)

    assert errors == []
    assert backend.get("key-3199") == 3199


def test_file_backend_flushes_buffered_writes_by_itself(tmp_path, monkeypatch):
    import os

    from subzero.cache_backends import file as file_backend

    monkeypatch.setattr(file_backend, "FLUSH_EVERY_ENTRIES", 5)
    backend = file_backend.SZFileBackend({"appname": "flush_cache", "app_cache_dir": str(tmp_path)})
    cache_dir = backend._cache.cache_dir
    for i in range(4):
        backend.set(f"key-{i}", i)
    assert len(os.listdir(cache_dir)) == 0

    backend.set("key-4", 4)
    assert len(os.listdir(cache_dir)) == 5


SRT = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"


class DownloadProvider(FakeProvider):
    """'gone' downloads return nothing (removed subtitle), 'flaky' raises a connection error, others work."""
    downloads = []

    def list_subtitles(self, video, languages):
        return [FakeSubtitle(sub_id) for sub_id in ("gone", "flaky", "good")]

    def download_subtitle(self, subtitle):
        type(self).downloads.append(subtitle.id)
        if subtitle.id == "flaky":
            import requests

            raise requests.ConnectionError("timeout")
        subtitle.content = None if subtitle.id == "gone" else SRT


def _download_best(pool, candidates):
    return [s.id for s in pool.download_best_subtitles(candidates, _episode(), {Language("eng")})]


@pytest.fixture
def download_pool(pool, monkeypatch):
    monkeypatch.setattr("subliminal_patch.core.provider_registry", {"fake": DownloadProvider})
    monkeypatch.setattr("subliminal_patch.core.DOWNLOAD_TRIES", 1, raising=False)
    DownloadProvider.downloads = []
    return pool


def _candidates(*ids):
    subtitles = []
    for sub_id in ids:
        subtitle = FakeSubtitle(sub_id)
        subtitle.get_matches = lambda video: {"series", "season", "episode"}
        subtitles.append(subtitle)
    return subtitles


def test_removed_subtitle_is_not_downloaded_again(download_pool):
    assert _download_best(download_pool, _candidates("gone", "good")) == ["good"]
    assert _download_best(download_pool, _candidates("gone", "good")) == ["good"]
    assert DownloadProvider.downloads.count("gone") == 1


def test_manual_search_retries_a_failed_download(download_pool):
    _download_best(download_pool, _candidates("gone", "good"))
    with search_results_cache.bypass():
        _download_best(download_pool, _candidates("gone", "good"))
    assert DownloadProvider.downloads.count("gone") == 2


def test_connection_errors_are_not_remembered(download_pool):
    assert not search_results_cache.failed_download(_candidates("flaky")[0])
    download_pool.download_subtitle(_candidates("flaky")[0])
    assert not search_results_cache.failed_download(_candidates("flaky")[0])


def test_failed_downloads_arent_remembered_when_search_results_arent_reused(download_pool):
    search_results_cache.configure(0)
    _download_best(download_pool, _candidates("gone", "good"))
    _download_best(download_pool, _candidates("gone", "good"))
    assert DownloadProvider.downloads.count("gone") == 2


def test_archive_retention_is_configured_with_the_cache():
    try:
        search_results_cache.configure(24, archive_days=4)
        assert search_results_cache.archive_ttl == 4 * 86400
    finally:
        search_results_cache.configure(0)
