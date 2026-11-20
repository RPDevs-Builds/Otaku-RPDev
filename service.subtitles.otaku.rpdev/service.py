# -*- coding: utf-8 -*-
"""
service.subtitles.otaku.rpdev/service.py - Kodi xbmc.subtitle.module Integration
================================================================================
Bridges Kodi's native OSD "Subtitle settings > Download subtitle" dialog
(Window 10153 / DialogSubtitles.xml) directly into Otaku-RPDev's built-in
multi-provider subtitle engine and Settings - Otaku RPDev > Subtitles.

Supports:
  - action=search       : Automatic subtitle identification & parallel search
  - action=manualsearch : Custom keyboard manual search across all enabled services
  - action=download     : Download, archive extraction, Kodi 22 validation & attach
"""

import json
import os
import sys
import urllib.parse
from typing import Dict, Any, List, Optional

import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

PLUGIN_ADDON_ID = 'plugin.video.otaku.rpdev'
SUBTITLE_ADDON_ID = 'service.subtitles.otaku.rpdev'


def _ensure_otaku_plugin_on_path() -> Optional[str]:
    """Locate plugin.video.otaku.rpdev and ensure it is on sys.path."""
    candidates = []
    try:
        addon_path = xbmcaddon.Addon(PLUGIN_ADDON_ID).getAddonInfo('path')
        if addon_path:
            translated = xbmcvfs.translatePath(addon_path)
            if translated:
                candidates.append(translated)
    except Exception:
        pass

    # Fallback: sibling directory in repository / local dev / offline tests
    repo_sibling = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        PLUGIN_ADDON_ID,
    )
    candidates.append(repo_sibling)

    for path in candidates:
        if path and os.path.isdir(path):
            if path not in sys.path:
                sys.path.insert(0, path)
            return path
    return None


def _get_service_temp_dir() -> Optional[str]:
    """Resolve service.subtitles.otaku.rpdev's own profile temp directory."""
    try:
        profile_path = xbmcaddon.Addon(SUBTITLE_ADDON_ID).getAddonInfo('profile')
        if profile_path:
            translated = xbmcvfs.translatePath(profile_path)
            if translated:
                temp_dir = os.path.join(translated, 'temp')
                try:
                    if hasattr(xbmcvfs, 'mkdirs'):
                        xbmcvfs.mkdirs(temp_dir)
                except Exception:
                    pass
                os.makedirs(temp_dir, exist_ok=True)
                return temp_dir
    except Exception:
        pass
    return None


def _parse_query_params(param_string: str) -> Dict[str, str]:
    """Parse Kodi sys.argv[2] query string cleanly."""
    raw = str(param_string or '')
    if raw.startswith('?'):
        raw = raw[1:]
    return dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))


def _parse_languages_param(raw_languages: str) -> List[str]:
    """Parse Kodi's comma-separated URL-encoded 'languages' parameter."""
    if not raw_languages:
        return []
    unquoted = urllib.parse.unquote(str(raw_languages))
    return [part.strip() for part in unquoted.split(',') if part.strip()]


def create_subtitle_listitem(result, subtitles_mod) -> xbmcgui.ListItem:
    """
    Build a Kodi DialogSubtitles.xml ListItem with:
      - Country flag icon (thumb) and 0-5 star rating (icon)
      - Native Kodi SYNC badge (sync='true') for automatically identified matches
      - Native Kodi CC badge (hearing_imp='true') for SDH subtitles
      - Color-coded [AUTO • Reason] / [MANUAL] indicator in label2
    """
    label = str(result.lang or 'English')
    label2 = subtitles_mod.format_kodi_listitem_label2(result)
    listitem = xbmcgui.ListItem(label=label, label2=label2, offscreen=True)

    rating_int = int(round(min(5.0, max(0.0, float(result.rating or 0.0)))))
    flag_code = str(result.lang_code or 'en').lower()
    listitem.setArt({
        'icon': str(rating_int),
        'thumb': flag_code,
    })

    # Native Kodi SYNC indicator lights up for exact hash/release or auto-identified matches
    is_sync = bool(result.sync or result.auto_identified)
    listitem.setProperty('sync', 'true' if is_sync else 'false')
    listitem.setProperty('hearing_imp', 'true' if result.impaired else 'false')
    listitem.setProperty('otaku.auto_identified', 'true' if result.auto_identified else 'false')
    listitem.setProperty('otaku.match_reason', str(result.match_reason or ''))
    listitem.setProperty('otaku.service', str(result.service_name or ''))
    return listitem


def _build_download_url(result) -> str:
    """Encode SubtitleResult fields into a compact plugin:// download URL."""
    payload_dict = {
        'service_name': str(result.service_name or ''),
        'display_name': str(result.display_name or ''),
        'name': str(result.name or ''),
        'lang': str(result.lang or 'English'),
        'lang_code': str(result.lang_code or 'en'),
        'download_url': str(result.download_url or ''),
        'action_args': dict(result.action_args or {}),
        'season': result.season,
        'episode': result.episode,
        'auto_identified': bool(result.auto_identified),
        'match_reason': str(result.match_reason or ''),
    }
    encoded = urllib.parse.quote_plus(json.dumps(payload_dict, separators=(',', ':')))
    return f"plugin://{SUBTITLE_ADDON_ID}/?action=download&payload={encoded}"


