# -*- coding: utf-8 -*-
"""Regular subtitles made from the hearing impaired subtitles of the video.

A hearing impaired subtitle next to the video or embedded in it is timed for that video and has all its dialogue, so
when no provider has a usable regular subtitle it's the best source for one. This provider removes what makes it
hearing impaired (sound descriptions, speaker labels, music markers) and offers the result as a regular subtitle in the
same language. It searches nothing online and only gets a turn once the other providers came up empty (see
subliminal_patch.core.LAST_RESORT_PROVIDERS).

The remove_HI mod alone leaves inline tags like ``(CHUCKLES)`` or ``[COUGHS, VOMITS]`` and music markers that Bazarr's
hearing impaired detection still finds, and deletes lyric lines. So music markers are removed beforehand (keeping the
lyrics) and the remaining tags afterwards; a result still detected as hearing impaired is never offered, as saving it
would only label it hearing impaired again.
"""

import logging
import os
import re

import pysubs2
from babelfish import language_converters
from subliminal_patch import core
from subliminal_patch.core import Episode, Movie, parse_for_hi_regex, search_external_subtitles
from subliminal_patch.providers import Provider
from subliminal_patch.providers.embeddedsubtitles import EmbeddedSubtitlesProvider
from subliminal_patch.subtitle import Subtitle
from subzero.modification.mods.hearing_impaired import HearingImpaired
from subzero.language import Language

logger = logging.getLogger(__name__)

_MUSIC = re.compile(r"[¶♫♪]+")
# remove_HI takes * and # for music markers: censored words (*****) are hidden from it, *sung lines* unwrapped
_CENSORED = re.compile(r"\*{2,}")
_CENSORED_PLACEHOLDER = "\ue000"  # private use character, left alone by the mods
_STARRED = re.compile(r"\*([^*\n]{3,}?)\*")
# the tags Bazarr's hearing impaired detection looks for, matched non-greedily so dialogue between two tags survives;
# formatting overrides like {\i1} and {\an8} aren't tags
_TAG = re.compile(r"[\[({](?!\\)[^\[\](){}\n]{3,}?[\])}]")
_DASH_ONLY = re.compile(r"^\s*-?[\s:]*$")
# remove_HI only finds speaker labels at the start of a line, not after formatting like {\i1}DAVID: Sister...
_SPEAKER = next(p.pattern for p in HearingImpaired.processors if p.name == "HI_before_colon_caps")
_LEADING_FORMATTING = re.compile(r"^([\s-]*(?:\{\\[^}]*\})+)(.*)$")
_DASH = re.compile(r"^-\s*")


def build_regular(raw, language):
    """SRT content of these hearing impaired subtitles without their hearing impaired parts, or None when that isn't
    possible or the result would still be detected as hearing impaired."""
    decoder = Subtitle(language)
    decoder.content = raw
    text = decoder.text
    if not text:
        return None

    text = _MUSIC.sub("", text)
    text = _CENSORED.sub(lambda match: _CENSORED_PLACEHOLDER * len(match.group(0)), text)
    text = _STARRED.sub(r"\1", text)

    stripped = Subtitle(language, mods=["remove_HI"])
    stripped.content = text.encode("utf-8")
    if not stripped.is_valid():
        return None
    content = stripped.get_modified_content(format="srt")
    if not content:
        return None

    try:
        subs = pysubs2.SSAFile.from_string(content.decode(stripped.get_encoding()))
    except Exception as error:  # pysubs2 raises many kinds of errors on malformed files
        logger.debug("Couldn't parse subtitles stripped of hearing impaired parts: %s", error)
        return None

    events = []
    for event in subs:
        lines = []
        for line in event.text.split("\\N"):
            line = _TAG.sub("", line).replace(_CENSORED_PLACEHOLDER, "#")
            formatted = _LEADING_FORMATTING.match(line)
            if formatted:
                line = formatted.group(1) + _SPEAKER.sub("", formatted.group(2))
            line = re.sub(r"\s{2,}", " ", _DASH_ONLY.sub("", line)).strip()
            if line:
                lines.append(line)
        # a dialogue dash only makes sense with two speakers left
        if len(lines) == 1:
            lines[0] = _DASH.sub("", lines[0])
        if lines:
            event.text = "\\N".join(lines)
            events.append(event)
    if not events:
        return None
    subs.events = events

    regular = subs.to_string("srt")
    if parse_for_hi_regex(subtitle_text=regular, alpha3_language=language.alpha3):
        logger.debug("Subtitles are still hearing impaired once stripped, not offering them")
        return None
    return regular.encode("utf-8")


