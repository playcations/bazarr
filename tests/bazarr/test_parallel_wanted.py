import threading
import time
from types import SimpleNamespace

import pytest

from subliminal_patch.provider_limits import ProviderLimits, provider_limits
from subtitles.wanted import parallel


# ── provider limits ──────────────────────────────────────────────────────────


def _run_concurrently(limits, provider, count, duration=0.02):
    state = {'current': 0, 'peak': 0}
    lock = threading.Lock()

    def operation():
        with limits.slot(provider):
            with lock:
                state['current'] += 1
                state['peak'] = max(state['peak'], state['current'])
            time.sleep(duration)
            with lock:
                state['current'] -= 1

    threads = [threading.Thread(target=operation) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return state['peak']


def test_limits_disabled_do_not_restrict():
    limits = ProviderLimits()
    assert _run_concurrently(limits, "gestdown", 6) > 1
    assert limits.try_reserve("gestdown") is True


def test_default_and_override_max_in_flight():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=1, overrides=["opensubtitlescom:3"])
    assert _run_concurrently(limits, "gestdown", 6) == 1
    assert _run_concurrently(limits, "opensubtitlescom", 9) == 3


def test_min_interval_spaces_operations():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=4, overrides=["tvsubtitles:4:100"])
    starts = []

    def operation():
        with limits.slot("tvsubtitles"):
            starts.append(time.monotonic())

    threads = [threading.Thread(target=operation) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    starts.sort()
    assert all(b - a >= 0.09 for a, b in zip(starts, starts[1:]))


def test_invalid_override_is_ignored():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=2, overrides=["gestdown:x", "subdl:1"])
    assert _run_concurrently(limits, "gestdown", 6) == 2
    assert _run_concurrently(limits, "subdl", 6) == 1


def test_nested_slot_of_the_same_provider_does_not_deadlock():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=1)
    with limits.slot("addic7ed"):
        with limits.slot("addic7ed"):
            pass


def test_reservations_are_bounded():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=2)
    first, second = limits.try_reserve("subdl"), limits.try_reserve("subdl")
    assert first and second
    assert limits.try_reserve("subdl") is False
    limits.unreserve(first)
    assert limits.try_reserve("subdl")


# ── parallel Wanted runner ───────────────────────────────────────────────────


class FakeHandler:
    """Items are ids; `catalog[(item, provider)]` lists the languages that provider can fill for that item."""
    media_type = 'series'

    def __init__(self, missing, catalog, delay=0.02):
        self.missing = {item: list(languages) for item, languages in missing.items()}
        self.catalog = catalog
        self.delay = delay
        self.lock = threading.Lock()
        self.active_items = set()
        self.overlaps = []
        self.active_providers = {}
        self.peak_providers = {}
        self.peak_items = 0
        self.searches = []
        self.stamped = {}
        # (item, provider) -> subtitles saved that don't satisfy any requirement
        self.relabeled = {}

    def load(self, item_id, refresh_index=True):
        return SimpleNamespace(id=item_id, path=f"/tv/{item_id}.mkv", missing=list(self.missing[item_id]))

    @staticmethod
    def due_languages(item):
        return list(item.missing)

    def search(self, item, languages, fallback_allowed=False, only_providers=None, video_cache=None):
        (provider,) = only_providers
        with self.lock:
            if item.id in self.active_items:
                self.overlaps.append(item.id)
            self.active_items.add(item.id)
            self.peak_items = max(self.peak_items, len(self.active_items))
            self.active_providers[provider] = self.active_providers.get(provider, 0) + 1
            self.peak_providers[provider] = max(self.peak_providers.get(provider, 0), self.active_providers[provider])
            self.searches.append((item.id, provider))
        with provider_limits.slot(provider):
            time.sleep(self.delay)
        found = [x for x in self.catalog.get((item.id, provider), []) if x in languages]
        saved_without_satisfying = self.relabeled.get((item.id, provider), 0)
        with self.lock:
            for language in found:
                self.missing[item.id].remove(language)
            self.active_items.discard(item.id)
            self.active_providers[provider] -= 1
        return len(found) + saved_without_satisfying

    def stamp(self, item, languages):
        self.stamped[item.id] = list(languages)

    @staticmethod
    def item_id(row):
        return row

    @staticmethod
    def label(row):
        return str(row)


@pytest.fixture
def runner(monkeypatch):
    progress = []

    def run(handler, rows, providers, workers=8, default_limit=1, overrides=None, providers_after=None):
        calls = {'n': 0}

        def get_providers():
            calls['n'] += 1
            if providers_after and calls['n'] > providers_after[0]:
                return list(providers_after[1])
            return list(providers)

        monkeypatch.setattr(parallel, "get_providers", get_providers)
        monkeypatch.setattr(parallel, "apply_provider_limits",
                            lambda: provider_limits.configure(True, default_limit, overrides or []))
        monkeypatch.setattr(parallel.jobs_queue, "update_job_progress",
                            lambda **kwargs: progress.append(kwargs.get("progress_value")))
        monkeypatch.setattr(parallel.database, "remove", lambda: None)
        monkeypatch.setitem(parallel.settings.general, "wanted_max_active_items", workers)
        monkeypatch.setitem(parallel.settings.general, "use_whisper_fallback", False)
        try:
            return parallel.run_parallel_wanted(handler, rows, job_id=1)
        finally:
            provider_limits.configure(False)

    run.progress = progress
    return run


