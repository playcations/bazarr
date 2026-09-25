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
