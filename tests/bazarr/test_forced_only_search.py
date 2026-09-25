import time

import pytest

from subtitles import adaptive_searching
from subtitles.adaptive_searching import filter_forced_only_languages

DAY = 86400


@pytest.fixture
def days(monkeypatch):
    def set_days(value):
        monkeypatch.setitem(adaptive_searching.settings.general, "forced_only_search_days", value)
    return set_days


def _attempts(*entries):
    return str([list(entry) for entry in entries])


def test_every_search_keeps_legacy_behavior(days):
    days(0)
    assert filter_forced_only_languages(["en:forced"], _attempts(("en:forced", time.time()))) == ["en:forced"]


def test_forced_searched_with_other_languages(days):
    days(30)
    languages = ["en:forced", "en"]
    assert filter_forced_only_languages(languages, _attempts(("en:forced", time.time()))) == languages


def test_forced_only_skipped_when_searched_recently(days):
    days(30)
    assert filter_forced_only_languages(["en:forced"], _attempts(("en:forced", time.time() - 2 * DAY))) == []


def test_forced_only_searched_again_after_the_interval(days):
    days(7)
    attempts = _attempts(("en:forced", time.time() - 40 * DAY), ("en:forced", time.time() - 8 * DAY))
    assert filter_forced_only_languages(["en:forced"], attempts) == ["en:forced"]


def test_never_searched_forced_is_searched_once(days):
    days(-1)
    assert filter_forced_only_languages(["en:forced"], None) == ["en:forced"]
    assert filter_forced_only_languages(["en:forced"], _attempts(("en", time.time()))) == ["en:forced"]
    assert filter_forced_only_languages(["en:forced"], _attempts(("en:forced", time.time() - 400 * DAY))) == []


def test_malformed_attempts_search(days):
    days(30)
    assert filter_forced_only_languages(["en:forced"], "not a list") == ["en:forced"]
