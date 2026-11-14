# -*- coding: utf-8 -*-
"""
tests/kodi_profile.py - Dual-Version Kodi 21 (Omega) & Kodi 22 (Piers) Simulation Layer
=====================================================================================
Provides deterministic switchable Kodi 21 and Kodi 22 mock profiles for unit and
integration tests.

Capabilities:
1. KodiProfile('21' | '22'): Context manager, function decorator, and TestCase class decorator.
2. KodiProfileMixin: TestCase mixin with `kodi_profile_version = '21' | '22'`.
3. MockInfoTagVideoBase, MockInfoTagVideo21, MockInfoTagVideo22.
4. MockActor22 & MockListItem22: Enforces non-null type safety on SWIG constructors and setters.
5. JSON-RPC Simulation:
   - Kodi 21: Player.GetChapters returns {} / method not found (testing fallback chain); stream lists return ISO 639-2.
   - Kodi 22: Player.GetChapters returns native chapters; stream lists return BCP 47.
6. Strict Settings Mode (strict_settings=True): Validates CAddonSettings types against settings.xml.
7. Strict Skin Controls Mode (strict_skin_controls=True): Validates getControl(id) against skin XML.
8. reset_settings_to_defaults(include_test_fixtures=True): Restores canonical XML defaults.
"""

import os
import sys
import json
import functools
import threading
import unittest
import xml.etree.ElementTree as ET

import conftest


# ── Metadata Paths ─────────────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ROOT = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
SETTINGS_XML_PATH = os.path.join(ADDON_ROOT, 'resources', 'settings.xml')
SKINS_1080I_DIR = os.path.join(ADDON_ROOT, 'resources', 'skins', 'Default', '1080i')


# ── Shared Caches ──────────────────────────────────────────────────────────────
_SETTINGS_SCHEMA_CACHE = None
_SETTINGS_DEFAULTS_CACHE = None
_SKIN_XML_CACHE = {}
_PROFILE_LOCK = threading.RLock()


def load_settings_schema():
    """Parse plugin.video.otaku.rpdev/resources/settings.xml once and cache schema."""
    global _SETTINGS_SCHEMA_CACHE, _SETTINGS_DEFAULTS_CACHE
    if _SETTINGS_SCHEMA_CACHE is not None:
        return _SETTINGS_SCHEMA_CACHE, _SETTINGS_DEFAULTS_CACHE

    schema = {}
    defaults = {}
    if os.path.exists(SETTINGS_XML_PATH):
        try:
            tree = ET.parse(SETTINGS_XML_PATH)
            root = tree.getroot()
            for s in root.iter('setting'):
                sid = s.get('id')
                stype = s.get('type')
                dflt_el = s.find('default')
                dflt_attr = s.get('default')
                if sid:
                    schema[sid] = stype
                    if dflt_el is not None:
                        defaults[sid] = dflt_el.text or ''
                    elif dflt_attr is not None:
                        defaults[sid] = dflt_attr or ''
        except Exception:
            pass

    _SETTINGS_SCHEMA_CACHE = schema
    _SETTINGS_DEFAULTS_CACHE = defaults
    return schema, defaults


def parse_skin_xml(xml_file):
    """Parse control IDs and types from skin XML template in resources/skins/Default/1080i/."""
    if not xml_file:
        return {}
    basename = os.path.basename(xml_file)
    if basename in _SKIN_XML_CACHE:
        return _SKIN_XML_CACHE[basename]

    xml_path = os.path.join(SKINS_1080I_DIR, basename)
    if not os.path.exists(xml_path):
        xml_path = xml_file if os.path.exists(xml_file) else None

    controls = {}
    if xml_path and os.path.exists(xml_path):
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for c in root.iter('control'):
                cid = c.get('id')
                ctype = c.get('type') or 'list'
                if cid:
                    controls[str(cid)] = ctype
                    if str(cid).isdigit():
                        controls[int(cid)] = ctype
            for p in root.iter('param'):
                if p.get('name') == 'id':
                    val = p.get('value') or (p.text and p.text.strip())
                    if val:
                        controls[str(val)] = 'button'
                        if str(val).isdigit():
                            controls[int(val)] = 'button'
        except Exception:
            pass

    _SKIN_XML_CACHE[basename] = controls
    return controls


