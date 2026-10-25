"""
conftest.py - Centralized Kodi Mock Test Harness
=================================================
Mocks all Kodi C++ Python API modules (xbmc, xbmcaddon, xbmcgui, xbmcvfs, xbmcplugin)
before any add-on modules are imported. Compatible with both pytest and unittest.
"""

import os
import sys
import tempfile
import sqlite3
from unittest.mock import MagicMock

# 1. Ensure plugin.video.otaku.rpdev is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ROOT = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)

# 2. Setup temporary profile directory with test info.db
TEST_PROFILE_DIR = tempfile.mkdtemp(prefix='otaku_test_')
info_db_path = os.path.join(TEST_PROFILE_DIR, 'info.db')
with sqlite3.connect(info_db_path) as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS info (api_name TEXT PRIMARY KEY, client_id TEXT, client_secret TEXT, redirect_uri TEXT)')
    for svc in ('Simkl', 'AniDB', 'MyAnimeList', 'Kitsu', 'AniList', 'TMDB', 'TVDB', 'Fanart-TV', 'MDBList', 'AnimeSchedule', 'Real-Debrid', 'AllDebrid', 'TorBox'):
        conn.execute('INSERT OR REPLACE INTO info VALUES (?, ?, ?, ?)', (svc, 'test_id', 'test_secret', 'http://localhost'))
    conn.commit()

# 3. Setup Mock Modules if not already in sys.modules
mock_xbmc = MagicMock()
mock_xbmc.LOGINFO = 1
mock_xbmc.LOGWARNING = 2
mock_xbmc.LOGERROR = 3
mock_xbmc.LOGDEBUG = 0
mock_xbmc.LOGNONE = -1
mock_xbmc.Player = object
mock_xbmc.Monitor = object

_window_props = {}
mock_home_win = MagicMock()
mock_home_win.getProperty.side_effect = lambda k: _window_props.get(k, '')
mock_home_win.setProperty.side_effect = lambda k, v: _window_props.__setitem__(k, str(v))
mock_home_win.clearProperty.side_effect = lambda k: _window_props.pop(k, None)

class MockWindowXMLDialog:
    def __init__(self, *args, **kwargs):
        self._props = {}

    def setProperty(self, k, v):
        self._props[k] = v

    def getProperty(self, k):
        return self._props.get(k, '')

class MockWindowDialog:
    def __init__(self, *args, **kwargs):
        self._props = {}

    def setProperty(self, k, v):
        self._props[k] = v

    def getProperty(self, k):
        return self._props.get(k, '')

mock_xbmcgui = MagicMock()
mock_xbmcgui.Window.return_value = mock_home_win
mock_xbmcgui.WindowXMLDialog = MockWindowXMLDialog
mock_xbmcgui.WindowDialog = MockWindowDialog

mock_xbmcvfs = MagicMock()
mock_xbmcvfs.translatePath.side_effect = lambda p: p.replace('special://profile/addon_data/plugin.video.otaku.rpdev', TEST_PROFILE_DIR).replace('special://home/addons/plugin.video.otaku.rpdev', ADDON_ROOT)
mock_xbmcvfs.exists.side_effect = os.path.exists
mock_xbmcvfs.mkdirs.side_effect = lambda p: os.makedirs(p, exist_ok=True)

mock_xbmcplugin = MagicMock()

_settings_store = {
    'watchlist.update.enabled': 'true',
    'interface.watchlist.paging': 'true',
    'interface.perpage.watchlist': '2',
    'general.minResolution': '0',
    'general.maxResolution': '4',
    'general.fileFilter': '2',
    'general.timeout': '10',
    'general.autodownload.subtitles': 'false',
    'general.smartplay': 'true',
    'general.pre_scrape': 'true',
    'general.binge_mode': 'false',
    'general.kodi.cache': 'false',
    'ms_enable': 'false',
    'ms_url': 'http://127.0.0.1:4000',
    'provider.nyaa': 'true',
    'provider.animetosho': 'true',
    'provider.hianime': 'true',
    'realdebrid.enabled': 'true',
    'realdebrid.token': 'test_rd_token_123456789',
    'cache.torrents.ttl': '24'
}

def addon_side_effect(addon_id=None):
    addon_mock = MagicMock()
    if addon_id == 'xbmc.addon':
        addon_mock.getAddonInfo.side_effect = lambda k: '21.0.0' if k == 'version' else ''
    else:
        addon_mock.getAddonInfo.side_effect = lambda k: {
            'id': 'plugin.video.otaku.rpdev',
            'name': 'Otaku RPDev',
            'version': '5.4.7',
            'icon': '',
            'fanart': '',
            'path': ADDON_ROOT,
            'profile': TEST_PROFILE_DIR
        }.get(k, '')
        addon_mock.getSetting.side_effect = lambda k: _settings_store.get(k, '')
        addon_mock.getBool.side_effect = lambda k: _settings_store.get(k, '').lower() == 'true'
        addon_mock.getInt.side_effect = lambda k: int(_settings_store.get(k, 0))
        addon_mock.setSetting.side_effect = lambda k, v: _settings_store.__setitem__(k, str(v))
    return addon_mock

mock_xbmcaddon = MagicMock()
mock_xbmcaddon.Addon.side_effect = addon_side_effect

# Install mocks in sys.modules
sys.modules['xbmc'] = mock_xbmc
sys.modules['xbmcaddon'] = mock_xbmcaddon
sys.modules['xbmcgui'] = mock_xbmcgui
sys.modules['xbmcvfs'] = mock_xbmcvfs
sys.modules['xbmcplugin'] = mock_xbmcplugin
