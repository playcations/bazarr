from types import SimpleNamespace

import pytest
from subliminal_patch.core import Episode, Movie, parse_for_hi_regex
from subliminal_patch.providers import hiregular
from subliminal_patch.providers.hiregular import HIRegularProvider, HIRegularSubtitle, build_regular
from subzero.language import Language

HI = """1
00:00:01,000 --> 00:00:03,000
[Kevin] What a story this is.

2
00:00:04,000 --> 00:00:06,000
[scoffs] He's just doing what he...

3
00:00:07,000 --> 00:00:09,000
[somber music plays]

4
00:00:10,000 --> 00:00:12,000
- (CHUCKLES) You're late.
- [COUGHS, VOMITS] Sorry.

5
00:00:13,000 --> 00:00:15,000
♪ Sweet home Alabama ♪

6
00:00:16,000 --> 00:00:18,000
What the ***** was that?

7
00:00:19,000 --> 00:00:21,000
<i>I told you so.</i>

8
00:00:22,000 --> 00:00:24,000
- [door creaks]
- Who's there?
"""


def _text(content):
    return content.decode("utf-8")


def test_hi_parts_are_removed_and_dialogue_kept():
    regular = _text(build_regular(HI.encode("utf-8"), Language("eng")))

    assert "What a story this is." in regular
    assert "He's just doing what he..." in regular
    assert "You're late." in regular and "Sorry." in regular
    assert "Who's there?" in regular and "- Who's there?" not in regular   # one speaker left, no dash
    for hi in ("Kevin", "scoffs", "music", "CHUCKLES", "COUGHS", "door", "♪"):
        assert hi not in regular
    assert not parse_for_hi_regex(subtitle_text=regular, alpha3_language="eng")


def test_lyrics_censored_words_and_formatting_are_kept():
    regular = _text(build_regular(HI.encode("utf-8"), Language("eng")))

    assert "Sweet home Alabama" in regular
    assert "What the ##### was that?" in regular
    assert "<i>I told you so.</i>" in regular


def test_timing_is_kept():
    regular = _text(build_regular(HI.encode("utf-8"), Language("eng")))

    assert "00:00:01,000 --> 00:00:03,000" in regular
    assert "00:00:07,000 --> 00:00:09,000" not in regular   # only a sound description


def test_nothing_is_offered_when_the_result_is_still_hi(monkeypatch):
    monkeypatch.setattr(hiregular, "parse_for_hi_regex", lambda **kwargs: True)

    assert build_regular(HI.encode("utf-8"), Language("eng")) is None


def test_nothing_is_offered_for_unreadable_or_only_hi_subtitles():
    assert build_regular(b"not subtitles", Language("eng")) is None
    assert build_regular(b"1\n00:00:01,000 --> 00:00:02,000\n[door creaks]\n", Language("eng")) is None


NAME = "Show.S01E02.1080p.WEB-DL.x264-GRP"


def _video(tmp_path, cls=Episode):
    video_path = tmp_path / f"{NAME}.mkv"
    video_path.write_bytes(b"")
    video = Episode(str(video_path), "Show", 1, 2) if cls is Episode else Movie(str(video_path), "Show")
    video.original_path = str(video_path)
    return video


def test_provider_offers_regular_subtitles_from_the_hi_file(tmp_path):
    video = _video(tmp_path)
    (tmp_path / f"{NAME}.en.hi.srt").write_text(HI)
    provider = HIRegularProvider()

    subtitles = provider.list_subtitles(video, {Language("eng"), Language("eng", hi=True)})

    assert len(subtitles) == 1
    subtitle = subtitles[0]
    assert subtitle.language == Language("eng") and not subtitle.language.hi and not subtitle.hearing_impaired
    provider.download_subtitle(subtitle)
    assert subtitle.is_valid()
    assert b"What a story this is." in subtitle.content and b"Kevin" not in subtitle.content
    assert subtitle.get_matches(video) == {"hash"}   # the video's own subtitles, whatever the file name says


@pytest.mark.parametrize("existing, wanted", [
    ([f"{NAME}.en.hi.srt"], Language("eng", hi=True)),                     # an HI requirement
    ([f"{NAME}.en.hi.srt"], Language("eng", forced=True)),                 # a forced requirement
    ([f"{NAME}.en.hi.srt"], Language("fra")),                              # another language
    ([f"{NAME}.en.srt"], Language("eng")),                                 # not hearing impaired
    ([f"{NAME}.en.hi.srt", f"{NAME}.en.srt"], Language("eng")),            # would replace the .en.srt file
    ([f"{NAME}.en.hi.srt", f"{NAME}.srt"], Language("eng")),               # a subtitle without language
])
def test_provider_offers_nothing(tmp_path, existing, wanted):
    video = _video(tmp_path)
    for name in existing:
        (tmp_path / name).write_text(HI)

    assert HIRegularProvider().list_subtitles(video, {wanted}) == []


class FakeEmbedded:
    def __init__(self, tracks, content=HI.encode("utf-8")):
        self.tracks = tracks
        self.content = content
        self.queried = []

    def query(self, path, languages, media_type):
        self.queried.append(languages)
        return [track for track in self.tracks if track.language in languages]

    def download_subtitle(self, subtitle):
        subtitle.content = self.content


def _track(index, hi):
    return SimpleNamespace(id=f"video.mkv_{index}", language=Language("eng", hi=hi), content=None,
                           stream=SimpleNamespace(disposition=SimpleNamespace(hearing_impaired=hi)))


def test_provider_offers_regular_subtitles_from_an_embedded_hi_track(tmp_path):
    video = _video(tmp_path, Movie)
    provider = HIRegularProvider()
    provider._embedded = FakeEmbedded([_track(2, hi=False), _track(3, hi=True)])

    subtitles = provider.list_subtitles(video, {Language("eng")})

    assert provider._embedded.queried == [{Language("eng", hi=True)}]
    assert [s.id for s in subtitles] == ["video.mkv_3:regular"]
    provider.download_subtitle(subtitles[0])
    assert b"What a story this is." in subtitles[0].content and b"Kevin" not in subtitles[0].content


def test_external_hi_file_is_preferred_over_embedded_tracks(tmp_path):
    video = _video(tmp_path)
    (tmp_path / f"{NAME}.en.sdh.srt").write_text(HI)
    provider = HIRegularProvider()
    provider._embedded = FakeEmbedded([_track(3, hi=True)])

    subtitles = provider.list_subtitles(video, {Language("eng")})

    assert [s.release_info for s in subtitles] == [f"{NAME}.en.sdh.srt"]
    assert provider._embedded.queried == []


def test_embedded_track_that_cant_be_converted_gives_no_content(tmp_path):
    video = _video(tmp_path)
    provider = HIRegularProvider()
    provider._embedded = FakeEmbedded([_track(3, hi=True)], content=b"1\n00:00:01,000 --> 00:00:02,000\n[sighs]\n")

    (subtitle,) = provider.list_subtitles(video, {Language("eng")})
    provider.download_subtitle(subtitle)

    assert subtitle.content is None


def test_embedded_tracks_are_read_with_the_embedded_subtitles_settings(tmp_path):
    provider = HIRegularProvider({"cache_dir": str(tmp_path), "hi_fallback": False, "timeout": 30})

    assert provider._embedded._timeout == 30
    assert HIRegularProvider()._embedded is None


def test_subtitle_ids_are_unique_per_source():
    subtitle = HIRegularSubtitle(Language("eng"), "/tv/a.en.hi.srt", "a.en.hi.srt", "series", content="x")

    assert subtitle.id == "/tv/a.en.hi.srt:regular"
