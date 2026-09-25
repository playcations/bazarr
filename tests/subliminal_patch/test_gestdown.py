import pytest
from subliminal_patch.language import PatchedAddic7edConverter
from subliminal_patch.providers.gestdown import _BASE_URL
from subliminal_patch.providers.gestdown import GestdownProvider
from subliminal_patch.providers.gestdown import GestdownSubtitle
from subzero.language import Language


@pytest.fixture(autouse=True)
def fresh_cache():
    """Show lookups and season listings are kept in the subtitles cache: every test starts with an empty one."""
    from subliminal.cache import region

    from subliminal_patch.core import search_results_cache

    region.configure("dogpile.cache.memory", replace_existing_backend=True)
    search_results_cache.configure(24)
    yield
    search_results_cache.configure(0)


def test_language_list_is_convertible():
    converter = PatchedAddic7edConverter()
    for language in GestdownProvider.languages:
        converter.convert(language.alpha3)


@pytest.mark.parametrize(
    "episode_key,language,expected_any_release_info",
    [
        ("breaking_bad_s01e01", Language.fromietf("en"), "BluRayREWARD"),
        ("better_call_saul_s06e04", Language.fromietf("fr"), "AMZN-NTb"),
    ],
)
def test_list_subtitles(episodes, episode_key, language, expected_any_release_info):
    with GestdownProvider() as provider:
        subtitles = provider.list_subtitles(episodes[episode_key], {language})
        assert any(
            subtitle.release_info == expected_any_release_info for subtitle in subtitles
        )


def test_list_subtitles_hearing_impaired(episodes):
    with GestdownProvider() as provider:
        subtitles = provider.list_subtitles(
            episodes["better_call_saul_s06e04"], {Language.fromietf("en")}
        )
        assert not all(subtitle.hearing_impaired for subtitle in subtitles)
        assert any(subtitle.hearing_impaired for subtitle in subtitles)


def test_list_subtitles_inexistent(episodes):
    with GestdownProvider() as provider:
        assert not provider.list_subtitles(
            episodes["inexistent"], {Language.fromietf("en")}
        )


@pytest.fixture
def subtitle():
    return GestdownSubtitle(
        Language.fromietf("fr"),
        {
            "subtitleId": "d28b4d5b-7dcc-47b3-8232-fb02f081d135",
            "version": "480p.AMZN.WEB-DL.NTb",
            "hearingImpaired": False,
            "downloadUri": "/subtitles/download/d28b4d5b-7dcc-47b3-8232-fb02f081d135",
            "qualities": [],
        },
    )


def test_subtitle(subtitle):
    assert subtitle.language == Language.fromietf("fr")
    assert subtitle.id == "d28b4d5b-7dcc-47b3-8232-fb02f081d135"
    assert subtitle.hearing_impaired == False
    assert subtitle.releases == ["480p.AMZN.WEB-DL.NTb"]
    assert subtitle.qualities == []


def test_subtitle_get_matches(subtitle, episodes):
    matches = subtitle.get_matches(episodes["better_call_saul_s06e04"])

    assert matches.issuperset(("series", "title", "season", "episode", "source"))
    assert "resolution" not in matches


def test_subtitle_multi_release_version():
    sub = GestdownSubtitle(
        Language.fromietf("en"),
        {
            "subtitleId": "abc",
            "version": "HDTV, WEB",
            "hearingImpaired": False,
            "downloadUri": "/download/abc",
            "qualities": [],
        },
    )
    assert sub.releases == ["HDTV", "WEB"]
    assert sub.release_info == "HDTV\nWEB"


def test_subtitle_get_matches_release_group(episodes):
    sub = GestdownSubtitle(
        Language.fromietf("en"),
        {
            "subtitleId": "abc",
            "version": "BluRay.720p.REWARD",
            "hearingImpaired": False,
            "downloadUri": "/download/abc",
            "qualities": [],
            "qualities": [],
        },
    )
    matches = sub.get_matches(episodes["breaking_bad_s01e01"])
    assert "release_group" in matches


