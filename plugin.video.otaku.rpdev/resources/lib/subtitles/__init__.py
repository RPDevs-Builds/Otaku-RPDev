"""__init__.py - Otaku-RPDev Native Subtitles Engine
===================================================
High-level API for searching, downloading, auto-identifying, and auto-injecting
external subtitles across multi-provider backends, shared by both WatchlistPlayer
and the companion Kodi subtitle service (service.subtitles.otaku.rpdev).
"""

# -*- coding: utf-8 -*-

import os
from typing import Optional, List, Dict, Any
import xbmc
import xbmcgui

from resources.lib.ui import control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages
from resources.lib.subtitles.search import search_all_services, score_result
from resources.lib.subtitles.download import download_and_prepare_subtitle, purge_temp_subtitles
from resources.lib.subtitles.meta import (
    get_meta_from_player,
    get_meta_from_dict,
    get_meta_for_manual_search,
    parse_manual_search_query,
    publish_active_playback_meta,
    clear_active_playback_meta,
    get_active_playback_meta,
)

SUBTITLE_SERVICE_ADDON_ID = 'service.subtitles.otaku.rpdev'


def get_subtitles_settings() -> Dict[str, Any]:
    """Retrieve all subtitle settings from Settings - Otaku RPDev > Subtitles."""
    return {
        'subtitles.enabled': control.getBool('subtitles.enabled', True),
        'subtitles.auto_search': control.getBool('subtitles.auto_search', True),
        'subtitles.auto_download': control.getBool('subtitles.auto_download', True),
        'subtitles.prefer_sdh': control.getBool('subtitles.prefer_sdh', False),
        'subtitles.prefer_forced': control.getBool('subtitles.prefer_forced', False),
        'subtitles.strip_sdh_tags': control.getBool('subtitles.strip_sdh_tags', False),
        'subtitles.auto_calibrate_chapters': control.getBool('subtitles.auto_calibrate_chapters', False),
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
        'subtitles.provider.jimaku': control.getBool('subtitles.provider.jimaku', True),
        'subtitles.jimaku.apikey': control.getSetting('subtitles.jimaku.apikey') or '',
        'subtitles.provider.animetosho': control.getBool('subtitles.provider.animetosho', True),
    }


def format_result_badge(result: SubtitleResult) -> str:
    """Return a Kodi BBCode indicator badge showing auto-identification status and match reason."""
    reason = result.match_reason.strip() if result.match_reason else ''
    if result.auto_identified:
        color = 'springgreen' if result.match_confidence == 'exact' else 'cyan'
        tag = f"AUTO • {reason}" if reason else "AUTO"
        return f"[B][COLOR {color}][{tag}][/COLOR][/B]"
    if result.match_confidence == 'manual' or reason == 'Manual':
        return "[B][COLOR gold][MANUAL][/COLOR][/B]"
    return ""


def format_kodi_listitem_label2(result: SubtitleResult) -> str:
    """Format label2 for Kodi's native DialogSubtitles.xml with auto-identified indicator, ext, provider & flags."""
    raw_name = str(result.name or 'Subtitle').strip()
    stripped_name = raw_name
    for comp_ext in ('.xz', '.gz', '.zip'):
        if stripped_name.lower().endswith(comp_ext):
            stripped_name = stripped_name[:-len(comp_ext)]
            break
    base, ext = os.path.splitext(stripped_name)
    if ext.lower() in ('.srt', '.ass', '.ssa', '.vtt', '.sub'):
        clean_name = (base or stripped_name).replace('.', ' ').strip()
        ext_upper = ext.lstrip('.').upper()
    elif getattr(result, 'subtitle_format', ''):
        clean_name = stripped_name.replace('.', ' ').strip()
        ext_upper = str(result.subtitle_format).upper()
    else:
        clean_name = stripped_name.replace('.', ' ').strip()
        ext_upper = 'SRT'
    badge = format_result_badge(result)
    sdh_tag = " [B][SDH][/B]" if result.impaired else ""
    forced_tag = " [B][Forced][/B]" if result.forced else ""
    provider_color = result.color or 'springgreen'
    prefix = f"{badge} " if badge else ""
    return f"{prefix}{clean_name} ([B]{ext_upper}[/B]) ([B][COLOR {provider_color}]{result.display_name}[/COLOR][/B]){sdh_tag}{forced_tag}"


def format_dialog_label(result: SubtitleResult) -> str:
    """Format a row label for Otaku's interactive select dialog with auto-identified indicator."""
    badge = format_result_badge(result)
    prefix = f"{badge} " if badge else ""
    sdh_tag = " [SDH]" if result.impaired else ""
    forced_tag = " [Forced]" if result.forced else ""
    return f"{prefix}[{result.display_name}] {result.name} ({result.lang}){sdh_tag}{forced_tag}"


