"""subtitles.py - Subtitles Route Handlers for Otaku-RPDev
========================================================
Handles user-triggered manual subtitle searches, interactive selection,
Kodi default subtitle service configuration, and settings deep-linking.
"""

# -*- coding: utf-8 -*-

from resources.lib.ui.router import Route, multi_route
from resources.lib.ui import control
from resources.lib import subtitles


@multi_route('search_subtitles', 'search_subtitles/*', 'subtitles/search', 'subtitles/search/*')
def handle_subtitles_search(payload, params):
    """
    Manual subtitle search handler.
    Searches enabled subtitle providers for the currently playing video
    and presents an interactive selection dialog with auto-identified
    indicators and custom manual search support.
    """
    control.log("Subtitles Route: Manual subtitle search triggered", 'info')
    meta = subtitles.get_meta_from_player()
    settings = subtitles.get_subtitles_settings()

    if not settings.get('subtitles.enabled', True):
        control.notify(control.ADDON_NAME, "Native Subtitles are disabled in Settings", time=3000)
        return

    dialog = control.progressDialog
    dialog.create(control.ADDON_NAME, "Searching subtitles...")

    try:
        results = subtitles.search_subtitles(meta, settings)
    finally:
        dialog.close()

    # Always open manual_select_dialog even when 0 automatic results returned,
    # so the user can select [Manual Search...] to enter a custom title/episode.
    subtitles.manual_select_dialog(results, meta, settings, allow_manual_search=True)


@Route('set_kodi_subtitle_service')
def handle_set_kodi_subtitle_service(payload, params):
    """Set Otaku RPDev Subtitles as Kodi's default TV show & movie subtitle service."""
    control.log("Subtitles Route: Setting Kodi default subtitle service", 'info')
    subtitles.set_as_kodi_default_subtitle_service()


@Route('open_subtitle_settings')
def handle_open_subtitle_settings(payload, params):
    """Open Settings - Otaku RPDev (invoked from service.subtitles.otaku.rpdev Configure button)."""
    control.log("Subtitles Route: Opening Otaku RPDev settings", 'info')
    control.xbmc.executebuiltin(f'Addon.OpenSettings({control.ADDON_ID})')
    return control.exit_code()


@Route('open_subtitle_service_settings')
def handle_open_subtitle_service_settings(payload, params):
    """Open companion service.subtitles.otaku.rpdev settings (Subtitle Service & Providers)."""
    sub_id = getattr(control, 'SUBTITLE_ADDON_ID', 'service.subtitles.otaku.rpdev')
    control.log(f"Subtitles Route: Opening {sub_id} settings", 'info')
    control.xbmc.executebuiltin(f'Addon.OpenSettings({sub_id})')
    return control.exit_code()
