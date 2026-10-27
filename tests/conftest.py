"""
conftest.py - Centralized Kodi Mock Test Harness
=================================================
Mocks all Kodi C++ Python API modules (xbmc, xbmcaddon, xbmcgui, xbmcvfs, xbmcplugin)
before any add-on modules are imported. Compatible with both pytest and unittest.
Provides full in-memory fidelity for Player, Monitor, ListItem, VideoInfoTag,
WindowXMLDialog, and plugin directory listings.
"""

import os
import sys
import io
import time
import tempfile
import sqlite3
import random
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


# ── xbmc Models & Classes ──────────────────────────────────────────────────

class MockActor:
    def __init__(self, name='', role='', index=0, thumbnail=''):
        self.name = name
        self.role = role
        self.index = index
        self.thumbnail = thumbnail


class MockInfoTagVideo:
    def __init__(self):
        self._title = ''
        self._media_type = ''
        self._tvshow_title = ''
        self._plot = ''
        self._year = 0
        self._premiered = ''
        self._status = ''
        self._genres = []
        self._mpaa = ''
        self._rating = (0.0, 0)
        self._season = 0
        self._episode = 0
        self._first_aired = ''
        self._playcount = 0
        self._duration = 0
        self._production_code = ''
        self._studios = []
        self._cast = []
        self._countries = []
        self._original_title = ''
        self._trailer = ''
        self._unique_ids = {}
        self._imdb_number = ''
        self._resume_point = 0.0
        self._tagline = ''
        self._original_language = ''

    def setTitle(self, title): self._title = title
    def getTitle(self): return self._title
    def setMediaType(self, mtype): self._media_type = mtype
    def getMediaType(self): return self._media_type
    def setTvShowTitle(self, title): self._tvshow_title = title
    def getTvShowTitle(self): return self._tvshow_title
    def setPlot(self, plot): self._plot = plot
    def getPlot(self): return self._plot
    def setYear(self, year): self._year = int(year) if year else 0
    def getYear(self): return self._year
    def setPremiered(self, premiered): self._premiered = premiered
    def getPremiered(self): return self._premiered
    def setTvShowStatus(self, status): self._status = status
    def getTvShowStatus(self): return self._status
    def setGenres(self, genres): self._genres = genres if isinstance(genres, list) else [genres]
    def getGenres(self): return self._genres
    def setMpaa(self, mpaa): self._mpaa = mpaa
    def getMpaa(self): return self._mpaa
    def setRating(self, score, votes=0): self._rating = (float(score or 0), int(votes or 0))
    def getRating(self): return self._rating
    def setSeason(self, s): self._season = int(s) if s else 0
    def getSeason(self): return self._season
    def setEpisode(self, e): self._episode = int(e) if e else 0
    def getEpisode(self): return self._episode
    def setFirstAired(self, aired): self._first_aired = aired
    def getFirstAired(self): return self._first_aired
    def setPlaycount(self, count): self._playcount = int(count) if count else 0
    def getPlaycount(self): return self._playcount
    def setDuration(self, duration): self._duration = int(duration) if duration else 0
    def getDuration(self): return self._duration
    def setProductionCode(self, code): self._production_code = str(code) if code else ''
    def getProductionCode(self): return self._production_code
    def setStudios(self, studios): self._studios = studios if isinstance(studios, list) else [studios]
    def getStudios(self): return self._studios
    def setCast(self, cast): self._cast = cast if isinstance(cast, list) else [cast]
    def getCast(self): return self._cast
    def setCountries(self, countries): self._countries = countries if isinstance(countries, list) else [countries]
    def getCountries(self): return self._countries
    def setOriginalTitle(self, ot): self._original_title = ot
    def getOriginalTitle(self): return self._original_title
    def setTrailer(self, trailer): self._trailer = trailer
    def getTrailer(self): return self._trailer
    def setUniqueIDs(self, uids): self._unique_ids = dict(uids) if uids else {}
    def getUniqueIDs(self): return self._unique_ids
    def setIMDBNumber(self, imdb): self._imdb_number = str(imdb)
    def getIMDBNumber(self): return self._imdb_number
    def setResumePoint(self, point, total=1): self._resume_point = float(point)
    def getResumePoint(self): return self._resume_point
    def setTagLine(self, tagline): self._tagline = str(tagline or '')
    def getTagLine(self): return self._tagline
    def setOriginalLanguage(self, lang): self._original_language = str(lang or '')
    def getOriginalLanguage(self): return self._original_language
    def setHdrType(self, hdr_type): self._hdr_type = int(hdr_type) if str(hdr_type).isdigit() else 1
    def getHdrType(self): return getattr(self, '_hdr_type', 0)


