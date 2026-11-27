"""meta.py - Video Metadata Extraction for Subtitle Queries
==========================================================
"""

# -*- coding: utf-8 -*-

import json
import re
from typing import Optional, Dict, Any, List
import xbmc
from resources.lib.ui import control, database, source_utils
from resources.lib.subtitles.models import VideoMeta
from resources.lib.subtitles import languages

ACTIVE_SUB_META_PROP = 'otaku.active_sub_meta'


def _enrich_sub_fields_from_mappings(mal_id, imdb_id='', year='', tvshow='', original_title='', season=''):
    """Backfill blank subtitle lookup fields from offline mappings.db for accurate provider queries."""
    if not mal_id:
        return imdb_id, year, tvshow, original_title, season
    needs_season = (not season or str(season).strip() in ('', '0'))
    if imdb_id and year and (tvshow or original_title) and not needs_season:
        return imdb_id, year, tvshow, original_title, season
    try:
        mp = database.get_mappings(mal_id, 'mal_id')
    except Exception:
        mp = None
    if not isinstance(mp, dict) or not mp:
        return imdb_id, year, tvshow, original_title, season

    if not imdb_id and mp.get('imdb_id'):
        imdb_id = str(mp['imdb_id']).strip()
    if not year and mp.get('year'):
        year = str(mp['year']).strip()
    if not original_title and mp.get('mal_title'):
        original_title = str(mp['mal_title']).strip()
    if needs_season and mp.get('thetvdb_season') is not None:
        tvs = str(mp['thetvdb_season']).strip()
        if tvs.isdigit() and int(tvs) > 0:
            season = tvs
    return imdb_id, year, tvshow, original_title, season


def _resolve_anime_ids_and_groups(mal_id, season='', episode='', filename=''):
    """Resolve anime tracker IDs (anilist/anidb/kitsu/anidb_ep_id) and release/preferred groups."""
    anilist_id = ''
    anidb_id = ''
    anidb_ep_id = ''
    kitsu_id = ''
    preferred_group = ''
    release_group = source_utils.extract_release_group(filename or '')

    if mal_id and str(mal_id).isdigit():
        try:
            mp = database.resolve_mappings_with_fallback(mal_id)
            if isinstance(mp, dict):
                anilist_id = str(mp.get('anilist_id') or '').strip()
                anidb_id = str(mp.get('anidb_id') or mp.get('anidb') or '').strip()
                kitsu_id = str(mp.get('kitsu_id') or '').strip()
        except Exception:
            pass
        if episode and str(episode).isdigit():
            try:
                ep_rows = database.get_episode_list(int(mal_id)) or []
                target_ep = int(episode)
                for row in ep_rows:
                    if isinstance(row, dict) and int(row.get('number') or -1) == target_ep:
                        if row.get('anidb_ep_id'):
                            anidb_ep_id = str(row['anidb_ep_id']).strip()
                        break
            except Exception:
                pass
        try:
            ov = database.get_series_override(mal_id)
            if isinstance(ov, dict):
                preferred_group = str(ov.get('preferred_group') or '').strip()
        except Exception:
            pass

    return {
        'anilist_id': anilist_id,
        'anidb_id': anidb_id,
        'anidb_ep_id': anidb_ep_id,
        'kitsu_id': kitsu_id,
        'release_group': release_group,
        'preferred_group': preferred_group,
    }


