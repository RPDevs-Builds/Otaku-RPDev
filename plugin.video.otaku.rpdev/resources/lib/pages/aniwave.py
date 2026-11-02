# -*- coding: utf-8 -*-
"""
aniwave.py - Defunct Scraper Stub (Deprecated in v6.0.0)
AniWave (formerly 9anime) shut down globally in August 2024.
This stub preserves interface compatibility while returning no sources immediately.
"""

from resources.lib.ui import control
from resources.lib.ui.BrowserBase import BrowserBase


class Sources(BrowserBase):
    _BASE_URL = 'https://aniwave.se/'

    def get_sources(self, mal_id, episode):
        control.log("AniWave: Scraper is deprecated and defunct (domain shutdown). Returning 0 sources.", level='debug')
        return []