class MockPlayer:
    def __init__(self, *args, **kwargs):
        self._playing = False
        self._playing_video = False
        self._playing_audio = False
        self._time = 0.0
        self._total_time = 0.0
        self._playing_file = ''
        self._vinfo = MockInfoTagVideo()
        self._subtitles = []
        self._subtitle_stream = 0
        self._audio_stream = 0
        self._available_audio = []
        self._available_subtitles = []

    def isPlaying(self): return self._playing
    def isPlayingVideo(self): return self._playing and self._playing_video
    def isPlayingAudio(self): return self._playing and self._playing_audio
    def getTime(self): return self._time
    def getTotalTime(self): return self._total_time
    def seekTime(self, t): self._time = max(0.0, float(t))
    def pause(self): pass
    def play(self, item='', listitem=None, windowed=False, startpos=-1):
        self._playing = True
        self._playing_video = True
        self._playing_file = item
    def stop(self):
        self._playing = False
        self._playing_video = False
        self._playing_audio = False
    def getPlayingFile(self): return self._playing_file
    def getVideoInfoTag(self): return self._vinfo
    def setSubtitleStream(self, idx): self._subtitle_stream = int(idx)
    def setAudioStream(self, idx): self._audio_stream = int(idx)
    def getAvailableSubtitleStreams(self): return list(self._available_subtitles)
    def getAvailableAudioStreams(self): return list(self._available_audio)
    def getSubtitles(self): return list(self._subtitles)
    def onPlayBackStarted(self): pass
    def onPlayBackEnded(self): pass
    def onPlayBackStopped(self): pass
    def onPlayBackError(self): pass
    def onAVStarted(self): pass
    def onAVChange(self): pass


class MockMonitor:
    def __init__(self):
        self._abort = False

    def waitForAbort(self, timeout=0):
        if timeout > 0:
            time.sleep(min(float(timeout), 0.02))
        return self._abort

    def abortRequested(self):
        return self._abort

    def requestAbort(self):
        self._abort = True

    def onSettingsChanged(self): pass
    def onCleanStarted(self): pass
    def onCleanFinished(self): pass
    def onScanStarted(self): pass
    def onScanFinished(self): pass


class MockPlayList:
    _shared_playlists = {}

    def __init__(self, playListType=1):
        self.playListType = playListType
        if playListType not in self._shared_playlists:
            self._shared_playlists[playListType] = {'items': [], 'pos': 0}
        self._data = self._shared_playlists[playListType]

    @property
    def _items(self):
        return self._data['items']

    @property
    def _pos(self):
        return self._data['pos']

    @_pos.setter
    def _pos(self, val):
        self._data['pos'] = val

    def add(self, url, listitem=None, index=-1):
        if index < 0 or index >= len(self._items):
            self._items.append((url, listitem))
        else:
            self._items.insert(index, (url, listitem))

    def clear(self):
        self._items.clear()
        self._pos = 0

    def size(self):
        return len(self._items)

    def getposition(self):
        return self._pos

    def __getitem__(self, index):
        return self._items[index]

    def __len__(self):
        return len(self._items)


class MockKeyboard:
    def __init__(self, default='', heading='', hidden=False):
        self._text = default
        self._heading = heading
        self._confirmed = True

    def doModal(self, timeout=0): pass
    def isConfirmed(self): return self._confirmed
    def getText(self): return self._text
    def setText(self, text): self._text = text


