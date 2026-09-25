import datetime
import os
import threading
import time

import pytest

from app import get_providers
from subliminal_patch.core import SZProviderPool


def test_throttled_providers_parse_round_trip():
    tp = {
        "opensubtitlescom": ("TooManyRequests", datetime.datetime(2026, 9, 24, 16, 5, 3, 123456), "1 minute"),
        "subdl": ("APIThrottled", datetime.datetime(2026, 9, 25), "15 minutes"),
    }
    assert get_providers._parse_throttled_providers(str(tp)) == tp
    assert get_providers._parse_throttled_providers("") == {}
    assert get_providers._parse_throttled_providers("{}") == {}


@pytest.mark.parametrize("payload", [
    "__import__('os').system('true')",
    "{'x': ('a', open('/etc/passwd'), 'b')}",
    "{'x': ('a', datetime.datetime(2026, 1, 1, tzinfo=__import__('os')), 'b')}",
])
def test_throttled_providers_parse_rejects_code(payload):
    with pytest.raises((ValueError, SyntaxError)):
        get_providers._parse_throttled_providers(payload)


def test_set_throttled_providers_replaces_file_atomically(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(get_providers.args, "config_dir", str(tmp_path))
    path = tmp_path / "config" / "throttled_providers.dat"
    path.write_text("{}")
    os.chmod(path, 0o644)

    get_providers.set_throttled_providers("{'subdl': ('APIThrottled', datetime.datetime(2026, 9, 25), '1 day')}")

    assert get_providers.get_throttled_providers() == {
        "subdl": ("APIThrottled", datetime.datetime(2026, 9, 25), "1 day")}
    assert os.stat(path).st_mode & 0o777 == 0o644
    assert [p.name for p in (tmp_path / "config").iterdir()] == ["throttled_providers.dat"]


def test_throttled_count_is_consistent_across_threads(monkeypatch):
    monkeypatch.setattr(get_providers.time, "sleep", lambda seconds: None)
    get_providers.throttle_count.clear()
    results = []

    def strike():
        results.append(get_providers.throttled_count("provider"))

    threads = [threading.Thread(target=strike) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    get_providers.throttle_count.clear()

    # every 5th strike applies a throttle and starts a new count
    assert results.count(True) == 10


class _SlowProvider:
    initialized = 0

    def __init__(self, **kwargs):
        pass

    def initialize(self):
        time.sleep(0.05)
        type(self).initialized += 1

    def terminate(self):
        pass


def test_provider_is_initialized_once_when_requested_concurrently(monkeypatch):
    monkeypatch.setattr("subliminal_patch.core.provider_registry", {"slow": _SlowProvider})
    _SlowProvider.initialized = 0
    pool = SZProviderPool(providers=["slow"])
    instances = []

    threads = [threading.Thread(target=lambda: instances.append(pool["slow"])) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert _SlowProvider.initialized == 1
    assert len({id(instance) for instance in instances}) == 1

    del pool["slow"]
    assert "slow" not in pool.initialized_providers


class _HTTPError(Exception):
    def __init__(self, headers):
        super().__init__("429 Client Error: Too Many Requests")
        self.response = type("Response", (), {"headers": headers})()


@pytest.mark.parametrize("exception, expected", [
    (_HTTPError({"Retry-After": "120"}), 120),
    (_HTTPError({"Retry-After": "1"}), 30),
    (_HTTPError({"Retry-After": "999999"}), 86400),
    (_HTTPError({}), None),
    (_HTTPError({"Retry-After": "soon"}), None),
    (type("E", (Exception,), {"retry_after": 300})(), 300),
])
def test_retry_after(exception, expected):
    delta = get_providers._retry_after(exception)
    assert (delta.total_seconds() if delta else None) == expected


def test_retry_after_http_date():
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
    header = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    delta = get_providers._retry_after(_HTTPError({"Retry-After": header}))
    assert 550 < delta.total_seconds() <= 600
