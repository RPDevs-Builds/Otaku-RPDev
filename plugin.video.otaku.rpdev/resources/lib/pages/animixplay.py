# -*- coding: utf-8 -*-
"""
animixplay.py - Defunct Scraper Stub (Deprecated in v6.0.0)
AniMixPlay shut down permanently in December 2022.
This stub preserves interface compatibility while returning no sources immediately.
"""

from resources.lib.ui import control
from resources.lib.ui.BrowserBase import BrowserBase


class Sources(BrowserBase):
    _BASE_URL = 'https://animixplay.la/'

    def get_sources(self, mal_id, episode):
        control.log("AniMixPlay: Scraper is deprecated and defunct (domain shutdown). Returning 0 sources.", level='debug')
        return []