def test_subtitle_get_matches_resolution_from_qualities(episodes):
    sub = GestdownSubtitle(
        Language.fromietf("en"),
        {
            "subtitleId": "abc",
            "version": "HDTV",
            "hearingImpaired": False,
            "downloadUri": "/download/abc",
            "qualities": ["720p", "1080p"],
        },
    )
    matches = sub.get_matches(episodes["breaking_bad_s01e01"])
    assert "resolution" in matches


def test_subtitle_download(subtitle):
    with GestdownProvider() as provider:
        provider.download_subtitle(subtitle)
        assert subtitle.content is not None
        assert subtitle.is_valid()


def test_list_subtitles_423(episodes, requests_mock, mocker):
    mocker.patch("time.sleep")
    requests_mock.get(
        "https://api.gestdown.info/shows/external/tvdb/81189",
        status_code=200,
        text='{"shows":[{"id":"cd880e2e-ef44-47cd-9f3d-a03b343ba2d0","name":"Breaking Bad","nbSeasons":5,"seasons":[1,2,3,4,5]}]}',
    )
    requests_mock.get(
        f"{_BASE_URL}/shows/cd880e2e-ef44-47cd-9f3d-a03b343ba2d0/1/English",
        status_code=423,
    )
    requests_mock.get(
        f"{_BASE_URL}/subtitles/get/cd880e2e-ef44-47cd-9f3d-a03b343ba2d0/1/1/English",
        status_code=423,
    )

    with GestdownProvider() as provider:
        assert not provider.list_subtitles(
            episodes["breaking_bad_s01e01"], {Language.fromietf("en")}
        )


_SHOW = "cd880e2e-ef44-47cd-9f3d-a03b343ba2d0"


def _sub(sub_id, hi=False, completed=True):
    return {"subtitleId": sub_id, "version": "WEB", "completed": completed, "hearingImpaired": hi,
            "downloadUri": f"/subtitles/download/{sub_id}", "qualities": ["720p"]}


def _mock_show(requests_mock, shows=None):
    shows = shows or [{"id": _SHOW, "name": "Breaking Bad", "tvDbId": 81189}]
    return requests_mock.get(f"{_BASE_URL}/shows/external/tvdb/81189", json={"shows": shows})


def _episode(number):
    from subliminal.video import Episode

    return Episode(f"/tv/Breaking.Bad.S01E{number:02d}.mkv", "Breaking Bad", 1, number, series_tvdb_id=81189)


def test_season_listing_serves_every_episode_of_the_season(requests_mock):
    show = _mock_show(requests_mock)
    season = requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English", json={"episodes": [
        {"season": 1, "number": n, "subtitles": [_sub(f"e{n}"), _sub(f"e{n}-hi", hi=True)]} for n in (1, 2, 3)
    ], "seasonPacks": []})

    with GestdownProvider() as provider:
        for number in (1, 2, 3):
            subtitles = provider.list_subtitles(_episode(number),
                                                {Language.fromietf("en"), Language("eng", hi=True)})
            assert sorted(s.id for s in subtitles) == [f"e{number}", f"e{number}-hi"]
            assert {s.id: s.language.hi for s in subtitles} == {f"e{number}": False, f"e{number}-hi": True}

    assert show.call_count == 1
    assert season.call_count == 1


def test_episode_missing_from_season_listing_falls_back_once(requests_mock):
    _mock_show(requests_mock)
    requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English", json={"episodes": [], "seasonPacks": []})
    episode = requests_mock.get(f"{_BASE_URL}/subtitles/get/{_SHOW}/1/4/English",
                                json={"matchingSubtitles": [_sub("new"), _sub("wip", completed=False)]})

    with GestdownProvider() as provider:
        assert [s.id for s in provider.list_subtitles(_episode(4), {Language.fromietf("en")})] == ["new"]
        provider.list_subtitles(_episode(4), {Language.fromietf("en")})

    assert episode.call_count == 1


