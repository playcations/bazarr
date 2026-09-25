import pytest
from subliminal.video import Movie
from subliminal_patch.core import SZProviderPool
from subliminal_patch.subtitle import Subtitle
from subzero.language import Language

from subtitles.download import _reject_detected_hi

REGULAR = b"1\n00:00:01,000 --> 00:00:02,000\nHello there.\n\n"
HI_CUES = b"1\n00:00:01,000 --> 00:00:02,000\n[door creaks]\nHello there.\n\n"


class FakeSubtitle(Subtitle):
    provider_name = "fake"
    hearing_impaired_verifiable = True

    def __init__(self, sub_id, content, score_matches):
        super().__init__(Language("eng"), hearing_impaired=False)
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


def _best(monkeypatch, reject):
    monkeypatch.setattr("subliminal_patch.core.provider_registry", {"fake": FakeProvider})
    pool = SZProviderPool(providers=["fake"])
    video = Movie("/movies/Movie.2020.mkv", "Movie", year=2020)
    candidates = [FakeSubtitle("hi-content", HI_CUES, {"title", "year", "source"}),
                  FakeSubtitle("regular", REGULAR, {"title", "year"})]
    return pool.download_best_subtitles(candidates, video, {Language("eng")}, hearing_impaired="force non-HI",
                                        reject_detected_hi=reject)


def test_subtitle_with_hi_content_is_skipped_for_the_next_candidate(monkeypatch):
    assert [s.id for s in _best(monkeypatch, reject=True)] == ["regular"]


def test_subtitle_with_hi_content_is_kept_by_default(monkeypatch):
    assert [s.id for s in _best(monkeypatch, reject=False)] == ["hi-content"]


def test_reject_only_when_hi_is_excluded_and_not_removed_by_mods():
    assert _reject_detected_hi("force non-HI", [])
    assert not _reject_detected_hi("force non-HI", ["remove_HI"])
    assert not _reject_detected_hi("don't prefer", [])
    assert not _reject_detected_hi("force HI", [])


def test_subtitle_with_hi_content_is_not_downloaded_again(monkeypatch):
    downloads = []
    original = FakeProvider.download_subtitle

    def counting(self, subtitle):
        downloads.append(subtitle.id)
        original(self, subtitle)

    monkeypatch.setattr(FakeProvider, "download_subtitle", counting)
    _best(monkeypatch, reject=True)
    _best(monkeypatch, reject=True)

    assert downloads.count("hi-content") == 1
    assert downloads.count("regular") == 2