def _emit_search_results(handle: int, results, subtitles_mod) -> int:
    """Populate Kodi DialogSubtitles directory with ranked subtitle results."""
    count = 0
    for result in results:
        li = create_subtitle_listitem(result, subtitles_mod)
        url = _build_download_url(result)
        xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=li, isFolder=False)
        count += 1
    return count


def handle_request(handle: int, param_string: str) -> int:
    """
    Main Kodi xbmc.subtitle.module request dispatcher.
    Returns number of directory items emitted (useful for deterministic unit tests).
    """
    _ensure_otaku_plugin_on_path()
    from resources.lib.ui import control
    from resources.lib import subtitles
    from resources.lib.subtitles.models import SubtitleResult

    params = _parse_query_params(param_string)
    action = str(params.get('action', '') or '').strip().lower()
    emitted = 0

    try:
        settings = subtitles.get_subtitles_settings()
        if not settings.get('subtitles.enabled', True):
            control.notify(control.ADDON_NAME, "Native Subtitles disabled in Otaku RPDev Settings", time=3000)
            return 0

        req_langs = _parse_languages_param(params.get('languages', ''))
        pref_lang_raw = urllib.parse.unquote(str(params.get('preferredlanguage', '') or '')).strip()
        pref_lang = pref_lang_raw if pref_lang_raw and pref_lang_raw.lower() not in ('default', 'original', 'forced_only') else None

        if action == 'search':
            meta = subtitles.get_meta_from_player(
                languages_list=req_langs or None,
                preferred_lang=pref_lang,
            )
            control.log(
                f"Subtitle Service: action=search for '{meta.tvshow or meta.title}' "
                f"S{meta.season}E{meta.episode} langs={meta.languages} pref={meta.preferred_lang}",
                'info',
            )
            results = subtitles.search_subtitles(meta, settings)
            emitted = _emit_search_results(handle, results, subtitles)
            control.log(f"Subtitle Service: action=search returned {emitted} result(s)", 'info')

        elif action == 'manualsearch':
            search_string = urllib.parse.unquote_plus(str(params.get('searchstring', '') or '')).strip()
            if not search_string:
                control.notify(control.ADDON_NAME, "Enter a search query for manual subtitle search", time=3000)
                return 0
            meta = subtitles.get_meta_for_manual_search(
                search_string,
                languages_list=req_langs or None,
                preferred_lang=pref_lang,
            )
            control.log(
                f"Subtitle Service: action=manualsearch query='{search_string}' "
                f"parsed=({meta.title!r}, S{meta.season}E{meta.episode}) langs={meta.languages}",
                'info',
            )
            results = subtitles.search_subtitles(meta, settings)
            emitted = _emit_search_results(handle, results, subtitles)
            control.log(f"Subtitle Service: action=manualsearch returned {emitted} result(s)", 'info')

        elif action == 'download':
            raw_payload = urllib.parse.unquote_plus(str(params.get('payload', '') or ''))
            data = control.loads_json(raw_payload, default={})
            if not isinstance(data, dict) or not data.get('service_name'):
                control.log("Subtitle Service: action=download received invalid payload", 'warning')
                return 0

            result = SubtitleResult(
                service_name=str(data.get('service_name') or ''),
                display_name=str(data.get('display_name') or data.get('service_name') or ''),
                name=str(data.get('name') or 'subtitle.srt'),
                lang=str(data.get('lang') or 'English'),
                lang_code=str(data.get('lang_code') or 'en'),
                download_url=str(data.get('download_url') or ''),
                action_args=data.get('action_args') if isinstance(data.get('action_args'), dict) else {},
                season=data.get('season'),
                episode=data.get('episode'),
                auto_identified=bool(data.get('auto_identified', False)),
                match_reason=str(data.get('match_reason') or ''),
            )
            meta = subtitles.get_meta_from_player()
            service_temp_dir = _get_service_temp_dir()
            local_path = subtitles.download_subtitle(result, meta, settings, dest_dir=service_temp_dir)
            if local_path:
                li = xbmcgui.ListItem(label=str(local_path), offscreen=True)
                xbmcplugin.addDirectoryItem(handle=handle, url=str(local_path), listitem=li, isFolder=False)
                reason = result.match_reason or ('Auto' if result.auto_identified else 'Manual')
                control.setGlobalProp('otaku.subtitle.auto_loaded', 'true' if result.auto_identified else 'false')
                control.setGlobalProp('otaku.subtitle.auto_label', f"[{reason}] {result.name[:32]} ({result.display_name})")
                emitted = 1
                control.log(f"Subtitle Service: action=download prepared {local_path}", 'info')
            else:
                control.notify(control.ADDON_NAME, f"Failed downloading subtitle from {result.display_name}", time=3000)

        else:
            control.log(f"Subtitle Service: Unrecognized action '{action}'", 'warning')

    except Exception as e:
        control.log(f"Subtitle Service: Unhandled error in action='{action}': {e}", 'error')
    finally:
        if handle is not None and int(handle) >= 0:
            xbmcplugin.endOfDirectory(int(handle))

    return emitted


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint called by Kodi CPythonInvoker."""
    args = sys.argv if argv is None else argv
    handle = -1
    if len(args) > 1:
        try:
            handle = int(args[1])
        except (ValueError, TypeError):
            handle = -1
    param_string = args[2] if len(args) > 2 else ''
    return handle_request(handle, param_string)


if __name__ == '__main__':
    main()