def test_stops_at_the_first_show_with_subtitles(requests_mock):
    other = "11111111-1111-1111-1111-111111111111"
    _mock_show(requests_mock, [{"id": _SHOW, "tvDbId": 81189}, {"id": other, "tvDbId": 81189}])
    requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English",
                      json={"episodes": [{"season": 1, "number": 1, "subtitles": [_sub("a")]}]})
    second = requests_mock.get(f"{_BASE_URL}/shows/{other}/1/English", json={"episodes": []})

    with GestdownProvider() as provider:
        assert [s.id for s in provider.list_subtitles(_episode(1), {Language.fromietf("en")})] == ["a"]
    assert second.call_count == 0


def test_short_retry_after_is_waited_once(requests_mock, mocker):
    sleep = mocker.patch("subliminal_patch.providers.gestdown.time.sleep")
    _mock_show(requests_mock)
    requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English", [
        {"status_code": 429, "headers": {"Retry-After": "2"}},
        {"json": {"episodes": [{"season": 1, "number": 1, "subtitles": [_sub("a")]}]}},
    ])

    with GestdownProvider() as provider:
        assert [s.id for s in provider.list_subtitles(_episode(1), {Language.fromietf("en")})] == ["a"]
    sleep.assert_called_once_with(2.0)


def test_long_retry_after_throttles_the_provider(requests_mock):
    from subliminal_patch.exceptions import TooManyRequests

    _mock_show(requests_mock)
    requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English", status_code=429, headers={"Retry-After": "90"})

    with GestdownProvider() as provider:
        with pytest.raises(TooManyRequests) as error:
            provider.list_subtitles(_episode(1), {Language.fromietf("en")})
    assert error.value.retry_after == 90


def test_download_pool_exhausted(requests_mock, subtitle):
    from subliminal.exceptions import DownloadLimitExceeded

    requests_mock.get(subtitle.page_link, status_code=429)
    with GestdownProvider() as provider:
        with pytest.raises(DownloadLimitExceeded):
            provider.download_subtitle(subtitle)


@pytest.mark.parametrize("status", [404, 500])
def test_download_failure_only_fails_that_subtitle(requests_mock, subtitle, status):
    requests_mock.get(subtitle.page_link, status_code=status)
    with GestdownProvider() as provider:
        provider.download_subtitle(subtitle)
    assert subtitle.content is None


def test_episode_refresh_error_is_a_miss(requests_mock):
    _mock_show(requests_mock)
    requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English", json={"episodes": []})
    requests_mock.get(f"{_BASE_URL}/subtitles/get/{_SHOW}/1/5/English", status_code=500)
    with GestdownProvider() as provider:
        assert provider.list_subtitles(_episode(5), {Language.fromietf("en")}) == []


def test_show_missing_from_gestdown_is_looked_up_once(requests_mock):
    lookup = requests_mock.get(f"{_BASE_URL}/shows/external/tvdb/81189", status_code=404)
    with GestdownProvider() as provider:
        for number in (1, 2, 3):
            assert provider.list_subtitles(_episode(number), {Language.fromietf("en")}) == []
    assert lookup.call_count == 1


def test_season_listing_follows_the_search_results_duration(requests_mock):
    from subliminal_patch.core import search_results_cache

    _mock_show(requests_mock)
    season = requests_mock.get(f"{_BASE_URL}/shows/{_SHOW}/1/English", json={"episodes": [
        {"season": 1, "number": n, "subtitles": [_sub(f"e{n}")]} for n in (1, 2)]})
    with GestdownProvider() as provider:
        # not reused: every episode asks again
        search_results_cache.configure(0)
        for number in (1, 2):
            provider.list_subtitles(_episode(number), {Language.fromietf("en")})
        assert season.call_count == 2
