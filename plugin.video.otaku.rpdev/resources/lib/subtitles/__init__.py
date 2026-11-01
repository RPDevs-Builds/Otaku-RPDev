"""__init__.py - Otaku-RPDev Native Subtitles Engine
===================================================
High-level API for searching, downloading, and auto-injecting
external subtitles across multi-provider backends.
"""

# -*- coding: utf-8 -*-

from typing import Optional, List, Dict, Any
import xbmc
import xbmcgui

from resources.lib.ui import control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles.search import search_all_services
from resources.lib.subtitles.download import download_and_prepare_subtitle, purge_temp_subtitles
from resources.lib.subtitles.meta import get_meta_from_player, get_meta_from_dict


def get_subtitles_settings() -> Dict[str, Any]:
    """Retrieve all subtitle settings from addon configuration."""
    return {
        'subtitles.enabled': control.getBool('subtitles.enabled', True),
        'subtitles.auto_search': control.getBool('subtitles.auto_search', True),
        'subtitles.auto_download': control.getBool('subtitles.auto_download', True),
        'subtitles.auto_select': control.getBool('subtitles.auto_select', True),
        'subtitles.prefer_sdh': control.getBool('subtitles.prefer_sdh', False),
        'subtitles.prefer_forced': control.getBool('subtitles.prefer_forced', False),
        'subtitles.use_chardet': control.getBool('subtitles.use_chardet', True),
        'subtitles.timeout': control.getInt('subtitles.timeout') or 15,
        'subtitles.results_limit': control.getInt('subtitles.results_limit') or 20,
        # Provider toggles & credentials
        'subtitles.provider.opensubtitles': control.getBool('subtitles.provider.opensubtitles', True),
        'subtitles.opensubtitles.username': control.getSetting('subtitles.opensubtitles.username') or '',
        'subtitles.opensubtitles.password': control.getSetting('subtitles.opensubtitles.password') or '',
        'subtitles.provider.subdl': control.getBool('subtitles.provider.subdl', True),
        'subtitles.subdl.apikey': control.getSetting('subtitles.subdl.apikey') or '',
        'subtitles.provider.subsource': control.getBool('subtitles.provider.subsource', True),
        'subtitles.subsource.apikey': control.getSetting('subtitles.subsource.apikey') or '',
        'subtitles.provider.podnadpisi': control.getBool('subtitles.provider.podnadpisi', True),
        'subtitles.provider.bsplayer': control.getBool('subtitles.provider.bsplayer', True),
        'subtitles.provider.addic7ed': control.getBool('subtitles.provider.addic7ed', True),
    }


def search_subtitles(meta: Optional[VideoMeta] = None, settings: Optional[Dict[str, Any]] = None) -> List[SubtitleResult]:
    """Search for subtitles across all enabled providers."""
    if meta is None:
        meta = get_meta_from_player()
    if settings is None:
        settings = get_subtitles_settings()

    if not settings.get('subtitles.enabled', True):
        return []

    return search_all_services(meta, settings)


def download_subtitle(result: SubtitleResult, meta: Optional[VideoMeta] = None, settings: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Download, transcode to UTF-8, and return the local filesystem path."""
    if meta is None:
        meta = get_meta_from_player()
    if settings is None:
        settings = get_subtitles_settings()

    return download_and_prepare_subtitle(result, meta, settings)


def auto_download_subtitles(meta: Optional[VideoMeta] = None, settings: Optional[Dict[str, Any]] = None) -> bool:
    """
    End-to-end auto-search and auto-download pipeline triggered during playback.
    Finds top match and attaches it to the active Kodi player.
    """
    if settings is None:
        settings = get_subtitles_settings()

    if not settings.get('subtitles.enabled', True):
        return False

    if not settings.get('subtitles.auto_search', True):
        return False

    if meta is None:
        meta = get_meta_from_player()

    control.log(f"Native Subtitles: Initiating auto-search for {meta.tvshow or meta.title} S{meta.season}E{meta.episode}", 'info')
    results = search_subtitles(meta, settings)

    if not results:
        control.log("Native Subtitles: No external subtitles found", 'info')
        return False

    if not settings.get('subtitles.auto_download', True):
        # Auto-download is disabled: prompt user with selection dialog
        return manual_select_dialog(results, meta, settings)

    # Attempt download on highest ranking candidates
    for candidate in results:
        local_path = download_subtitle(candidate, meta, settings)
        if local_path:
            player = xbmc.Player()
            if player.isPlaying():
                player.setSubtitles(local_path)
                player.showSubtitles(True)
                control.notify(
                    control.ADDON_NAME,
                    f"Subtitles: Loaded {candidate.name[:30]} ({candidate.display_name})",
                    time=3500
                )
                control.log(f"Native Subtitles: Successfully attached {local_path} from {candidate.service_name}", 'info')
                return True

    return False


def manual_select_dialog(results: List[SubtitleResult], meta: VideoMeta, settings: Dict[str, Any]) -> bool:
    """Displays an interactive selection dialog for subtitles."""
    if not results:
        control.notify(control.ADDON_NAME, "No subtitles found", time=3000)
        return False

    items = []
    for r in results:
        sdh_tag = " [SDH]" if r.impaired else ""
        forced_tag = " [Forced]" if r.forced else ""
        label = f"[{r.display_name}] {r.name} ({r.lang}){sdh_tag}{forced_tag}"
        items.append(label)

    dialog = xbmcgui.Dialog()
    idx = dialog.select("Select Subtitle", items)
    if idx < 0:
        return False

    chosen = results[idx]
    local_path = download_subtitle(chosen, meta, settings)
    if local_path:
        player = xbmc.Player()
        if player.isPlaying():
            player.setSubtitles(local_path)
            player.showSubtitles(True)
            control.notify(control.ADDON_NAME, f"Subtitles loaded: {chosen.name[:30]}", time=3000)
            return True

    return False