def publish_active_playback_meta(video_info: Optional[Dict[str, Any]], mal_id: str = '', filename: str = '') -> None:
    """Publish compact active-playback metadata to Window(10000) for auto-download and Kodi subtitle service."""
    try:
        info = dict(video_info or {})
        unique_ids = info.get('UniqueIDs', {}) if isinstance(info.get('UniqueIDs'), dict) else {}
        imdb_id = str(unique_ids.get('imdb') or unique_ids.get('imdb_id') or '')
        title = str(info.get('title') or info.get('name') or '')
        tvshow = str(info.get('tvshowtitle') or info.get('showtitle') or '')
        original_title = str(info.get('originaltitle') or info.get('OriginalTitle') or '')
        season = str(info.get('season') or '')
        episode = str(info.get('episode') or '')
        year = str(info.get('year') or '')
        imdb_id, year, tvshow, original_title, season = _enrich_sub_fields_from_mappings(
            mal_id, imdb_id=imdb_id, year=year, tvshow=tvshow, original_title=original_title, season=season
        )
        eff_filename = str(filename or info.get('release_title') or source_utils.format_video_filename(info) or '')
        anime_ctx = _resolve_anime_ids_and_groups(mal_id, season=season, episode=episode, filename=eff_filename)

        payload = {
            'mal_id': str(mal_id or ''),
            'imdb_id': imdb_id,
            'anilist_id': str(unique_ids.get('anilist_id') or anime_ctx['anilist_id'] or ''),
            'anidb_id': str(unique_ids.get('anidb') or unique_ids.get('anidb_id') or anime_ctx['anidb_id'] or ''),
            'anidb_ep_id': str(info.get('anidb_ep_id') or anime_ctx['anidb_ep_id'] or ''),
            'kitsu_id': str(unique_ids.get('kitsu_id') or anime_ctx['kitsu_id'] or ''),
            'release_group': anime_ctx['release_group'],
            'preferred_group': anime_ctx['preferred_group'],
            'title': title,
            'tvshow': tvshow,
            'original_title': original_title,
            'season': season,
            'episode': episode,
            'year': year,
            'filename': eff_filename,
        }
        control.setGlobalProp(ACTIVE_SUB_META_PROP, json.dumps(payload))
    except Exception as e:
        control.log(f"Native Subtitles: Failed to publish active playback meta: {e}", 'debug')


def clear_active_playback_meta() -> None:
    """Clear active-playback subtitle metadata and auto-loaded indicator from Window(10000)."""
    try:
        control.clearGlobalProp(ACTIVE_SUB_META_PROP)
        control.clearGlobalProp('otaku.subtitle.auto_loaded')
        control.clearGlobalProp('otaku.subtitle.auto_label')
        control.clearGlobalProp('otaku.embed_sub_signs_only')
        control.clearGlobalProp('otaku.embed_sub_has_full_dialog')
    except Exception:
        pass


def get_active_playback_meta() -> Dict[str, Any]:
    """Read active-playback metadata published by WatchlistPlayer (if available)."""
    try:
        raw = control.getGlobalProp(ACTIVE_SUB_META_PROP)
        if raw:
            parsed = control.loads_json(raw, default={})
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass
    return {}


def parse_manual_search_query(search_string: str) -> Dict[str, str]:
    """
    Parse optional season/episode/year tokens from a manual search query string.
    Examples:
      'Frieren S01E05' -> {'title': 'Frieren', 'season': '1', 'episode': '5', 'year': ''}
      'One Piece 1120' -> {'title': 'One Piece', 'season': '', 'episode': '1120', 'year': ''}
      'Spirited Away 2001' -> {'title': 'Spirited Away', 'season': '', 'episode': '', 'year': '2001'}
    """
    raw = str(search_string or '').strip()
    if not raw:
        return {'title': '', 'season': '', 'episode': '', 'year': ''}

    season = ''
    episode = ''
    year = ''
    clean = raw

    # Match S01E05 or 1x05
    m_se = re.search(r'\b(?:s(\d{1,2})[._\s\-]?e(\d{1,4})|(\d{1,2})x(\d{1,4}))\b', clean, re.IGNORECASE)
    if m_se:
        season = str(int(m_se.group(1) or m_se.group(3)))
        episode = str(int(m_se.group(2) or m_se.group(4)))
        clean = (clean[:m_se.start()] + ' ' + clean[m_se.end():]).strip()
    else:
        # Match "Season 2 Episode 5"
        m_word = re.search(r'\bseason\s*(\d{1,2})\s*(?:episode|ep\.?)\s*(\d{1,4})\b', clean, re.IGNORECASE)
        if m_word:
            season = str(int(m_word.group(1)))
            episode = str(int(m_word.group(2)))
            clean = (clean[:m_word.start()] + ' ' + clean[m_word.end():]).strip()
        else:
            # Match standalone "Ep 05" / "Episode 5" / "E05"
            m_ep = re.search(r'\b(?:episode|ep\.?|e)\s*(\d{1,4})\b', clean, re.IGNORECASE)
            if m_ep:
                episode = str(int(m_ep.group(1)))
                clean = (clean[:m_ep.start()] + ' ' + clean[m_ep.end():]).strip()

    # Match 4-digit year (1950-2039)
    m_yr = re.search(r'\b(19[5-9]\d|20[0-3]\d)\b', clean)
    if m_yr:
        year = m_yr.group(1)
        clean = (clean[:m_yr.start()] + ' ' + clean[m_yr.end():]).strip()

    clean = re.sub(r'[\s._\-]+$', '', re.sub(r'\s{2,}', ' ', clean)).strip()
    return {
        'title': clean or raw,
        'season': season,
        'episode': episode,
        'year': year,
    }


