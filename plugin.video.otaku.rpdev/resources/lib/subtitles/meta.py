"""meta.py - Video Metadata Extraction for Subtitle Queries
==========================================================
"""

# -*- coding: utf-8 -*-

import re
from typing import Optional, Dict, Any, List
import xbmc
from resources.lib.ui import control, database, source_utils
from resources.lib.subtitles.models import VideoMeta
from resources.lib.subtitles import languages


def get_meta_from_player() -> VideoMeta:
    """Extracts VideoMeta from the active Kodi player instance."""
    title = ''
    tvshow = ''
    original_title = ''
    season = ''
    episode = ''
    year = ''
    imdb_id = ''
    filename = ''

    # 1. InfoTagVideo API (Kodi 20+)
    try:
        player = xbmc.Player()
        if player.isPlaying():
            vinfo = player.getVideoInfoTag()
            if vinfo:
                season = str(vinfo.getSeason() or '')
                episode = str(vinfo.getEpisode() or '')
                year = str(vinfo.getYear() or '')
                tvshow = vinfo.getTVShowTitle() or ''
                title = vinfo.getTitle() or ''
                original_title = vinfo.getOriginalTitle() or ''
                imdb_id = vinfo.getUniqueID('imdb') or ''
    except Exception:
        pass

    # 2. Fallbacks via getInfoLabel
    if not year:
        year = xbmc.getInfoLabel('VideoPlayer.Year') or ''
    if not season:
        season = xbmc.getInfoLabel('VideoPlayer.Season') or ''
    if not episode:
        episode = xbmc.getInfoLabel('VideoPlayer.Episode') or ''
    if not tvshow:
        tvshow = xbmc.getInfoLabel('VideoPlayer.TVShowTitle') or ''
    if not title:
        title = xbmc.getInfoLabel('VideoPlayer.Title') or ''
    if not original_title:
        original_title = xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or ''
    if not imdb_id:
        imdb_id = xbmc.getInfoLabel('VideoPlayer.IMDBNumber') or ''

    # 3. Clean Filename
    filename = (
        xbmc.getInfoLabel('ListItem.Property(original_filename)') or
        xbmc.getInfoLabel('ListItem.Property(VideoPlayer.OriginalFilename)') or
        ''
    )

    if not filename:
        try:
            playing_file = xbmc.Player().getPlayingFile()
            clean_url = playing_file.split('?')[0].split('#')[0]
            basename = clean_url.split('/')[-1]
            if basename and not basename.lower().endswith(('.m3u8', '.mpd', 'master')):
                filename = basename
        except Exception:
            pass

    # If still no clean filename, synthesize from show/episode
    if not filename:
        clean_show = tvshow or title
        if clean_show and season and episode:
            try:
                filename = f"{clean_show} - S{int(season):02d}E{int(episode):02d}.mkv"
            except (ValueError, TypeError):
                filename = f"{clean_show} - E{episode}.mkv"

    # Preferred language from Otaku settings (general.subtitles)
    sub_setting_idx = control.getInt('general.subtitles')
    subtitle_langs = [
        "none", "English", "Japanese", "Spanish", "French", "German",
        "Italian", "Dutch", "Russian", "Portuguese", "Korean", "Chinese",
        "Arabic", "Hindi", "Turkish", "Polish", "Swedish", "Norwegian",
        "Danish", "Finnish"
    ]
    if sub_setting_idx == 0:
        pref_name = "none"
        pref_code = "none"
        languages_list = []
    else:
        pref_name = subtitle_langs[sub_setting_idx] if sub_setting_idx < len(subtitle_langs) else "English"
        pref_code = languages.to_iso639_1(pref_name)
        languages_list = [pref_name]

    return VideoMeta(
        title=title,
        tvshow=tvshow,
        original_title=original_title,
        season=season,
        episode=episode,
        year=year,
        imdb_id=imdb_id,
        filename=filename,
        languages=languages_list,
        preferred_lang=pref_code,
    )


def get_meta_from_dict(video_info: Dict[str, Any], mal_id: Optional[str] = None) -> VideoMeta:
    """Builds VideoMeta from an Otaku video_info dictionary."""
    title = video_info.get('title') or video_info.get('name') or ''
    tvshow = video_info.get('tvshowtitle') or video_info.get('showtitle') or ''
    original_title = video_info.get('originaltitle') or video_info.get('OriginalTitle') or ''
    season = str(video_info.get('season') or '')
    episode = str(video_info.get('episode') or '')
    year = str(video_info.get('year') or '')

    imdb_id = ''
    unique_ids = video_info.get('UniqueIDs', {})
    if isinstance(unique_ids, dict):
        imdb_id = str(unique_ids.get('imdb') or unique_ids.get('imdb_id') or '')

    if not imdb_id and mal_id:
        try:
            ids = database.get_unique_ids(mal_id, 'mal_id')
            if ids and ids.get('imdb'):
                imdb_id = str(ids['imdb'])
        except Exception:
            pass

    clean_filename = source_utils.format_video_filename(video_info)

    sub_setting_idx = control.getInt('general.subtitles')
    subtitle_langs = [
        "none", "English", "Japanese", "Spanish", "French", "German",
        "Italian", "Dutch", "Russian", "Portuguese", "Korean", "Chinese",
        "Arabic", "Hindi", "Turkish", "Polish", "Swedish", "Norwegian",
        "Danish", "Finnish"
    ]
    if sub_setting_idx == 0:
        pref_name = "none"
        pref_code = "none"
        languages_list = []
    else:
        pref_name = subtitle_langs[sub_setting_idx] if sub_setting_idx < len(subtitle_langs) else "English"
        pref_code = languages.to_iso639_1(pref_name)
        languages_list = [pref_name]

    return VideoMeta(
        title=title,
        tvshow=tvshow,
        original_title=original_title,
        season=season,
        episode=episode,
        year=year,
        imdb_id=imdb_id,
        filename=clean_filename,
        languages=languages_list,
        preferred_lang=pref_code,
    )