def reset_settings_to_defaults(include_test_fixtures=True):
    """Reset conftest._settings_store to XML defaults plus required test fixture tokens."""
    _, defaults = load_settings_schema()
    conftest._settings_store.clear()
    conftest._settings_store.update(defaults)
    if include_test_fixtures:
        conftest._settings_store.update({
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
            'smartplay.prescrape': 'true',
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
        })


_FIXTURE_SETTINGS = {
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
    'smartplay.prescrape': 'true',
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


def restore_fixture_settings():
    """Restore conftest._settings_store back to baseline test fixtures."""
    conftest._settings_store.clear()
    conftest._settings_store.update(_FIXTURE_SETTINGS)


# ── InfoTagVideo Model Hierarchy ───────────────────────────────────────────────

class MockInfoTagVideoBase:
    """Common VideoInfoTag API surface present in both Kodi 20/21 and Kodi 22."""
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

    def setTitle(self, title): self._title = str(title) if title is not None else ''
    def getTitle(self): return self._title
    def setMediaType(self, mtype): self._media_type = str(mtype) if mtype is not None else ''
    def getMediaType(self): return self._media_type
    def setTvShowTitle(self, title): self._tvshow_title = str(title) if title is not None else ''
    def getTvShowTitle(self): return self._tvshow_title
    def setPlot(self, plot): self._plot = str(plot) if plot is not None else ''
    def getPlot(self): return self._plot
    def setYear(self, year): self._year = int(year) if year else 0
    def getYear(self): return self._year
    def setPremiered(self, premiered): self._premiered = str(premiered) if premiered is not None else ''
    def getPremiered(self): return self._premiered
    def setTvShowStatus(self, status): self._status = str(status) if status is not None else ''
    def getTvShowStatus(self): return self._status
    def setGenres(self, genres):
        self._genres = genres if isinstance(genres, list) else ([genres] if genres else [])
    def getGenres(self): return list(self._genres)
    def setMpaa(self, mpaa): self._mpaa = str(mpaa) if mpaa is not None else ''
    def getMpaa(self): return self._mpaa
    def setRating(self, score, votes=0):
        self._rating = (float(score or 0), int(votes or 0))
    def getRating(self): return self._rating
    def setSeason(self, s): self._season = int(s) if s else 0
    def getSeason(self): return self._season
    def setEpisode(self, e): self._episode = int(e) if e else 0
    def getEpisode(self): return self._episode
    def setFirstAired(self, aired): self._first_aired = str(aired) if aired is not None else ''
    def getFirstAired(self): return self._first_aired
    def setPlaycount(self, count): self._playcount = int(count) if count else 0
    def getPlaycount(self): return self._playcount
    def setDuration(self, duration): self._duration = int(duration) if duration else 0
    def getDuration(self): return self._duration
    def setProductionCode(self, code): self._production_code = str(code) if code else ''
    def getProductionCode(self): return self._production_code
    def setStudios(self, studios):
        self._studios = studios if isinstance(studios, list) else ([studios] if studios else [])
    def getStudios(self): return list(self._studios)
    def setCast(self, cast):
        self._cast = cast if isinstance(cast, list) else ([cast] if cast else [])
    def getCast(self): return list(self._cast)
    def setCountries(self, countries):
        self._countries = countries if isinstance(countries, list) else ([countries] if countries else [])
    def getCountries(self): return list(self._countries)
    def setOriginalTitle(self, ot): self._original_title = str(ot) if ot is not None else ''
    def getOriginalTitle(self): return self._original_title
    def setTrailer(self, trailer): self._trailer = str(trailer) if trailer is not None else ''
    def getTrailer(self): return self._trailer
    def setUniqueIDs(self, uids): self._unique_ids = dict(uids) if uids else {}
    def getUniqueIDs(self): return dict(self._unique_ids)
    def setIMDBNumber(self, imdb): self._imdb_number = str(imdb) if imdb is not None else ''
    def getIMDBNumber(self): return self._imdb_number
    def setResumePoint(self, point, total=1): self._resume_point = float(point or 0.0)
    def getResumePoint(self): return self._resume_point


class MockInfoTagVideo21(MockInfoTagVideoBase):
    """
    Kodi 21 (Omega) InfoTagVideo C++ Simulation.
    Excludes setOriginalLanguage, setTagLine, setSeasonPlot, setAvailableFanart, setHdrType.
    Accessing these methods without an hasattr check will immediately raise AttributeError.
    """
    pass



class MockInfoTagVideo22(MockInfoTagVideoBase):
    """
    Kodi 22 (Piers) InfoTagVideo C++ Simulation.
    Exposes Kodi 22 typed setters and strictly enforces SWIG non-null contracts.
    """
    def __init__(self):
        super().__init__()
        self._tagline = ''
        self._original_language = ''
        self._hdr_type = 0
        self._season_plot = ''
        self._available_fanart = []

    # Kodi 22 exclusive methods
    def setTagLine(self, tagline):
        if tagline is None:
            raise TypeError("SWIG contract violation: InfoTagVideo.setTagLine requires non-null string")
        self._tagline = str(tagline)

    def getTagLine(self): return self._tagline

    def setOriginalLanguage(self, lang):
        if lang is None:
            raise TypeError("SWIG contract violation: InfoTagVideo.setOriginalLanguage requires non-null string")
        self._original_language = str(lang)

    def getOriginalLanguage(self): return self._original_language

    def setHdrType(self, hdr_type):
        if hdr_type is None:
            raise TypeError("SWIG contract violation: InfoTagVideo.setHdrType requires non-null argument")
        hdr_map = {'none': 0, 'hdr10': 1, 'hlg': 2, 'dolbyvision': 3, 'dv': 3, 'hdr10plus': 4, 'hdr': 1}
        self._hdr_type = hdr_map.get(str(hdr_type).lower(), int(hdr_type) if str(hdr_type).isdigit() else 1)

    def getHdrType(self): return self._hdr_type

    def setSeasonPlot(self, plot):
        if plot is None:
            raise TypeError("SWIG contract violation: InfoTagVideo.setSeasonPlot requires non-null string")
        self._season_plot = str(plot)

    def getSeasonPlot(self): return self._season_plot

    def setAvailableFanart(self, fanarts):
        if fanarts is None or (isinstance(fanarts, list) and any(f is None for f in fanarts)):
            raise TypeError("SWIG contract violation: InfoTagVideo.setAvailableFanart requires non-null list of strings")
        self._available_fanart = list(fanarts)

    def getAvailableFanart(self): return list(self._available_fanart)

    # Strict SWIG non-null assertions on standard setters
    def setTitle(self, title):
        if title is None: raise TypeError("SWIG contract violation: setTitle requires non-null string")
        super().setTitle(title)



    def setMediaType(self, mtype):
        if mtype is None: raise TypeError("SWIG contract violation: setMediaType requires non-null string")
        super().setMediaType(mtype)

    def setTvShowTitle(self, title):
        if title is None: raise TypeError("SWIG contract violation: setTvShowTitle requires non-null string")
        super().setTvShowTitle(title)

    def setPlot(self, plot):
        if plot is None: raise TypeError("SWIG contract violation: setPlot requires non-null string")
        super().setPlot(plot)

    def setYear(self, year):
        if year is None: raise TypeError("SWIG contract violation: setYear requires non-null int/str")
        super().setYear(year)

    def setPremiered(self, premiered):
        if premiered is None: raise TypeError("SWIG contract violation: setPremiered requires non-null string")
        super().setPremiered(premiered)

    def setTvShowStatus(self, status):
        if status is None: raise TypeError("SWIG contract violation: setTvShowStatus requires non-null string")
        super().setTvShowStatus(status)

    def setGenres(self, genres):
        if genres is None or (isinstance(genres, list) and any(g is None for g in genres)):
            raise TypeError("SWIG contract violation: setGenres requires non-null list of strings")
        super().setGenres(genres)

    def setMpaa(self, mpaa):
        if mpaa is None: raise TypeError("SWIG contract violation: setMpaa requires non-null string")
        super().setMpaa(mpaa)

    def setRating(self, score, votes=0):
        if score is None or votes is None:
            raise TypeError("SWIG contract violation: setRating requires non-null score and votes")
        super().setRating(score, votes)

    def setSeason(self, s):
        if s is None: raise TypeError("SWIG contract violation: setSeason requires non-null int")
        super().setSeason(s)

    def setEpisode(self, e):
        if e is None: raise TypeError("SWIG contract violation: setEpisode requires non-null int")
        super().setEpisode(e)

    def setFirstAired(self, aired):
        if aired is None: raise TypeError("SWIG contract violation: setFirstAired requires non-null string")
        super().setFirstAired(aired)

    def setPlaycount(self, count):
        if count is None: raise TypeError("SWIG contract violation: setPlaycount requires non-null int")
        super().setPlaycount(count)

    def setDuration(self, duration):
        if duration is None: raise TypeError("SWIG contract violation: setDuration requires non-null int")
        super().setDuration(duration)

    def setProductionCode(self, code):
        if code is None: raise TypeError("SWIG contract violation: setProductionCode requires non-null string")
        super().setProductionCode(code)

    def setStudios(self, studios):
        if studios is None or (isinstance(studios, list) and any(s is None for s in studios)):
            raise TypeError("SWIG contract violation: setStudios requires non-null list of strings")
        super().setStudios(studios)

    def setCast(self, cast):
        if cast is None or (isinstance(cast, list) and any(c is None for c in cast)):
            raise TypeError("SWIG contract violation: setCast requires non-null list of Actor objects")
        super().setCast(cast)

    def setCountries(self, countries):
        if countries is None or (isinstance(countries, list) and any(c is None for c in countries)):
            raise TypeError("SWIG contract violation: setCountries requires non-null list of strings")
        super().setCountries(countries)

    def setOriginalTitle(self, ot):
        if ot is None: raise TypeError("SWIG contract violation: setOriginalTitle requires non-null string")
        super().setOriginalTitle(ot)

    def setTrailer(self, trailer):
        if trailer is None: raise TypeError("SWIG contract violation: setTrailer requires non-null string")
        super().setTrailer(trailer)

    def setUniqueIDs(self, uids):
        if uids is None or any(v is None for v in uids.values()):
            raise TypeError("SWIG contract violation: setUniqueIDs requires non-null dictionary")
        super().setUniqueIDs(uids)

    def setIMDBNumber(self, imdb):
        if imdb is None: raise TypeError("SWIG contract violation: setIMDBNumber requires non-null string")
        super().setIMDBNumber(imdb)

    def setResumePoint(self, point, total=1):
        if point is None or total is None:
            raise TypeError("SWIG contract violation: setResumePoint requires non-null float")
        super().setResumePoint(point, total)


# ── Specialized Models for Kodi 21 & 22 ─────────────────────────────────────────

class MockActor22(conftest.MockActor):
    def __init__(self, name='', role='', index=0, thumbnail=''):
        if name is None:
            raise TypeError("SWIG contract violation: in method 'new_Actor', argument 1 of type 'std::string const &' (got None)")
        if role is None:
            raise TypeError("SWIG contract violation: in method 'new_Actor', argument 2 of type 'std::string const &' (got None)")
        if index is None or not isinstance(index, int):
            raise TypeError("SWIG contract violation: in method 'new_Actor', argument 3 of type 'int' (got None or non-int)")
        if thumbnail is None:
            raise TypeError("SWIG contract violation: in method 'new_Actor', argument 4 of type 'std::string const &' (got None)")
        super().__init__(str(name), str(role), int(index), str(thumbnail))


class MockListItem21(conftest.MockListItem):
    def __init__(self, label='', label2='', path='', offscreen=False):
        super().__init__(label=label, label2=label2, path=path, offscreen=offscreen)
        self._vinfo = MockInfoTagVideo21()


class MockListItem22(conftest.MockListItem):
    def __init__(self, label='', label2='', path='', offscreen=False):
        if label is None:
            raise TypeError("SWIG contract violation: ListItem label cannot be None")
        if label2 is None:
            raise TypeError("SWIG contract violation: ListItem label2 cannot be None")
        if path is None:
            raise TypeError("SWIG contract violation: ListItem path cannot be None")
        super().__init__(label=str(label), label2=str(label2), path=str(path), offscreen=offscreen)
        self._vinfo = MockInfoTagVideo22()

    def setProperty(self, k, v):
        if k is None or v is None:
            raise TypeError("SWIG contract violation: ListItem.setProperty key and value cannot be None")
        super().setProperty(k, v)

    def setPath(self, path):
        if path is None:
            raise TypeError("SWIG contract violation: ListItem.setPath path cannot be None")
        super().setPath(path)


class MockPlayer21(conftest.MockPlayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vinfo = MockInfoTagVideo21()
        self._available_audio = ['jpn', 'eng']
        self._available_subtitles = ['eng']


class MockPlayer22(conftest.MockPlayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vinfo = MockInfoTagVideo22()
        self._available_audio = ['ja', 'en']
        self._available_subtitles = ['en']


# ── Profile Management ─────────────────────────────────────────────────────────

class KodiProfile:
    """
    Context manager, function decorator, and unittest.TestCase class decorator
    for simulating switchable Kodi 21 (Omega) and Kodi 22 (Piers) C++ environments.
    """
    _profile_stack = []
    _active_profile = None

    def __init__(self, version, strict_settings=False, strict_skin_controls=False):
        ver_str = str(version).strip().replace('kodi', '').replace('v', '').split('.')[0]
        if ver_str not in ('21', '22'):
            raise ValueError(f"Invalid Kodi version '{version}': must be '21' or '22'")
        self.version = ver_str
        self.strict_settings = bool(strict_settings)
        self.strict_skin_controls = bool(strict_skin_controls)
        self._saved_state = None

    @classmethod
    def current(cls):
        """Return the active Kodi version string ('21' or '22'), or 'default' when inactive."""
        with _PROFILE_LOCK:
            return cls._active_profile.version if cls._active_profile else 'default'

    @classmethod
    def is_active(cls):
        """Return True if an explicit Kodi profile is currently active."""
        with _PROFILE_LOCK:
            return cls._active_profile is not None

    @classmethod
    def get_active(cls):
        """Return the active KodiProfile instance or None."""
        with _PROFILE_LOCK:
            return cls._active_profile

    @classmethod
    def is_kodi_21(cls):
        return cls.current() == '21'

    @classmethod
    def is_kodi_22(cls):
        return cls.current() == '22'

    @classmethod
    def is_strict_settings(cls):
        with _PROFILE_LOCK:
            return cls._active_profile.strict_settings if cls._active_profile else False

    @classmethod
    def is_strict_skin_controls(cls):
        with _PROFILE_LOCK:
            return cls._active_profile.strict_skin_controls if cls._active_profile else False

    def __enter__(self):
        with _PROFILE_LOCK:
            KodiProfile._profile_stack.append(KodiProfile._active_profile)
            KodiProfile._active_profile = self

            # Save previous state
            saved_control_ver = None
            if 'resources.lib.ui.control' in sys.modules:
                saved_control_ver = getattr(sys.modules['resources.lib.ui.control'], 'kodi_version', None)

            self._saved_state = {
                'InfoTagVideo': conftest.mock_xbmc.InfoTagVideo,
                'Actor': conftest.mock_xbmc.Actor,
                'ListItem': conftest.mock_xbmcgui.ListItem,
                'Player': conftest.mock_xbmc.Player,
                'kodi_version': saved_control_ver,
                'active_profile_in_conftest': getattr(conftest, '_current_kodi_profile', None),
            }

            # Inform conftest of active profile
            conftest._current_kodi_profile = self

            # Apply profile-specific mocks
            if self.version == '21':
                conftest.mock_xbmc.InfoTagVideo = MockInfoTagVideo21
                conftest.mock_xbmc.Actor = conftest.MockActor
                conftest.mock_xbmcgui.ListItem = MockListItem21
                conftest.mock_xbmc.Player = MockPlayer21
                if 'resources.lib.ui.control' in sys.modules:
                    sys.modules['resources.lib.ui.control'].kodi_version = 21.3
            else:  # Kodi 22
                conftest.mock_xbmc.InfoTagVideo = MockInfoTagVideo22
                conftest.mock_xbmc.Actor = MockActor22
                conftest.mock_xbmcgui.ListItem = MockListItem22
                conftest.mock_xbmc.Player = MockPlayer22
                if 'resources.lib.ui.control' in sys.modules:
                    sys.modules['resources.lib.ui.control'].kodi_version = 22.0

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        with _PROFILE_LOCK:
            if self._saved_state:
                conftest.mock_xbmc.InfoTagVideo = self._saved_state['InfoTagVideo']
                conftest.mock_xbmc.Actor = self._saved_state['Actor']
                conftest.mock_xbmcgui.ListItem = self._saved_state['ListItem']
                conftest.mock_xbmc.Player = self._saved_state['Player']
                if 'resources.lib.ui.control' in sys.modules and self._saved_state['kodi_version'] is not None:
                    sys.modules['resources.lib.ui.control'].kodi_version = self._saved_state['kodi_version']
                conftest._current_kodi_profile = self._saved_state['active_profile_in_conftest']

            KodiProfile._active_profile = KodiProfile._profile_stack.pop() if KodiProfile._profile_stack else None
            conftest._current_kodi_profile = KodiProfile._active_profile

    def __call__(self, target):
        if isinstance(target, type) and issubclass(target, unittest.TestCase):
            orig_setUp = getattr(target, 'setUp', lambda s: None)
            orig_tearDown = getattr(target, 'tearDown', lambda s: None)
            profile_obj = self

            def new_setUp(test_self):
                test_self._kodi_profile_class_ctx = KodiProfile(
                    profile_obj.version,
                    strict_settings=profile_obj.strict_settings,
                    strict_skin_controls=profile_obj.strict_skin_controls
                )
                test_self._kodi_profile_class_ctx.__enter__()
                orig_setUp(test_self)

            def new_tearDown(test_self):
                try:
                    orig_tearDown(test_self)
                finally:
                    if hasattr(test_self, '_kodi_profile_class_ctx'):
                        test_self._kodi_profile_class_ctx.__exit__(None, None, None)

            target.setUp = new_setUp
            target.tearDown = new_tearDown
            return target

        elif callable(target):
            profile_obj = self

            @functools.wraps(target)
            def wrapper(*args, **kwargs):
                with KodiProfile(
                    profile_obj.version,
                    strict_settings=profile_obj.strict_settings,
                    strict_skin_controls=profile_obj.strict_skin_controls
                ):
                    return target(*args, **kwargs)

            return wrapper
        return target


class KodiProfileMixin:
    """Class mixin for unittest.TestCase classes desiring dual Kodi profile simulation."""
    kodi_profile_version = '21'
    strict_settings = False
    strict_skin_controls = False

    def setUp(self):
        super().setUp()
        self._kodi_profile_mixin_ctx = KodiProfile(
            self.kodi_profile_version,
            strict_settings=getattr(self, 'strict_settings', False),
            strict_skin_controls=getattr(self, 'strict_skin_controls', False)
        )
        self._kodi_profile_mixin_ctx.__enter__()

    def tearDown(self):
        try:
            if hasattr(self, '_kodi_profile_mixin_ctx'):
                self._kodi_profile_mixin_ctx.__exit__(None, None, None)
        finally:
            super().tearDown()