def get_meta_from_player(
    languages_list: Optional[List[str]] = None,
    preferred_lang: Optional[str] = None,
) -> VideoMeta:
    """Extracts VideoMeta from the active Kodi player instance and Otaku active-playback context."""
    title = ''
    tvshow = ''
    original_title = ''
    season = ''
    episode = ''
    year = ''
    imdb_id = ''
    mal_id = ''
    filename = ''

    # 0. Active Otaku playback context (rich MAL/IMDb/Romaji/release filename metadata)
    active = get_active_playback_meta()
    if active:
        mal_id = str(active.get('mal_id') or '')
        imdb_id = str(active.get('imdb_id') or '')
        tvshow = str(active.get('tvshow') or '')
        title = str(active.get('title') or '')
        original_title = str(active.get('original_title') or '')
        season = str(active.get('season') or '')
        episode = str(active.get('episode') or '')
        year = str(active.get('year') or '')
        filename = str(active.get('filename') or '')

    # 1. InfoTagVideo API (Kodi 20+)
    try:
        player = xbmc.Player()
        if player.isPlaying():
            vinfo = player.getVideoInfoTag()
            if vinfo:
                season = season or str(vinfo.getSeason() or '')
                episode = episode or str(vinfo.getEpisode() or '')
                year = year or str(vinfo.getYear() or '')
                tvshow = tvshow or (vinfo.getTVShowTitle() or '')
                title = title or (vinfo.getTitle() or '')
                original_title = original_title or (vinfo.getOriginalTitle() or '')
                imdb_id = imdb_id or (vinfo.getUniqueID('imdb') or '')
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

    # 2b. Fill remaining gaps from offline mappings.db when mal_id is known
    imdb_id, year, tvshow, original_title, season = _enrich_sub_fields_from_mappings(
        mal_id, imdb_id=imdb_id, year=year, tvshow=tvshow, original_title=original_title, season=season
    )

    # 3. Clean Filename
    if not filename:
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

    # Preferred language from caller (Kodi DialogSubtitles) or Otaku/Kodi settings
    if preferred_lang is not None and str(preferred_lang).strip():
        pref_raw = str(preferred_lang).strip()
        pref_code = 'none' if pref_raw.lower() == 'none' else languages.to_iso639_1(pref_raw)
    else:
        pref_code = languages.get_preferred_subtitle_language()

    if languages_list:
        clean_langs = [languages.to_english_name(l) for l in languages_list if str(l or '').strip()]
    elif pref_code == "none":
        clean_langs = []
    else:
        clean_langs = [languages.to_english_name(pref_code)]

    anime_ctx = _resolve_anime_ids_and_groups(mal_id, season=season, episode=episode, filename=filename)
    anilist_id = str(active.get('anilist_id') or anime_ctx['anilist_id'] or '') if active else anime_ctx['anilist_id']
    anidb_id = str(active.get('anidb_id') or anime_ctx['anidb_id'] or '') if active else anime_ctx['anidb_id']
    anidb_ep_id = str(active.get('anidb_ep_id') or anime_ctx['anidb_ep_id'] or '') if active else anime_ctx['anidb_ep_id']
    kitsu_id = str(active.get('kitsu_id') or anime_ctx['kitsu_id'] or '') if active else anime_ctx['kitsu_id']
    release_group = str(active.get('release_group') or anime_ctx['release_group'] or '') if active else anime_ctx['release_group']
    preferred_group = str(active.get('preferred_group') or anime_ctx['preferred_group'] or '') if active else anime_ctx['preferred_group']

    return VideoMeta(
        title=title,
        tvshow=tvshow,
        original_title=original_title,
        season=season,
        episode=episode,
        year=year,
        imdb_id=imdb_id,
        filename=filename,
        languages=clean_langs,
        preferred_lang=pref_code,
        mal_id=mal_id,
        anilist_id=anilist_id,
        anidb_id=anidb_id,
        anidb_ep_id=anidb_ep_id,
        kitsu_id=kitsu_id,
        release_group=release_group,
        preferred_group=preferred_group,
    )


