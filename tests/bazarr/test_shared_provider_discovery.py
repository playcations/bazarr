from types import SimpleNamespace

import pytest
from subliminal.video import Movie
from subliminal_patch.core import SZProviderPool
from subliminal_patch.subtitle import Subtitle
from subzero.language import Language

from subtitles import download
from subtitles import pool as pool_module

SRT = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"

EN = Language("eng")
EN_HI = Language("eng", hi=True)
EN_FORCED = Language("eng", forced=True)
FR = Language("fra")


class FakeSubtitle(Subtitle):
    provider_name = "fake"

    def __init__(self, language, sub_id, matches):
        super().__init__(language, hearing_impaired=bool(language.hi))
        self.sub_id = sub_id
        self._matches = matches

    @property
    def id(self):
        return self.sub_id

    def get_matches(self, video):
        return set(self._matches)


class FakeProvider:
    """Returns only the subtitles of the exact languages asked for, like providers filtering on HI/forced do."""
    languages = {EN, EN_HI, EN_FORCED, FR}
    video_types = (Movie,)
    catalog = []
    listings = []

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
        type(self).listings.append(set(languages))
        return [FakeSubtitle(language, sub_id, matches) for language, sub_id, matches in self.catalog
                if language in languages]

    def download_subtitle(self, subtitle):
        subtitle.content = SRT


class SearchState:
    def __init__(self, missing):
        self.missing = set(missing)
        self.saved = []


def _profile(*items):
    return {"items": [{"language": language, "hi": hi, "forced": forced} for language, hi, forced in items],
            "originalFormat": False}


@pytest.fixture
def run_search(monkeypatch):
    def run(shared, languages, profile, catalog, cutoff_after_first_save=False):
        FakeProvider.catalog = catalog
        FakeProvider.listings = []
        monkeypatch.setattr("subliminal_patch.core.provider_registry", {"fake": FakeProvider})
        monkeypatch.setitem(download.settings.general, "shared_provider_discovery", shared)
        monkeypatch.setattr(pool_module, "_update_pool", lambda *args, **kwargs: False)
        monkeypatch.setattr(download.subliminal, "region", SimpleNamespace(backend=SimpleNamespace(sync=lambda: None)))

        sz_pool = SZProviderPool(providers=["fake"])
        state = SearchState(download._get_language_obj(languages))

        def save_subtitles(path, subtitles, **kwargs):
            state.saved.extend(subtitles)
            if cutoff_after_first_save:
                state.missing = set()
            else:
                for subtitle in subtitles:
                    state.missing.discard(subtitle.language)
            return subtitles

        monkeypatch.setattr(download, "_get_pool", lambda *args, **kwargs: sz_pool)
        monkeypatch.setattr(download, "get_profiles_list", lambda profile_id: profile)
        monkeypatch.setattr(download, "get_video", lambda *args, **kwargs: Movie("/movies/Movie.2020.mkv", "Movie",
                                                                                 year=2020))
        monkeypatch.setattr(download, "_get_scores", lambda *args, **kwargs: (0, 120, None))
        monkeypatch.setattr(download, "save_subtitles", save_subtitles)
        monkeypatch.setattr(download, "process_subtitle", lambda subtitle, **kwargs: SimpleNamespace(subtitle=subtitle))
        monkeypatch.setattr(download, "check_missing_languages", lambda path, media_type: set(state.missing))

        results = list(download.generate_subtitles("/movies/Movie.2020.mkv", languages, "English", None, "Movie",
                                                   "movie", 1, check_if_still_required=True))
        return state, results

    return run


CATALOG = [
    (EN, "en-1", {"title", "year"}),
    (EN_HI, "en-hi-1", {"title", "year"}),
    (EN_FORCED, "en-forced-1", {"title", "year"}),
    (FR, "fr-1", {"title", "year"}),
]


def _saved(state):
    return sorted((str(s.language), bool(s.language.hi), s.id) for s in state.saved)


@pytest.mark.parametrize("languages, profile, expected_listings", [
    ([("en", "False", "False"), ("fr", "False", "False")],
     _profile(("en", "False", "False"), ("fr", "False", "False")), 1),
    ([("en", "False", "False"), ("en", "False", "True")],
     _profile(("en", "False", "False"), ("en", "False", "True")), 1),
    ([("en", "False", "False"), ("en", "True", "False"), ("en", "False", "True")],
     _profile(("en", "False", "False"), ("en", "True", "False"), ("en", "False", "True")), 2),
])
def test_shared_discovery_lists_less_and_saves_the_same_subtitles(run_search, languages, profile, expected_listings):
    legacy_state, _ = run_search(False, languages, profile, CATALOG)
    legacy_listings = len(FakeProvider.listings)

    shared_state, _ = run_search(True, languages, profile, CATALOG)

    assert len(FakeProvider.listings) == expected_listings
    assert legacy_listings == len(languages)
    assert _saved(shared_state) == _saved(legacy_state)
    assert len(shared_state.saved) == len(languages)


def test_forced_candidate_never_satisfies_the_regular_requirement(run_search):
    catalog = [(EN_FORCED, "en-forced-1", {"title", "year"})]
    languages = [("en", "False", "False"), ("en", "False", "True")]

    state, _ = run_search(True, languages, _profile(("en", "False", "False"), ("en", "False", "True")), catalog)

    assert _saved(state) == [("en:forced", False, "en-forced-1")]


def test_cutoff_reached_after_first_save_stops_other_languages(run_search):
    languages = [("fr", "False", "False"), ("en", "False", "False")]
    profile = _profile(("fr", "False", "False"), ("en", "False", "False"))

    state, results = run_search(True, languages, profile, CATALOG, cutoff_after_first_save=True)

    # profile order is used, so French is resolved first and English is never downloaded
    assert _saved(state) == [("fr", False, "fr-1")]
    assert len(results) == 1


def test_hi_requirements_are_not_listed_when_cutoff_is_reached_first(run_search):
    languages = [("en", "False", "False"), ("en", "True", "False")]
    profile = _profile(("en", "False", "False"), ("en", "True", "False"))

    run_search(True, languages, profile, CATALOG, cutoff_after_first_save=True)

    assert FakeProvider.listings == [{EN}]


def test_listed_candidates_are_not_modified_by_selection(run_search, monkeypatch):
    listed = []
    original = download.list_candidates

    def spy(*args, **kwargs):
        candidates = original(*args, **kwargs)
        listed.extend(candidates)
        return candidates

    monkeypatch.setattr(download, "list_candidates", spy)
    run_search(True, [("en", "False", "False")], _profile(("en", "False", "False")), CATALOG)

    assert listed and all(candidate.content is None for candidate in listed)
    assert all(candidate.matches == set() for candidate in listed)
