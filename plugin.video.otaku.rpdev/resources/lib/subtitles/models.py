"""models.py - Data models for Otaku-RPDev Native Subtitles
=========================================================
"""

# -*- coding: utf-8 -*-

from typing import Optional, List, Dict, Any


class VideoMeta:
    """Represents video metadata used for querying subtitle providers."""

    def __init__(
        self,
        title: str = '',
        tvshow: str = '',
        original_title: str = '',
        season: Any = '',
        episode: Any = '',
        year: Any = '',
        imdb_id: str = '',
        tvshow_year: Any = '',
        filename: str = '',
        languages: Optional[List[str]] = None,
        preferred_lang: str = 'eng',
        filehash: str = '',
        filesize: int = 0,
        is_tvshow: Optional[bool] = None,
        search_string: str = '',
        is_manual_search: bool = False,
        mal_id: str = '',
        anilist_id: str = '',
        anidb_id: str = '',
        anidb_ep_id: str = '',
        kitsu_id: str = '',
        release_group: str = '',
        preferred_group: str = '',
    ):
        self.title = str(title or '').strip()
        self.tvshow = str(tvshow or '').strip()
        self.original_title = str(original_title or '').strip()
        self.season = str(season or '').strip()
        self.episode = str(episode or '').strip()
        self.year = str(year or '').strip()
        self.imdb_id = str(imdb_id or '').strip()
        self.tvshow_year = str(tvshow_year or '').strip()
        self.filename = str(filename or '').strip()
        self.languages = list(languages) if languages is not None else ['English']
        self.preferred_lang = str(preferred_lang if preferred_lang is not None else 'eng').strip().lower()
        self.filehash = str(filehash or '').strip()
        self.filesize = int(filesize or 0)
        self.search_string = str(search_string or '').strip()
        self.is_manual_search = bool(is_manual_search)
        self.mal_id = str(mal_id or '').strip()
        self.anilist_id = str(anilist_id or '').strip()
        self.anidb_id = str(anidb_id or '').strip()
        self.anidb_ep_id = str(anidb_ep_id or '').strip()
        self.kitsu_id = str(kitsu_id or '').strip()
        self.release_group = str(release_group or '').strip()
        self.preferred_group = str(preferred_group or '').strip()

        if is_tvshow is not None:
            self.is_tvshow = bool(is_tvshow)
        else:
            self.is_tvshow = bool(self.tvshow or (self.season and self.episode))

        self.is_movie = not self.is_tvshow

        # Ensure IMDb ID has 'tt' format and integer format
        if self.imdb_id.startswith('tt'):
            self.imdb_id_int = self.imdb_id[2:] if self.imdb_id[2:].isdigit() else ''
        elif self.imdb_id.isdigit():
            self.imdb_id_int = self.imdb_id
            self.imdb_id = f"tt{self.imdb_id}"
        else:
            self.imdb_id_int = ''

    @property
    def filename_without_ext(self) -> str:
        if '.' in self.filename:
            return self.filename.rsplit('.', 1)[0]
        return self.filename

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'tvshow': self.tvshow,
            'original_title': self.original_title,
            'season': self.season,
            'episode': self.episode,
            'year': self.year,
            'imdb_id': self.imdb_id,
            'tvshow_year': self.tvshow_year,
            'filename': self.filename,
            'languages': self.languages,
            'preferred_lang': self.preferred_lang,
            'filehash': self.filehash,
            'filesize': self.filesize,
            'is_tvshow': self.is_tvshow,
            'is_movie': self.is_movie,
            'search_string': self.search_string,
            'is_manual_search': self.is_manual_search,
            'mal_id': self.mal_id,
            'anilist_id': self.anilist_id,
            'anidb_id': self.anidb_id,
            'anidb_ep_id': self.anidb_ep_id,
            'kitsu_id': self.kitsu_id,
            'release_group': self.release_group,
            'preferred_group': self.preferred_group,
        }

    def __repr__(self) -> str:
        return f"<VideoMeta {self.tvshow or self.title} S{self.season}E{self.episode} imdb={self.imdb_id}>"


class SubtitleResult:
    """Represents a single subtitle result returned by a subtitle provider."""

    def __init__(
        self,
        service_name: str,
        display_name: str,
        name: str,
        lang: str,
        lang_code: str,
        download_url: str = '',
        rating: float = 0.0,
        sync: bool = False,
        impaired: bool = False,
        forced: bool = False,
        color: str = 'springgreen',
        action_args: Optional[Dict[str, Any]] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        episodes_range: Optional[List[int]] = None,
        auto_identified: bool = False,
        match_confidence: str = 'low',
        match_reason: str = '',
        release_group: str = '',
        is_anime_native: bool = False,
        subtitle_format: str = '',
        is_signs_only: bool = False,
    ):
        self.service_name = service_name
        self.display_name = display_name
        self.name = str(name or '').strip()
        self.lang = str(lang or '').strip()
        self.lang_code = str(lang_code or '').strip().lower()
        self.download_url = str(download_url or '').strip()
        self.rating = float(rating or 0.0)
        self.sync = bool(sync)
        self.impaired = bool(impaired)  # Hearing impaired / SDH
        self.forced = bool(forced)      # Forced / Signs & Songs
        self.color = color
        self.action_args = dict(action_args or {})
        self.season = season
        self.episode = episode
        self.episodes_range = list(episodes_range or [])
        self.auto_identified = bool(auto_identified)
        self.match_confidence = str(match_confidence or 'low')
        self.match_reason = str(match_reason or '')
        self.release_group = str(release_group or '').strip()
        self.is_anime_native = bool(is_anime_native)
        self.subtitle_format = str(subtitle_format or '').strip().lower()
        self.is_signs_only = bool(is_signs_only)
        self.score = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'service_name': self.service_name,
            'service': self.display_name,
            'name': self.name,
            'lang': self.lang,
            'lang_code': self.lang_code,
            'download_url': self.download_url,
            'rating': self.rating,
            'sync': 'true' if self.sync else 'false',
            'impaired': 'true' if self.impaired else 'false',
            'forced': 'true' if self.forced else 'false',
            'color': self.color,
            'action_args': self.action_args,
            'season': self.season,
            'episode': self.episode,
            'auto_identified': self.auto_identified,
            'match_confidence': self.match_confidence,
            'match_reason': self.match_reason,
            'release_group': self.release_group,
            'is_anime_native': self.is_anime_native,
            'subtitle_format': self.subtitle_format,
            'is_signs_only': self.is_signs_only,
            'score': round(self.score, 3),
        }

    def __repr__(self) -> str:
        return f"<SubtitleResult [{self.service_name}] {self.name} ({self.lang}) score={round(self.score, 2)}>"
