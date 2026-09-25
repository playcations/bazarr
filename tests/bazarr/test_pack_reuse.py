import io
import threading
import time
import zipfile
from types import SimpleNamespace

import pytest
from subzero.language import Language

from subliminal_patch.providers.subdl import SubdlProvider, SubdlSubtitle
from subtitles.wanted import series as wanted_series

SRT = "1\n00:00:01,000 --> 00:00:02,000\nEpisode {}\n\n"


def _zip(*episodes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for episode in episodes:
            archive.writestr(f"Show.S01E{episode:02d}.720p.WEB.srt", SRT.format(episode))
    return buffer.getvalue()


def _members(*episodes):
    return [{"name": f"Show.S01E{e:02d}.720p.WEB.srt", "episode": e, "season": 1, "url": f"/unpack/{e}",
             "file_n_id": str(e)} for e in episodes]


def _pack_subtitle(target_episode, episodes=(1, 2, 3)):
    subtitle = SubdlSubtitle(language=Language("eng"), forced=False, hearing_impaired=False, page_link="",
                             download_link="/subtitle/pack.zip", file_id="pack.zip",
                             release_names=["Show.S01.720p.WEB"], uploader="", season=1, is_pack=True,
                             is_full_season=True, target_episode=target_episode, matched_id=True)
    subtitle.pack_members = _members(*episodes)
    subtitle.pack_member = f"Show.S01E{target_episode:02d}.720p.WEB.srt"
    return subtitle


# ── SubDL packs ──────────────────────────────────────────────────────────────


def test_pack_candidate_for_another_episode():
    pack = _pack_subtitle(1)

    candidate = pack.pack_candidate_for(1, 2, episode_title="Second")

    assert candidate.target_episode == 2
    assert candidate.pack_member == "Show.S01E02.720p.WEB.srt"
    assert candidate.id == pack.id
    assert pack.target_episode == 1
    assert pack.pack_candidate_for(1, 9) is None
    assert pack.pack_candidate_for(2, 2) is None


@pytest.fixture(autouse=True)
def fresh_cache():
    """Downloaded packs are kept in the subtitles cache: every test starts with an empty one."""
    from subliminal.cache import region

    region.configure("dogpile.cache.memory", replace_existing_backend=True)
    yield


def _counting_provider(monkeypatch, delay=0):
    provider = SubdlProvider(api_key="key", pack_reuse=True)
    downloads = []

    def get(url, timeout):
        downloads.append(url)
        time.sleep(delay)
        return SimpleNamespace(content=_zip(1, 2, 3), status_code=200)

    monkeypatch.setattr(provider, "checked", lambda fn, **kwargs: fn())
    monkeypatch.setattr(provider.session, "get", get)
    return provider, downloads


def test_pack_members_of_several_episodes_come_from_one_download(monkeypatch):
    provider, downloads = _counting_provider(monkeypatch)

    first = _pack_subtitle(1)
    provider.download_subtitle(first)
    second = first.pack_candidate_for(1, 3)
    provider.download_subtitle(second)

    assert len(downloads) == 1
    assert b"Episode 1" in first.content
    assert b"Episode 3" in second.content


def test_concurrent_requests_for_a_pack_download_it_once(monkeypatch):
    provider, downloads = _counting_provider(monkeypatch, delay=0.05)
    subtitles = [_pack_subtitle(1).pack_candidate_for(1, episode) for episode in (1, 2, 3)]

    threads = [threading.Thread(target=provider.download_subtitle, args=(s,)) for s in subtitles]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(downloads) == 1
    assert all(s.content for s in subtitles)


# ── filling other episodes ───────────────────────────────────────────────────


def test_pack_fills_other_wanted_episodes_of_the_season(monkeypatch):
    rows = [SimpleNamespace(sonarrEpisodeId=e, season=1, episode=e, absoluteEpisode=None, episodeTitle=f"E{e}")
            for e in (2, 3, 9)]
    searched = {}

    monkeypatch.setattr(wanted_series, "get_providers", lambda: ["subdl"])
    monkeypatch.setattr(wanted_series.database, "execute", lambda stmt: SimpleNamespace(all=lambda: rows))
    monkeypatch.setattr(wanted_series, "_load_episode",
                        lambda episode_id, refresh_index=True: SimpleNamespace(sonarrEpisodeId=episode_id,
                                                                               missing_subtitles="['en']",
                                                                               failedAttempts=None,
                                                                               path=f"/tv/{episode_id}.mkv"))

    def search(episode, languages, candidates=None, fill_from_packs=True, **kwargs):
        searched[episode.sonarrEpisodeId] = ([c.target_episode for c in candidates], fill_from_packs)
        return 1

    monkeypatch.setattr(wanted_series, "_search_episode", search)

    wanted_series._fill_from_packs(SimpleNamespace(sonarrSeriesId=1, sonarrEpisodeId=1, path="/tv/1.mkv"),
                                   [_pack_subtitle(1)])

    # episode 9 isn't in the pack; filled episodes don't fill again
    assert searched == {2: ([2], False), 3: ([3], False)}


def test_pack_fill_skips_an_episode_searched_by_another_job(monkeypatch):
    rows = [SimpleNamespace(sonarrEpisodeId=2, season=1, episode=2, absoluteEpisode=None, episodeTitle="E2")]
    monkeypatch.setattr(wanted_series, "get_providers", lambda: ["subdl"])
    monkeypatch.setattr(wanted_series.database, "execute", lambda stmt: SimpleNamespace(all=lambda: rows))
    monkeypatch.setattr(wanted_series, "_search_episode", lambda *args, **kwargs: pytest.fail("searched"))
    release = threading.Event()
    holder = threading.Thread(target=lambda: _hold_lock(release))
    holder.start()
    time.sleep(0.02)
    try:
        wanted_series._fill_from_packs(SimpleNamespace(sonarrSeriesId=1, sonarrEpisodeId=1, path="/tv/1.mkv"),
                                       [_pack_subtitle(1)])
    finally:
        release.set()
        holder.join()


def _hold_lock(release):
    with wanted_series.media_lock('series', 2):
        release.wait(1)


@pytest.mark.parametrize("pack_reuse", [True, False])
def test_search_keeps_packs_whole_only_with_pack_reuse(monkeypatch, pack_reuse):
    from subliminal.video import Episode

    item = {"name": "pack.zip", "url": "/subtitle/pack.zip", "language": "EN", "releases": ["Show.S01.720p.WEB"],
            "season": 1, "episode": None, "full_season": True, "episode_from": None, "episode_end": 0,
            "subtitlePage": "/s/pack", "unpack_files": _members(1, 2, 3)}
    provider = SubdlProvider(api_key="key", pack_reuse=pack_reuse)
    monkeypatch.setattr(provider, "_search", lambda params, description, paginate=False: ([item], {}))
    video = Episode("/tv/Show.S01E02.720p.WEB.mkv", "Show", 1, 2)

    (subtitle,) = [s for s in provider.query({Language("eng")}, video) if s.id.startswith("pack.zip")][:1]

    if pack_reuse:
        assert subtitle.is_pack and subtitle.download_link == "/subtitle/pack.zip"
        assert subtitle.pack_member == "Show.S01E02.720p.WEB.srt"
        assert len(subtitle.pack_members) == 3
    else:
        assert subtitle.is_direct_file and subtitle.download_link == "/unpack/2"
        assert subtitle.pack_members is None


def _season_pack(season, episodes, name, full=True):
    return {"name": name, "url": f"/subtitle/{name}", "language": "EN", "releases": [name], "season": season,
            "episode": None, "full_season": full, "episode_from": min(episodes), "episode_end": max(episodes),
            "subtitlePage": f"/s/{name}",
            "unpack_files": [{"name": f"Show.S{season:02d}E{e:02d}.srt", "episode": e, "season": season,
                              "url": f"/unpack/{season}/{e}", "file_n_id": f"{season}{e}"} for e in episodes]}


def _query(monkeypatch, items, season, episode, absolute=None, pack_reuse=True):
    from subliminal.video import Episode

    provider = SubdlProvider(api_key="key", pack_reuse=pack_reuse)
    monkeypatch.setattr(provider, "_search", lambda params, description, paginate=False: (items, {}))
    video = Episode(f"/tv/Show.S{season:02d}E{episode:02d}.mkv", "Show", season, episode)
    video.absolute_episode = absolute
    return provider.query({Language("eng")}, video)


@pytest.mark.parametrize("pack_reuse", [True, False])
def test_pack_of_another_season_is_never_used(monkeypatch, pack_reuse):
    # Arrested Development S03E01 (absolute 41) was filled from the season 1 pack (episodes 1-22)
    items = [_season_pack(1, range(1, 23), "show-first-season.zip"),
             _season_pack(4, range(1, 11), "show-fourth-season.zip")]
    assert _query(monkeypatch, items, season=3, episode=1, absolute=41, pack_reuse=pack_reuse) == []


def test_pack_of_the_right_season_is_used(monkeypatch):
    items = [_season_pack(3, range(1, 14), "show-third-season.zip")]
    (subtitle,) = _query(monkeypatch, items, season=3, episode=1, absolute=41)
    assert subtitle.is_pack and subtitle.pack_member == "Show.S03E01.srt"
    assert subtitle.absolute_episode is None
    assert "season" in subtitle.matches


def test_anime_pack_matched_by_absolute_range_is_kept(monkeypatch):
    # arc-based numbering: Sonarr S11E03 is absolute 266, the provider files it as season 9 episodes 264-275
    item = _season_pack(9, range(264, 276), "anime-arc.zip", full=False)
    item["unpack_files"] = [{"name": f"Anime - {e}.srt", "episode": e, "season": 0, "url": f"/u/{e}",
                             "file_n_id": str(e)} for e in range(264, 276)]
    (subtitle,) = _query(monkeypatch, [item], season=11, episode=3, absolute=266)
    assert subtitle.is_pack and subtitle.absolute_episode == 266
    assert "season" in subtitle.matches
    # absolute numbering can't be used to fill other episodes
    assert subtitle.pack_candidate_for(11, 4) is None


def test_pack_member_named_for_another_season_is_not_used(monkeypatch):
    item = _season_pack(2, range(1, 11), "mislabeled.zip")
    item["unpack_files"] = [{"name": f"Show.S04E{e:02d}.srt", "episode": e, "season": 0, "url": f"/u/{e}",
                             "file_n_id": str(e)} for e in range(1, 11)]
    assert _query(monkeypatch, [item], season=2, episode=4) == []