def _external_path(video_path, name):
    # search_external_subtitles looks next to the video and in the custom subtitles folders
    folder = os.path.dirname(video_path)
    for directory in [folder] + [os.path.join(folder, path) for path in core.CUSTOM_PATHS]:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    return None


class HIRegularSubtitle(Subtitle):
    provider_name = "hiregular"
    hash_verifiable = False

    def __init__(self, language, source_id, release_info, media_type, content=None, embedded=None):
        super().__init__(language)
        self.source_id = source_id
        self.page_link = source_id
        self.release_info = release_info
        self.media_type = media_type
        self.embedded = embedded
        self._regular_content = content

    @property
    def id(self):
        return f"{self.source_id}:regular"

    def get_matches(self, video):
        # made from this video's own hearing impaired subtitles (a track of it or the file named after it), so they fit
        # the file like embedded subtitles do; the file name alone often lacks the year or release group
        return {"hash"}


class HIRegularProvider(Provider):
    provider_name = "hiregular"

    languages = {Language.fromalpha2(code) for code in language_converters["alpha2"].codes}
    video_types = (Episode, Movie)
    subtitle_class = HIRegularSubtitle

    def __init__(self, embedded_config=None):
        """embedded_config: settings of the embedded subtitles provider, used to read embedded tracks."""
        self._embedded = EmbeddedSubtitlesProvider(**embedded_config) if embedded_config else None

    def initialize(self):
        if self._embedded:
            self._embedded.initialize()

    def terminate(self):
        if self._embedded:
            self._embedded.terminate()

    def list_subtitles(self, video, languages):
        wanted = {language.basename: language for language in languages if not language.hi and not language.forced}
        path = getattr(video, "original_path", None) or video.name
        if not wanted or not path or not os.path.isfile(path):
            return []
        media_type = "series" if isinstance(video, Episode) else "movie"

        external = search_external_subtitles(path)
        # the regular subtitles are saved as <video>.<language>.srt: never replace a file that may already be there,
        # like hearing impaired subtitles named as regular ones or subtitles without a language
        if any(language is None for language in external.values()):
            return []
        for language in external.values():
            if not language.hi and not language.forced:
                wanted.pop(language.basename, None)

        subtitles = []
        for name, language in sorted(external.items()):
            if not language.hi or language.forced or language.basename not in wanted:
                continue
            hi_path = _external_path(path, name)
            if not hi_path:
                continue
            try:
                with open(hi_path, "rb") as file:
                    content = build_regular(file.read(), wanted[language.basename])
            except OSError as error:
                logger.debug("Couldn't read %s: %s", hi_path, error)
                continue
            if content:
                logger.debug("Built regular subtitles from %s", hi_path)
                subtitles.append(HIRegularSubtitle(wanted.pop(language.basename), hi_path, name, media_type,
                                                   content=content))

        if wanted and self._embedded:
            subtitles.extend(self._list_embedded(video, path, wanted, media_type))
        return subtitles

    def _list_embedded(self, video, path, wanted, media_type):
        hi_languages = {Language.rebuild(language, hi=True) for language in wanted.values()}
        try:
            tracks = self._embedded.query(path, hi_languages, media_type)
        except Exception as error:
            logger.debug("Couldn't list the embedded subtitles of %s: %s", path, error)
            return []

        subtitles = []
        for track in tracks:
            language = wanted.pop(track.language.basename, None) if track.stream.disposition.hearing_impaired else None
            if language:
                subtitles.append(HIRegularSubtitle(language, track.id, os.path.basename(path), media_type,
                                                   embedded=track))
        return subtitles

    def download_subtitle(self, subtitle):
        if subtitle.embedded is not None:
            # embedded tracks are only extracted when their turn comes
            self._embedded.download_subtitle(subtitle.embedded)
            if subtitle.embedded.content:
                subtitle._regular_content = build_regular(subtitle.embedded.content, subtitle.language)
            if not subtitle._regular_content:
                logger.info("%r: Couldn't make regular subtitles from this embedded track", subtitle)
                return
        subtitle.content = subtitle._regular_content