def search_subtitles(meta: Optional[VideoMeta] = None, settings: Optional[Dict[str, Any]] = None) -> List[SubtitleResult]:
    """Search for subtitles across all enabled providers."""
    if meta is None:
        meta = get_meta_from_player()
    if settings is None:
        settings = get_subtitles_settings()

    if not settings.get('subtitles.enabled', True):
        return []

    # If preferred language is "none" during automatic search, skip external scraping
    if not meta.is_manual_search and (not meta.preferred_lang or meta.preferred_lang.lower() == 'none'):
        control.log("Native Subtitles: Preferred subtitle language is 'none', skipping external search", 'info')
        return []

    return search_all_services(meta, settings)


def manual_search_subtitles(
    search_string: str,
    languages_list: Optional[List[str]] = None,
    preferred_lang: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> List[SubtitleResult]:
    """Execute a manual keyword subtitle search across all enabled providers."""
    if settings is None:
        settings = get_subtitles_settings()
    if not settings.get('subtitles.enabled', True):
        return []
    meta = get_meta_for_manual_search(
        search_string,
        languages_list=languages_list,
        preferred_lang=preferred_lang,
    )
    return search_all_services(meta, settings)


def download_subtitle(
    result: SubtitleResult,
    meta: Optional[VideoMeta] = None,
    settings: Optional[Dict[str, Any]] = None,
    dest_dir: Optional[str] = None,
) -> Optional[str]:
    """Download, validate for Kodi 22, transcode to UTF-8, and return the local filesystem path."""
    if meta is None:
        meta = get_meta_from_player()
    if settings is None:
        settings = get_subtitles_settings()

    return download_and_prepare_subtitle(result, meta, settings, dest_dir=dest_dir)


def auto_download_subtitles(meta: Optional[VideoMeta] = None, settings: Optional[Dict[str, Any]] = None) -> bool:
    """
    End-to-end auto-search and auto-download pipeline triggered during playback
    when no matching subtitle stream is available.
    Prioritizes automatically identified candidates and attaches the best valid match.
    """
    if settings is None:
        settings = get_subtitles_settings()

    if not settings.get('subtitles.enabled', True):
        return False

    if not settings.get('subtitles.auto_search', True):
        return False

    if meta is None:
        meta = get_meta_from_player()

    # If preferred language is "none", do not auto-download external subtitles
    if not meta.preferred_lang or meta.preferred_lang.lower() == 'none':
        control.log("Native Subtitles: Preferred subtitle language is 'none', skipping auto-download", 'info')
        return False

    control.log(
        f"Native Subtitles: Initiating auto-search for {meta.tvshow or meta.title} "
        f"S{meta.season}E{meta.episode} (pref_lang={meta.preferred_lang})",
        'info',
    )
    results = search_subtitles(meta, settings)

    if not results:
        control.log("Native Subtitles: No external subtitles found", 'info')
        return False

    if not settings.get('subtitles.auto_download', True):
        # Auto-download is disabled: prompt user with selection dialog
        return manual_select_dialog(results, meta, settings)

    # Attempt download on highest ranking candidates matching preferred language.
    # Prioritize non-Season-Pack candidates first so unverified packs cannot exhaust MAX_AUTO_ATTEMPTS.
    MAX_AUTO_ATTEMPTS = 6
    MAX_PACK_ATTEMPTS = 3
    non_pack_candidates = [c for c in results if getattr(c, 'match_reason', '') != 'Season Pack']
    pack_candidates = [c for c in results if getattr(c, 'match_reason', '') == 'Season Pack']
    ordered_candidates = non_pack_candidates + pack_candidates[:MAX_PACK_ATTEMPTS]
    attempts = 0
    for candidate in ordered_candidates:
        if getattr(candidate, 'match_reason', '') in ('Mismatch', 'Title Mismatch'):
            control.log(
                f"Native Subtitles: Skipping {candidate.name} ({candidate.match_reason})",
                'debug',
            )
            continue
        if attempts >= MAX_AUTO_ATTEMPTS:
            break

        player = xbmc.Player()
        if not player.isPlaying():
            control.log("Native Subtitles: Playback stopped; aborting auto-download", 'info')
            return False

        cand_code = candidate.lang_code or languages.to_iso639_1(candidate.lang)
        if not languages.is_language_match(cand_code, meta.preferred_lang):
            control.log(
                f"Native Subtitles: Skipping {candidate.name} ({candidate.lang}) - "
                f"does not match preferred {meta.preferred_lang}",
                'debug',
            )
            continue

        attempts += 1
        local_path = download_subtitle(candidate, meta, settings)
        if local_path:
            if player.isPlaying():
                player.setSubtitles(local_path)
                player.showSubtitles(True)
                try:
                    cur_t = float(player.getTime() or 0.0)
                    if cur_t > 5.0:
                        player.seekTime(max(0.0, cur_t - 0.25))
                except Exception:
                    pass
                reason = candidate.match_reason or ('Auto' if candidate.auto_identified else 'Match')
                auto_tag = f"Auto • {reason}" if candidate.auto_identified else reason
                label_text = f"[{auto_tag}] {candidate.name[:32]} ({candidate.display_name})"
                control.setGlobalProp('otaku.subtitle.auto_loaded', 'true')
                control.setGlobalProp('otaku.subtitle.auto_label', label_text)
                control.notify(
                    control.ADDON_NAME,
                    f"Subtitles {label_text}",
                    time=4000,
                )
                control.log(
                    f"Native Subtitles: Successfully attached {local_path} from {candidate.service_name} "
                    f"(auto_identified={candidate.auto_identified}, reason={reason})",
                    'info',
                )
                return True

    control.log(
        f"Native Subtitles: Auto-download checked {len(results)} candidate(s) (attempted={attempts}) "
        f"but none were usable for {meta.tvshow or meta.title} S{meta.season}E{meta.episode}",
        'info',
    )
    return False


def manual_select_dialog(
    results: List[SubtitleResult],
    meta: Optional[VideoMeta] = None,
    settings: Optional[Dict[str, Any]] = None,
    allow_manual_search: bool = True,
) -> bool:
    """Displays an interactive selection dialog with auto-identified indicators and manual search."""
    if meta is None:
        meta = get_meta_from_player()
    if settings is None:
        settings = get_subtitles_settings()

    dialog = xbmcgui.Dialog()
    current_results = list(results or [])
    current_meta = meta

    while True:
        items = []
        if allow_manual_search:
            items.append("[B][COLOR gold][Manual Search...][/COLOR][/B] Enter custom title / episode")

        for r in current_results:
            items.append(format_dialog_label(r))

        if not current_results and not allow_manual_search:
            control.notify(control.ADDON_NAME, "No subtitles found", time=3000)
            return False

        heading = "Select Subtitle" if current_results else "No Automatic Matches — Try Manual Search"
        idx = dialog.select(heading, items)
        if idx < 0:
            return False

        if allow_manual_search and idx == 0:
            default_query = current_meta.search_string or current_meta.tvshow or current_meta.title or ''
            query = dialog.input("Manual Subtitle Search", defaultt=default_query)
            if not query or not str(query).strip():
                return False
            current_meta = get_meta_for_manual_search(
                str(query).strip(),
                languages_list=current_meta.languages,
                preferred_lang=current_meta.preferred_lang,
            )
            p_dlg = control.progressDialog
            p_dlg.create(control.ADDON_NAME, f"Searching subtitles for '{current_meta.search_string}'...")
            try:
                current_results = search_subtitles(current_meta, settings)
            finally:
                p_dlg.close()
            if not current_results:
                control.notify(control.ADDON_NAME, f"No subtitles found for '{current_meta.search_string}'", time=3000)
            continue

        result_idx = idx - 1 if allow_manual_search else idx
        if result_idx < 0 or result_idx >= len(current_results):
            return False

        chosen = current_results[result_idx]
        local_path = download_subtitle(chosen, current_meta, settings)
        if local_path:
            player = xbmc.Player()
            if player.isPlaying():
                player.setSubtitles(local_path)
                player.showSubtitles(True)
                try:
                    cur_t = float(player.getTime() or 0.0)
                    if cur_t > 5.0:
                        player.seekTime(max(0.0, cur_t - 0.25))
                except Exception:
                    pass
                reason = chosen.match_reason or ('Auto' if chosen.auto_identified else 'Manual')
                control.setGlobalProp('otaku.subtitle.auto_loaded', 'true' if chosen.auto_identified else 'false')
                control.setGlobalProp('otaku.subtitle.auto_label', f"[{reason}] {chosen.name[:32]} ({chosen.display_name})")
                control.notify(
                    control.ADDON_NAME,
                    f"Subtitles [{reason}]: {chosen.name[:30]} ({chosen.display_name})",
                    time=3500,
                )
                return True
            return False

        control.notify(control.ADDON_NAME, f"Download failed from {chosen.display_name}", time=3000)
        return False


def set_as_kodi_default_subtitle_service() -> bool:
    """Configure Kodi's default TV show and movie subtitle service to Otaku RPDev Subtitles."""
    ok_tv = False
    ok_movie = False
    for key in ('subtitles.tv', 'subtitles.movie'):
        try:
            res = control.jsonrpc({
                'jsonrpc': '2.0',
                'method': 'Settings.SetSettingValue',
                'params': {'setting': key, 'value': SUBTITLE_SERVICE_ADDON_ID},
                'id': 1,
            })
            success = bool(isinstance(res, dict) and res.get('result') is True)
            if key == 'subtitles.tv':
                ok_tv = success
            else:
                ok_movie = success
        except Exception as e:
            control.log(f"Native Subtitles: Failed setting {key} to {SUBTITLE_SERVICE_ADDON_ID}: {e}", 'warning')

    if ok_tv or ok_movie:
        control.notify(
            control.ADDON_NAME,
            "Kodi default subtitle service set to Otaku RPDev Subtitles",
            time=3500,
        )
        control.log(f"Native Subtitles: Configured Kodi subtitles.tv={ok_tv}, subtitles.movie={ok_movie}", 'info')
        return True

    control.notify(
        control.ADDON_NAME,
        "Install/enable Otaku RPDev Subtitles in Kodi Add-ons first",
        time=4000,
    )
    return False