mock_xbmc = MagicMock()
mock_xbmc.LOGINFO = 1
mock_xbmc.LOGWARNING = 2
mock_xbmc.LOGERROR = 3
mock_xbmc.LOGDEBUG = 0
mock_xbmc.LOGNONE = -1
mock_xbmc.PLAYLIST_VIDEO = 1
mock_xbmc.Actor = MockActor
mock_xbmc.InfoTagVideo = MockInfoTagVideo
mock_xbmc.Player = MockPlayer
mock_xbmc.Monitor = MockMonitor
mock_xbmc.PlayList = MockPlayList
mock_xbmc.Keyboard = MockKeyboard
mock_xbmc.executeJSONRPC.side_effect = lambda q: '{"result": "ok"}'
mock_xbmc.executebuiltin = MagicMock()
mock_xbmc.getCondVisibility.side_effect = lambda c: False
mock_xbmc.getInfoLabel.side_effect = lambda lbl: ''
mock_xbmc.getRegion.side_effect = lambda r: 'en'
mock_xbmc.getSupportedMedia.side_effect = lambda m: 'video'
mock_xbmc.log = MagicMock()
mock_xbmc.sleep = MagicMock()


# ── xbmcgui Models & Classes ───────────────────────────────────────────────

class MockListItem:
    def __init__(self, label='', label2='', path='', offscreen=False):
        self._label = label
        self._label2 = label2
        self._path = path
        self._offscreen = offscreen
        self._art = {}
        self._props = {}
        self._info = {}
        self._cm = []
        self._vinfo = MockInfoTagVideo()
        self._selected = False

    def getLabel(self): return self._label
    def setLabel(self, label): self._label = str(label)
    def getLabel2(self): return self._label2
    def setLabel2(self, label2): self._label2 = str(label2)
    def getPath(self): return self._path
    def setPath(self, path): self._path = str(path)
    def setArt(self, art): self._art.update(art or {})
    def getArt(self, key=None):
        return self._art.get(key, '') if key else dict(self._art)
    def setProperty(self, k, v): self._props[str(k)] = str(v)
    def setProperties(self, props):
        if props:
            self._props.update({str(k): str(v) for k, v in props.items()})
    def getProperty(self, k): return self._props.get(str(k), '')
    def getVideoInfoTag(self): return self._vinfo
    def setInfo(self, type_, infoLabels):
        self._info.setdefault(type_, {}).update(infoLabels or {})
    def addContextMenuItems(self, items, replaceItems=False):
        if replaceItems:
            self._cm = list(items or [])
        else:
            self._cm.extend(items or [])
    def select(self, selected=True): self._selected = bool(selected)
    def isSelected(self): return self._selected


class MockDialog:
    def __init__(self):
        self.notifications = []
        self.ok_dialogs = []
        self.yesno_response = True
        self.select_response = 0
        self.contextmenu_response = 0
        self.browse_response = ''
        self.textviewer_contents = []

    def notification(self, heading, message, icon='', time=3000, sound=True):
        self.notifications.append({'heading': heading, 'message': message, 'icon': icon, 'time': time})

    def ok(self, heading, message):
        self.ok_dialogs.append({'heading': heading, 'message': message})
        return True

    def yesno(self, heading, message, nolabel='', yeslabel='', autoclose=0):
        return self.yesno_response

    def yesnocustom(self, heading, message, customlabel='', nolabel='', yeslabel='', autoclose=0, defaultbutton=0):
        return 0

    def select(self, heading, list_, autoclose=0, preselect=-1, useDetails=False):
        return self.select_response

    def multiselect(self, heading, list_, autoclose=0, preselect=None, useDetails=False):
        return preselect or []

    def contextmenu(self, list_):
        return self.contextmenu_response

    def browse(self, type_, heading, shares, mask='', useThumbs=False, treatAsFolder=False, defaultt='', enableMultiple=False):
        return self.browse_response

    def textviewer(self, heading, text):
        self.textviewer_contents.append({'heading': heading, 'text': text})


class MockDialogProgress:
    def __init__(self):
        self._heading = ''
        self._msg = ''
        self._pct = 0
        self._canceled = False
        self._closed = False

    def create(self, heading, message='', line2='', line3=''):
        self._heading = heading
        msg_parts = [p for p in (message, line2, line3) if p]
        self._msg = "\n".join(msg_parts)
        self._pct = 0
        self._canceled = False
        self._closed = False

    def update(self, percent, message='', line2='', line3=''):
        self._pct = percent
        msg_parts = [p for p in (message, line2, line3) if p]
        if msg_parts:
            self._msg = "\n".join(msg_parts)

    def iscanceled(self):
        return self._canceled

    def close(self):
        self._closed = True