PROVIDERS = ["gestdown", "opensubtitlescom", "subdl", "supersubtitles"]


def test_items_progress_in_parallel_within_provider_limits(runner):
    items = list(range(24))
    handler = FakeHandler({i: ["en:hi"] for i in items},
                          {(i, "subdl"): ["en:hi"] for i in items})

    throttled = runner(handler, items, PROVIDERS)

    assert not throttled
    assert handler.overlaps == []
    assert handler.peak_items > 1
    assert all(peak <= 1 for peak in handler.peak_providers.values())
    assert all(not languages for languages in handler.missing.values())
    assert sorted(runner.progress)[-1] == len(items)


def test_item_stops_at_first_provider_with_an_acceptable_subtitle(runner):
    handler = FakeHandler({1: ["en"]}, {(1, "gestdown"): ["en"], (1, "subdl"): ["en"]})

    runner(handler, [1], PROVIDERS)

    assert handler.searches == [(1, "gestdown")]


def test_partial_results_keep_searching_only_remaining_languages(runner):
    handler = FakeHandler({1: ["en", "en:hi", "en:forced"]},
                          {(1, "gestdown"): ["en:hi"], (1, "opensubtitlescom"): ["en", "en:forced"]})

    runner(handler, [1], PROVIDERS)

    assert handler.searches == [(1, "gestdown"), (1, "opensubtitlescom")]
    assert handler.stamped == {}


def test_exhausted_item_stamps_only_remaining_languages_once(runner):
    handler = FakeHandler({1: ["en", "en:hi"]}, {(1, "subdl"): ["en:hi"]})

    runner(handler, [1], PROVIDERS)

    assert sorted(provider for _, provider in handler.searches) == sorted(PROVIDERS)
    assert handler.stamped == {1: ["en"]}


def test_no_stamp_when_a_provider_got_throttled_during_the_search(runner):
    handler = FakeHandler({1: ["en"]}, {})

    runner(handler, [1], PROVIDERS, providers_after=(3, ["gestdown", "subdl"]))

    assert handler.stamped == {}


def test_overrides_allow_more_in_flight_for_a_provider(runner):
    items = list(range(12))
    handler = FakeHandler({i: ["en"] for i in items}, {(i, "gestdown"): ["en"] for i in items}, delay=0.05)

    runner(handler, items, ["gestdown"], workers=8, overrides=["gestdown:4"])

    assert handler.peak_providers["gestdown"] == 4


def test_stops_when_all_providers_are_throttled(runner):
    handler = FakeHandler({1: ["en"]}, {})

    assert runner(handler, [1], []) is True
    assert handler.searches == []


def test_item_searched_by_another_job_is_retried_later(runner):
    handler = FakeHandler({1: ["en"], 2: ["en"]}, {(1, "gestdown"): ["en"], (2, "gestdown"): ["en"]})
    release = threading.Event()

    def other_job():
        with parallel.media_lock('series', 1):
            release.wait(1)

    thread = threading.Thread(target=other_job)
    thread.start()
    time.sleep(0.02)
    threading.Timer(0.1, release.set).start()

    runner(handler, [1, 2], PROVIDERS, workers=1)
    thread.join()

    assert (1, "gestdown") in handler.searches
    assert handler.missing[1] == []


def test_lane_statistics():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=1)
    _run_concurrently(limits, "subdl", 3, duration=0.02)
    operations, per_operation, waiting = limits.stats()["subdl"]
    assert operations == 3
    assert per_operation >= 0.02
    assert waiting > 0


def test_fast_providers_are_tried_first():
    provider_limits.configure(True, 1)
    try:
        with provider_limits.slot("supersubtitles"):
            time.sleep(0.05)
        with provider_limits.slot("gestdown"):
            pass

        name, reservation = parallel._reserve_provider(["supersubtitles", "gestdown", "subdl"])
        # never measured providers are tried first to learn their speed, then the fastest
        assert name == "subdl"
        provider_limits.unreserve(reservation)
        assert parallel._reserve_provider(["supersubtitles", "gestdown"])[0] == "gestdown"
    finally:
        provider_limits.configure(False)


def test_saved_subtitle_not_satisfying_the_language_stops_the_item(runner):
    handler = FakeHandler({1: ["en"]}, {})
    handler.relabeled[(1, "gestdown")] = 1

    runner(handler, [1], ["gestdown", "subdl", "opensubtitlescom"])

    assert handler.searches == [(1, "gestdown")]
    assert handler.stamped == {}


def test_waiting_for_a_provider_wakes_up_when_one_is_released():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=1)
    taken = limits.try_reserve("gestdown")
    released_at = []

    def release():
        time.sleep(0.05)
        released_at.append(time.monotonic())
        limits.unreserve(taken)

    threading.Thread(target=release).start()
    provider, reservation = limits.reserve_any(["gestdown"])
    assert provider == "gestdown" and reservation
    assert time.monotonic() - released_at[0] < 0.05


def test_waiting_for_a_provider_held_back_by_its_interval():
    limits = ProviderLimits()
    limits.configure(True, default_max_in_flight=2, overrides=["tvsubtitles:2:100"])
    with limits.slot("tvsubtitles"):
        pass
    started = time.monotonic()
    provider, _ = limits.reserve_any(["tvsubtitles"])
    assert provider == "tvsubtitles"
    assert 0.05 < time.monotonic() - started < 0.5
