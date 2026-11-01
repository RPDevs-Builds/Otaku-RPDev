"""subtitles.py - Subtitles Route Handlers for Otaku-RPDev
========================================================
Handles user-triggered manual subtitle searches and interactive selection.
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
    and presents an interactive selection dialog to the user.
    """
    control.log("Subtitles Route: Manual subtitle search triggered", 'info')
    meta = subtitles.get_meta_from_player()
    settings = subtitles.get_subtitles_settings()

    dialog = control.progressDialog
    dialog.create(control.ADDON_NAME, "Searching subtitles...")

    try:
        results = subtitles.search_subtitles(meta, settings)
    finally:
        dialog.close()

    if not results:
        control.notify(control.ADDON_NAME, "No subtitles found", time=3000)
        return

    subtitles.manual_select_dialog(results, meta, settings)