class MockControlList:
    def __init__(self):
        self._items = []
        self._selected = 0
        self._visible = True
    def addItem(self, item): self._items.append(item)
    def addItems(self, items): self._items.extend(items)
    def reset(self): self._items.clear(); self._selected = 0
    def size(self): return len(self._items)
    def getListItem(self, idx): return self._items[idx] if 0 <= idx < len(self._items) else None
    def getSelectedPosition(self): return self._selected if self._items else -1
    def getSelectedItem(self): return self._items[self._selected] if 0 <= self._selected < len(self._items) else None
    def selectItem(self, idx): self._selected = idx
    def setVisible(self, v): self._visible = bool(v)


class MockControlProgress:
    def __init__(self):
        self._percent = 0.0
        self._visible = True
    def setPercent(self, pct): self._percent = float(pct)
    def getPercent(self): return self._percent
    def setVisible(self, v): self._visible = bool(v)


class MockControlButton:
    def __init__(self):
        self._label = ''
        self._enabled = True
        self._visible = True
    def setLabel(self, lbl): self._label = str(lbl)
    def getLabel(self): return self._label
    def setEnabled(self, e): self._enabled = bool(e)
    def setVisible(self, v): self._visible = bool(v)


_window_props = {}
mock_home_win = MagicMock()
mock_home_win.getProperty.side_effect = lambda k: _window_props.get(k, '')
mock_home_win.setProperty.side_effect = lambda k, v: _window_props.__setitem__(k, str(v))
mock_home_win.clearProperty.side_effect = lambda k: _window_props.pop(k, None)
mock_home_win.clearProperties.side_effect = lambda: _window_props.clear()


class MockWindowXMLDialog:
    def __init__(self, xml_file='', xml_path='', default_skin='', default_res=''):
        self._xml_file = xml_file
        self._xml_path = xml_path
        self._props = {}
        self._controls = {}
        self._focus_id = 1000

    def setProperty(self, k, v): self._props[str(k)] = str(v)
    def setProperties(self, props):
        if props:
            self._props.update({str(k): str(v) for k, v in props.items()})
    def getProperty(self, k): return self._props.get(str(k), '')
    def clearProperty(self, k): self._props.pop(str(k), None)
    def clearProperties(self): self._props.clear()
    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = MockControlList()
        return self._controls[control_id]
    def setFocusId(self, control_id): self._focus_id = int(control_id)
    def getFocusId(self): return self._focus_id
    def setFocus(self, control): pass
    def doModal(self): pass
    def close(self): pass
    def show(self): pass


class MockWindowDialog:
    def __init__(self, *args, **kwargs):
        self._props = {}
        self._controls = {}
        self._focus_id = 1000

    def setProperty(self, k, v): self._props[str(k)] = str(v)
    def setProperties(self, props):
        if props:
            self._props.update({str(k): str(v) for k, v in props.items()})
    def getProperty(self, k): return self._props.get(str(k), '')
    def clearProperty(self, k): self._props.pop(str(k), None)
    def clearProperties(self): self._props.clear()
    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = MockControlList()
        return self._controls[control_id]
    def setFocusId(self, control_id): self._focus_id = int(control_id)
    def getFocusId(self): return self._focus_id
    def setFocus(self, control): pass
    def doModal(self): pass
    def close(self): pass
    def show(self): pass


mock_xbmcgui = MagicMock()
mock_xbmcgui.ACTION_BACKSPACE = 110
mock_xbmcgui.ACTION_NAV_BACK = 9
mock_xbmcgui.ACTION_PREVIOUS_MENU = 10
mock_xbmcgui.ACTION_SELECT_ITEM = 7
mock_xbmcgui.ACTION_MOUSE_LEFT_CLICK = 100
mock_xbmcgui.ACTION_MOUSE_DOUBLE_CLICK = 101
mock_xbmcgui.ACTION_TOUCH_TAP = 401
mock_xbmcgui.DLG_YESNO_YES_BTN = 11
mock_xbmcgui.INPUT_ALPHANUM = 0
mock_xbmcgui.getCurrentWindowId.return_value = 10000