def get_meta_for_manual_search(
    search_string: str,
    languages_list: Optional[List[str]] = None,
    preferred_lang: Optional[str] = None,
) -> VideoMeta:
    """Builds VideoMeta for a user-supplied manual subtitle search query."""
    base_meta = get_meta_from_player(languages_list=languages_list, preferred_lang=preferred_lang)
    parsed = parse_manual_search_query(search_string)
    query_title = parsed['title'] or base_meta.tvshow or base_meta.title
    season = parsed['season']
    episode = parsed['episode']
    year = parsed['year']
    is_tv = bool(season or episode)

    # Keep active player filename only for optional release-match badge highlighting
    pref_code = base_meta.preferred_lang
    if pref_code == 'none':
        # Manual search explicitly requested by user: default to English if preferred was 'none'
        pref_code = languages.to_iso639_1(languages_list[0]) if languages_list else 'en'
        langs = [languages.to_english_name(l) for l in (languages_list or ['English']) if str(l or '').strip()]
    else:
        langs = base_meta.languages or [languages.to_english_name(pref_code)]

    return VideoMeta(
        title=query_title,
        tvshow=query_title if is_tv else '',
        original_title='',
        season=season,
        episode=episode,
        year=year,
        imdb_id='',
        filename=base_meta.filename,
        languages=langs,
        preferred_lang=pref_code,
        is_tvshow=is_tv,
        search_string=str(search_string or '').strip(),
        is_manual_search=True,
        mal_id=base_meta.mal_id,
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

    imdb_id, year, tvshow, original_title, season = _enrich_sub_fields_from_mappings(
        mal_id, imdb_id=imdb_id, year=year, tvshow=tvshow, original_title=original_title, season=season
    )

    clean_filename = str(video_info.get('release_title') or source_utils.format_video_filename(video_info) or '')
    anime_ctx = _resolve_anime_ids_and_groups(mal_id, season=season, episode=episode, filename=clean_filename)
    anilist_id = str((unique_ids.get('anilist_id') if isinstance(unique_ids, dict) else '') or anime_ctx['anilist_id'] or '')
    anidb_id = str((unique_ids.get('anidb') or unique_ids.get('anidb_id') if isinstance(unique_ids, dict) else '') or anime_ctx['anidb_id'] or '')
    anidb_ep_id = str(video_info.get('anidb_ep_id') or anime_ctx['anidb_ep_id'] or '')
    kitsu_id = str((unique_ids.get('kitsu_id') if isinstance(unique_ids, dict) else '') or anime_ctx['kitsu_id'] or '')

    pref_code = languages.get_preferred_subtitle_language()
    if pref_code == "none":
        pref_name = "none"
        languages_list = []
    else:
        pref_name = languages.to_english_name(pref_code)
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
        mal_id=str(mal_id or ''),
        anilist_id=anilist_id,
        anidb_id=anidb_id,
        anidb_ep_id=anidb_ep_id,
        kitsu_id=kitsu_id,
        release_group=anime_ctx['release_group'],
        preferred_group=anime_ctx['preferred_group'],
    )
