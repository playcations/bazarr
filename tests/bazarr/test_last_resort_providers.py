import pytest
from subliminal.video import Movie
from subliminal_patch.core import SZProviderPool
from subliminal_patch.subtitle import Subtitle
from subzero.language import Language

REGULAR = b"1\n00:00:01,000 --> 00:00:02,000\nHello there.\n\n"
HI_CUES = b"1\n00:00:01,000 --> 00:00:02,000\n[door creaks]\nHello there.\n\n"


class FakeSubtitle(Subtitle):
    def __init__(self, provider_name, sub_id, content, score_matches):
        super().__init__(Language("eng"), hearing_impaired=False)
        self.provider_name = provider_name
        self.sub_id = sub_id
        self.fake_content = content
        self._matches = score_matches

    @property
    def id(self):
        return self.sub_id

    def get_matches(self, video):
        return set(self._matches)


class FakeProvider:
    def __init__(self, **kwargs):
        pass

    def initialize(self):
        pass

    def terminate(self):
        pass

    def download_subtitle(self, subtitle):
        subtitle.content = subtitle.fake_content


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    from dogpile.cache import make_region
    from subliminal_patch import core

    monkeypatch.setattr(core, "region", make_region().configure("dogpile.cache.memory"))


ALL = {"title", "year", "source", "release_group", "resolution", "video_codec", "audio_codec", "streaming_service",
       "edition"}


def _best(monkeypatch, candidates, min_score=0, reject=False):
    monkeypatch.setattr("subliminal_patch.core.provider_registry", {"fake": FakeProvider, "hiregular": FakeProvider})
    pool = SZProviderPool(providers=["fake", "hiregular"])
    video = Movie("/movies/Movie.2020.mkv", "Movie", year=2020)
    return pool.download_best_subtitles(candidates, video, {Language("eng")}, min_score=min_score,
                                        hearing_impaired="force non-HI", reject_detected_hi=reject)


def test_other_providers_win_over_a_better_scored_last_resort_subtitle(monkeypatch):
    candidates = [FakeSubtitle("hiregular", "from-hi", REGULAR, ALL),
                  FakeSubtitle("fake", "provider", REGULAR, {"title", "year"})]

    assert [s.id for s in _best(monkeypatch, candidates)] == ["provider"]


def test_last_resort_subtitle_is_used_when_the_others_are_rejected(monkeypatch):
    candidates = [FakeSubtitle("hiregular", "from-hi", REGULAR, ALL),
                  FakeSubtitle("fake", "hi-content", HI_CUES, {"title", "year"})]

    assert [s.id for s in _best(monkeypatch, candidates, reject=True)] == ["from-hi"]


def test_last_resort_subtitle_is_used_when_the_others_score_too_low(monkeypatch):
    candidates = [FakeSubtitle("fake", "low", REGULAR, {"title"}),
                  FakeSubtitle("hiregular", "from-hi", REGULAR, ALL)]

    assert [s.id for s in _best(monkeypatch, candidates, min_score=80)] == ["from-hi"]


def test_last_resort_subtitle_still_needs_the_minimum_score(monkeypatch):
    candidates = [FakeSubtitle("hiregular", "from-hi", REGULAR, {"title"})]

    assert _best(monkeypatch, candidates, min_score=80) == []