mock_xbmcgui.ListItem = MockListItem
mock_xbmcgui.Dialog = MockDialog
mock_xbmcgui.DialogProgress = MockDialogProgress
mock_xbmcgui.ControlList = MockControlList
mock_xbmcgui.ControlProgress = MockControlProgress
mock_xbmcgui.ControlButton = MockControlButton
mock_xbmcgui.Window.return_value = mock_home_win
mock_xbmcgui.WindowXMLDialog = MockWindowXMLDialog
mock_xbmcgui.WindowDialog = MockWindowDialog


# ── xbmcplugin Models & Registry ───────────────────────────────────────────

class MockPlugin:
    def __init__(self):
        self.directory_items = []
        self.resolved_urls = []
        self.end_of_directory_args = []
        self.content_type = ''
        self.sort_methods = []
        self.properties = {}
        self.SORT_METHOD_NONE = 0
        self.SORT_METHOD_LABEL = 1
        self.SORT_METHOD_LABEL_IGNORE_THE = 2
        self.SORT_METHOD_DATE = 3
        self.SORT_METHOD_YEAR = 17
        self.SORT_METHOD_VIDEO_RATING = 18
        self.SORT_METHOD_DATEADDED = 21
        self.SORT_METHOD_EPISODE = 24
        self.SORT_METHOD_PLAYCOUNT = 37

    def addDirectoryItem(self, handle, url, listitem, isFolder=False, totalItems=0):
        self.directory_items.append((handle, url, listitem, isFolder))
        return True

    def addDirectoryItems(self, handle, items, totalItems=0):
        for item in items:
            self.directory_items.append((handle, item[0], item[1], item[2]))
        return True

    def endOfDirectory(self, handle, succeeded=True, updateListing=False, cacheToDisc=True):
        self.end_of_directory_args.append((handle, succeeded, updateListing, cacheToDisc))
        return True

    def setResolvedUrl(self, handle, succeeded, listitem):
        self.resolved_urls.append((handle, succeeded, listitem))

    def setContent(self, handle, content):
        self.content_type = content

    def addSortMethod(self, handle, sortMethod, *args, **kwargs):
        self.sort_methods.append((handle, sortMethod))

    def setProperty(self, handle, key, value):
        self.properties[key] = value

    def reset(self):
        self.directory_items.clear()
        self.resolved_urls.clear()
        self.end_of_directory_args.clear()
        self.sort_methods.clear()
        self.properties.clear()


mock_xbmcplugin = MockPlugin()


# ── xbmcvfs Models & Handlers ─────────────────────────────────────────────

class MockVFSFile:
    def __init__(self, path, mode='r'):
        self.path = path
        self.mode = mode
        self._buf = io.BytesIO()
        real_p = mock_xbmcvfs.translatePath(path)
        if 'r' in mode and os.path.exists(real_p):
            with open(real_p, 'rb') as f:
                self._buf = io.BytesIO(f.read())

    def read(self, size=-1):
        res = self._buf.read(size)
        return res.decode('utf-8', errors='ignore') if 'b' not in self.mode else res

    def readBytes(self, size=-1):
        return self._buf.read(size)

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        return self._buf.write(data)

    def size(self):
        pos = self._buf.tell()
        self._buf.seek(0, io.SEEK_END)
        sz = self._buf.tell()
        self._buf.seek(pos)
        return sz

    def seek(self, offset, whence=0):
        return self._buf.seek(offset, whence)

    def close(self):
        pass


mock_xbmcvfs = MagicMock()
mock_xbmcvfs.File = MockVFSFile
mock_xbmcvfs.translatePath.side_effect = lambda p: p.replace(
    'special://profile/addon_data/plugin.video.otaku.rpdev', TEST_PROFILE_DIR
).replace(
    'special://home/addons/plugin.video.otaku.rpdev', ADDON_ROOT
)
mock_xbmcvfs.exists.side_effect = os.path.exists
mock_xbmcvfs.mkdirs.side_effect = lambda p: os.makedirs(p, exist_ok=True)
mock_xbmcvfs.listdir.side_effect = lambda p: (
    [d for d in os.listdir(mock_xbmcvfs.translatePath(p)) if os.path.isdir(os.path.join(mock_xbmcvfs.translatePath(p), d))],
    [f for f in os.listdir(mock_xbmcvfs.translatePath(p)) if os.path.isfile(os.path.join(mock_xbmcvfs.translatePath(p), f))]
) if os.path.exists(mock_xbmcvfs.translatePath(p)) else ([], [])


# ── xbmcaddon Models & Settings ───────────────────────────────────────────

_settings_store = {
    'menu.mainmenu.config': 'airing_calendar,airing_last_season,airing_this_season,airing_next_season,trending,popular,voted,favourites,top_100,genres,search,tools',
    'otaku.version': '5.5.1',
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
            'version': '5.5.1',
            'icon': '',
            'fanart': '',
            'path': ADDON_ROOT,
            'profile': TEST_PROFILE_DIR
        }.get(k, '')
        mock_settings = MagicMock()
        mock_settings.getString.side_effect = lambda k: _settings_store.get(k, '')
        mock_settings.setString.side_effect = lambda k, v: _settings_store.__setitem__(k, str(v))
        mock_settings.getBool.side_effect = lambda k: _settings_store.get(k, '').lower() == 'true'
        mock_settings.getInt.side_effect = lambda k: int(_settings_store.get(k, 0))
        mock_settings.getNumber.side_effect = lambda k: float(_settings_store.get(k, 0))

        def _get_str_list(k):
            val = _settings_store.get(k, '')
            if isinstance(val, list):
                return val
            return [x.strip() for x in val.split(',') if x.strip()] if val else []

        def _set_str_list(k, v):
            if isinstance(v, list):
                _settings_store[k] = ','.join(v)
            else:
                _settings_store[k] = str(v)

        mock_settings.getStringList.side_effect = _get_str_list
        mock_settings.setStringList.side_effect = _set_str_list
        mock_settings.getIntList.side_effect = lambda k: [int(x) for x in _get_str_list(k)]
        mock_settings.getBoolList.side_effect = lambda k: [x.lower() == 'true' for x in _get_str_list(k)]

        addon_mock.getLocalizedString.side_effect = lambda string_id: f"String_{string_id}"
        addon_mock.getSettings.return_value = mock_settings
        addon_mock.getSetting.side_effect = lambda k: _settings_store.get(k, '')
        addon_mock.getString.side_effect = lambda k: _settings_store.get(k, '')
        addon_mock.getStringList.side_effect = _get_str_list
        addon_mock.getBool.side_effect = lambda k: _settings_store.get(k, '').lower() == 'true'
        addon_mock.getInt.side_effect = lambda k: int(_settings_store.get(k, 0))
        addon_mock.setSetting.side_effect = lambda k, v: _settings_store.__setitem__(k, str(v))
        addon_mock.setString.side_effect = lambda k, v: _settings_store.__setitem__(k, str(v))
        addon_mock.setStringList.side_effect = _set_str_list
    return addon_mock

mock_xbmcaddon = MagicMock()
mock_xbmcaddon.Addon.side_effect = addon_side_effect

# Install mocks in sys.modules
sys.modules['xbmc'] = mock_xbmc
sys.modules['xbmcaddon'] = mock_xbmcaddon
sys.modules['xbmcgui'] = mock_xbmcgui
sys.modules['xbmcvfs'] = mock_xbmcvfs
sys.modules['xbmcplugin'] = mock_xbmcplugin

# Fallback mocks for external Kodi script modules (bs4, pyqrcode) when running in bare CI
try:
    import bs4
except ImportError:
    mock_bs4 = MagicMock()
    mock_bs4.BeautifulSoup = MagicMock
    mock_bs4.SoupStrainer = MagicMock
    sys.modules['bs4'] = mock_bs4

try:
    import pyqrcode
except ImportError:
    mock_pyqrcode = MagicMock()
    sys.modules['pyqrcode'] = mock_pyqrcode

# Module aliasing for test harness
this_mod = sys.modules[__name__]
sys.modules['conftest'] = this_mod
sys.modules['tests.conftest'] = this_mod
