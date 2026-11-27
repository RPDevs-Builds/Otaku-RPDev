# -*- coding: utf-8 -*-
"""
e2e_helpers.py — Hermetic Opaque-Box E2E Harness & Entrypoint Drivers
=====================================================================
Provides:
  - ``@tier(1..4)`` and ``@feature(*feature_ids)`` metadata decorators
  - ``E2EHermeticEnv`` context manager isolating ``special://`` URIs into
    per-test temporary directories, integrating ``KodiProfile``, allowing
    loopback-only sockets while blocking external traffic (including 10.13.0.16),
    capturing dialogs/executebuiltin calls, and ensuring zero repo leaks
  - Public opaque-box drivers: ``invoke_plugin_route``, ``invoke_context_action``,
    ``invoke_subtitle_service``, ``run_cli_script``
  - ``E2EMockServer`` (extending ``scripts.kodi_e2e_mock_server.LocalMockServer``)
"""

import functools
import importlib.util
import io
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from unittest.mock import MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_ROOT = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
SERVICE_ROOT = os.path.join(REPO_ROOT, 'service.otaku.rpdev')
SERVICE_LIB_ROOT = os.path.join(SERVICE_ROOT, 'resources', 'lib')
CONTEXT_ROOT = os.path.join(REPO_ROOT, 'context.otaku.rpdev')
SUBTITLE_ROOT = os.path.join(REPO_ROOT, 'service.subtitles.otaku.rpdev')
TESTS_ROOT = os.path.join(REPO_ROOT, 'tests')

for _p in (REPO_ROOT, ADDON_ROOT, SERVICE_LIB_ROOT, CONTEXT_ROOT, TESTS_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import conftest  # noqa: E402
from tests import kodi_profile  # noqa: E402
from scripts.kodi_e2e_mock_server import (  # noqa: E402
    LocalMockServer,
    MockServerHandler,
    ThreadingHTTPServer,
)

_CONTEXT_MODULE_CACHE = None
_SUBTITLE_MODULE_CACHE = None


# ── Metadata Decorators ────────────────────────────────────────────────────────

def tier(level: int):
    """Attach ``_e2e_tier`` (1..4) metadata to a test method or TestCase class."""
    lvl = int(level)
    if lvl not in (1, 2, 3, 4):
        raise ValueError(f"E2E tier must be 1..4, got {level!r}")

    def _decorator(obj):
        obj._e2e_tier = lvl
        return obj

    return _decorator


def feature(*feature_ids: str):
    """Attach ``_e2e_features`` tuple metadata to a test method or TestCase class."""
    normalized = tuple(str(fid).strip() for fid in feature_ids if str(fid).strip())
    if not normalized:
        raise ValueError("feature() requires at least one non-empty feature ID")

    def _decorator(obj):
        existing = tuple(getattr(obj, '_e2e_features', ()) or ())
        merged = tuple(dict.fromkeys(existing + normalized))
        obj._e2e_features = merged
        return obj

    return _decorator


# ── Repo Leak Hygiene ──────────────────────────────────────────────────────────

def find_repo_leaks():
    """Return sorted list of any ``special:*`` or ``MagicMock*`` entries in REPO_ROOT."""
    leaks = []
    try:
        for entry in sorted(os.listdir(REPO_ROOT)):
            if entry.startswith('special:') or entry.startswith('MagicMock'):
                leaks.append(entry)
    except OSError:
        pass
    return leaks


def assert_repo_clean_of_leaks():
    """Assert REPO_ROOT contains zero ``special:*`` or ``MagicMock*`` directories/files."""
    leaks = find_repo_leaks()
    if leaks:
        raise AssertionError(
            f"Repository root contains VFS/mock leak entries: {leaks} under {REPO_ROOT}"
        )


def assert_no_new_repo_leaks(baseline_leaks):
    """Assert no NEW ``special:*`` or ``MagicMock*`` entries appeared after baseline."""
    current = set(find_repo_leaks())
    new_leaks = sorted(current - set(baseline_leaks or ()))
    if new_leaks:
        raise AssertionError(
            f"Test created new VFS/mock leak entries in {REPO_ROOT}: {new_leaks}"
        )


# ── Dialog Capture & Loopback Guard ────────────────────────────────────────────

class DialogCapture(conftest.MockDialog):
    """Shared MockDialog capturing all notifications, ok_dialogs, and textviewers."""

    def __init__(self):
        super().__init__()
        self.yesno_calls = []
        self.select_calls = []
        self.input_calls = []
        self.contextmenu_calls = []

    def yesno(self, heading, message, nolabel='', yeslabel='', autoclose=0):
        self.yesno_calls.append({'heading': heading, 'message': message})
        return super().yesno(heading, message, nolabel=nolabel, yeslabel=yeslabel, autoclose=autoclose)

    def select(self, heading, list_, autoclose=0, preselect=-1, useDetails=False):
        self.select_calls.append({'heading': heading, 'list': list(list_ or [])})
        return super().select(heading, list_, autoclose=autoclose, preselect=preselect, useDetails=useDetails)

    def input(self, heading='', defaultt='', type=0, autoclose=0):
        self.input_calls.append({'heading': heading, 'default': defaultt})
        return super().input(heading=heading, defaultt=defaultt, type=type, autoclose=autoclose)

    def contextmenu(self, list_):
        self.contextmenu_calls.append({'list': list(list_ or [])})
        return super().contextmenu(list_)


def _is_loopback_address(address):
    """Return True iff socket address targets 127.0.0.0/8, ::1, or localhost."""
    if not isinstance(address, (list, tuple)) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    cleaned = host.strip().lower()
    if cleaned == 'localhost':
        return True
    if '%' in cleaned:
        cleaned = cleaned.split('%', 1)[0]
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


# ── Hermetic E2E Environment Context Manager ───────────────────────────────────

class E2EHermeticEnv:
    """
    Isolated per-test environment for Otaku-RPDev tri-addon E2E tests.
    - Translates all Kodi ``special://`` URIs into a unique ``TemporaryDirectory``
    - Configures real disk-backed ``xbmcvfs`` (``rename``, ``delete``, ``copy``, ``File``)
    - Rebinds ``control.*``, ``client.*``, and ``subtitles.download.*`` cached paths
    - Activates ``KodiProfile`` ('21' or '22') with strict settings & skin controls
    - Allows loopback ``127.0.0.1`` / ``::1`` sockets when ``allow_loopback=True``,
      while blocking all external hosts (including ``10.13.0.16``)
    - Snapshots and restores globals, SQLite pools, WindowXML instances, and settings
    """

    def __init__(
        self,
        kodi_version='22',
        strict_settings=True,
        strict_skin_controls=True,
        allow_loopback=True,
    ):
        self.kodi_version = str(kodi_version)
        self.strict_settings = bool(strict_settings)
        self.strict_skin_controls = bool(strict_skin_controls)
        self.allow_loopback = bool(allow_loopback)

        self._tmp_dir_obj = None
        self.root_dir = ''
        self.profile_dir = ''
        self.profile_root = ''
        self.temp_dir = ''
        self.userdata_dir = ''
        self.addon_data_root = ''
        self.home_dir = ''
        self.home_addons_dir = ''
        self.xbmc_dir = ''
        self.subtitle_temp_dir = ''

        self.dialog_capture = DialogCapture()
        self.executebuiltin_calls = []
        self._kodi_profile_ctx = None
        self._baseline_leaks = set()
        self._saved = {}
        self._saved_modules = {}

    def translate_path(self, path):
        if not isinstance(path, str):
            raise TypeError(f"xbmcvfs.translatePath expected str, got {type(path).__name__}")
        if not path.startswith('special://'):
            return path
        prefix_map = (
            ('special://profile/addon_data/plugin.video.otaku.rpdev', self.profile_dir),
            ('special://profile/addon_data', self.addon_data_root),
            ('special://profile', self.profile_root),
            ('special://userdata/addon_data/plugin.video.otaku.rpdev', self.profile_dir),
            ('special://userdata/addon_data', self.addon_data_root),
            ('special://userdata', self.userdata_dir),
            ('special://temp', self.temp_dir),
            ('special://home/addons/plugin.video.otaku.rpdev', ADDON_ROOT),
            ('special://home/addons/context.otaku.rpdev', CONTEXT_ROOT),
            ('special://home/addons/service.subtitles.otaku.rpdev', SUBTITLE_ROOT),
            ('special://home/addons', self.home_addons_dir),
            ('special://home', self.home_dir),
            ('special://xbmc', self.xbmc_dir),
        )
        for prefix, target in prefix_map:
            if path == prefix or path == prefix + '/':
                return target + (os.sep if path.endswith('/') else '')
            if path.startswith(prefix + '/'):
                rel = path[len(prefix) + 1:].lstrip('/')
                joined = os.path.join(target, rel)
                if path.endswith('/') and not joined.endswith(os.sep):
                    joined += os.sep
                return joined
        rel = path[len('special://'):].lstrip('/')
        return os.path.join(self.root_dir, 'special', rel)

    def _seed_sandbox_files(self):
        import sqlite3
        info_db_path = os.path.join(self.profile_dir, 'info.db')
        with sqlite3.connect(info_db_path) as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS info '
                '(api_name TEXT PRIMARY KEY, client_id TEXT, client_secret TEXT, redirect_uri TEXT)'
            )
            services = (
                'Simkl', 'AniDB', 'MyAnimeList', 'Kitsu', 'AniList',
                'TMDB', 'TVDB', 'Fanart-TV', 'MDBList', 'AnimeSchedule',
                'Real-Debrid', 'AllDebrid', 'TorBox',
            )
            for svc in services:
                conn.execute(
                    'INSERT OR REPLACE INTO info VALUES (?, ?, ?, ?)',
                    (svc, 'test_id', 'test_secret', 'http://localhost'),
                )
            conn.commit()
        cacert = os.path.join(self.xbmc_dir, 'system', 'certs', 'cacert.pem')
        os.makedirs(os.path.dirname(cacert), exist_ok=True)
        with open(cacert, 'w', encoding='utf-8') as cf:
            cf.write('')

    def _build_vfs_file_cls(self):
        env = self

        class _HermeticVFSFile:
            def __init__(self, path, mode='r'):
                self.path = path
                self.mode = mode or 'r'
                self._real_path = env.translate_path(path)
                self._buf = io.BytesIO()
                self._closed = False
                if ('r' in self.mode or 'a' in self.mode) and os.path.exists(self._real_path):
                    with open(self._real_path, 'rb') as f:
                        self._buf = io.BytesIO(f.read())
                    if 'a' in self.mode:
                        self._buf.seek(0, io.SEEK_END)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.close()

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
                if not self._closed and any(m in self.mode for m in ('w', 'a', '+')):
                    parent = os.path.dirname(os.path.abspath(self._real_path))
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(self._real_path, 'wb') as f:
                        f.write(self._buf.getvalue())
                self._closed = True

        return _HermeticVFSFile

    def _rebind_module_paths(self, translate_fn, vfs_exists_fn):
        self._saved_modules = {}

        if 'resources.lib.ui.control' in sys.modules:
            ctrl = sys.modules['resources.lib.ui.control']
            ctrl_attrs = (
                'dataPath', 'cacheFile', 'searchHistoryDB', 'malSyncDB', 'mappingDB',
                'maldubFile', 'downloads_json', 'completed_json', 'genre_json',
                'sort_options_json', 'watch_history_json', 'embeds_json',
                'animeschedule_calendar_json', 'mal_calendar_json', 'simkl_calendar_json',
                'kodi_userdata_path', 'kodi_advancedsettings_path', 'pathExists',
            )
            self._saved_modules['control'] = {a: getattr(ctrl, a) for a in ctrl_attrs if hasattr(ctrl, a)}
            ctrl.dataPath = self.profile_dir + os.sep
            ctrl.cacheFile = os.path.join(self.profile_dir, 'cache.db')
            ctrl.searchHistoryDB = os.path.join(self.profile_dir, 'search.db')
            ctrl.malSyncDB = os.path.join(self.profile_dir, 'malSync.db')
            ctrl.mappingDB = os.path.join(self.profile_dir, 'mappings.db')
            ctrl.maldubFile = os.path.join(self.profile_dir, 'mal_dub.json')
            ctrl.downloads_json = os.path.join(self.profile_dir, 'downloads.json')
            ctrl.completed_json = os.path.join(self.profile_dir, 'completed.json')
            ctrl.genre_json = os.path.join(self.profile_dir, 'genres.json')
            ctrl.sort_options_json = os.path.join(self.profile_dir, 'sort_options.json')
            ctrl.watch_history_json = os.path.join(self.profile_dir, 'watch_history.json')
            ctrl.embeds_json = os.path.join(self.profile_dir, 'embeds.json')
            ctrl.animeschedule_calendar_json = os.path.join(self.profile_dir, 'animeschedule_calendar.json')
            ctrl.mal_calendar_json = os.path.join(self.profile_dir, 'mal_calendar.json')
            ctrl.simkl_calendar_json = os.path.join(self.profile_dir, 'simkl_calendar.json')
            ctrl.kodi_userdata_path = self.userdata_dir + os.sep
            ctrl.kodi_advancedsettings_path = os.path.join(self.userdata_dir, 'advancedsettings.xml')
            ctrl.pathExists = vfs_exists_fn
            if hasattr(ctrl, 'clearSettingsCache'):
                ctrl.clearSettingsCache()
            if hasattr(ctrl, '_studio_logo_index_cache'):
                ctrl._studio_logo_index_cache.clear()
            if hasattr(ctrl, 'monitor') and hasattr(ctrl.monitor, 'cleanup'):
                ctrl.monitor.cleanup()

        if 'resources.lib.ui.client' in sys.modules:
            cl = sys.modules['resources.lib.ui.client']
            self._saved_modules['client'] = {
                'TRANSLATEPATH': getattr(cl, 'TRANSLATEPATH', None),
                'CERT_FILE': getattr(cl, 'CERT_FILE', None),
            }
            cl.TRANSLATEPATH = translate_fn
            cl.CERT_FILE = translate_fn('special://xbmc/system/certs/cacert.pem')

        if 'resources.lib.subtitles.download' in sys.modules:
            dl = sys.modules['resources.lib.subtitles.download']
            self._saved_modules['sub_dl'] = {'SUBTITLE_TEMP_DIR': getattr(dl, 'SUBTITLE_TEMP_DIR', None)}
            dl.SUBTITLE_TEMP_DIR = os.path.join(self.profile_dir, 'temp', 'subtitles')

        if 'resources.lib.ui.database' in sys.modules:
            db = sys.modules['resources.lib.ui.database']
            if hasattr(db, 'close_all_connections'):
                db.close_all_connections()
            if hasattr(db, '_tables_ready'):
                db._tables_ready.clear()

    def _restore_module_paths(self):
        if 'resources.lib.ui.database' in sys.modules:
            db = sys.modules['resources.lib.ui.database']
            if hasattr(db, 'close_all_connections'):
                db.close_all_connections()
            if hasattr(db, '_tables_ready'):
                db._tables_ready.clear()

        if 'control' in self._saved_modules and 'resources.lib.ui.control' in sys.modules:
            ctrl = sys.modules['resources.lib.ui.control']
            for k, v in self._saved_modules['control'].items():
                setattr(ctrl, k, v)
            if hasattr(ctrl, 'clearSettingsCache'):
                ctrl.clearSettingsCache()
            if hasattr(ctrl, '_studio_logo_index_cache'):
                ctrl._studio_logo_index_cache.clear()
            if hasattr(ctrl, 'monitor') and hasattr(ctrl.monitor, 'cleanup'):
                ctrl.monitor.cleanup()

        if 'client' in self._saved_modules and 'resources.lib.ui.client' in sys.modules:
            cl = sys.modules['resources.lib.ui.client']
            for k, v in self._saved_modules['client'].items():
                setattr(cl, k, v)

        if 'sub_dl' in self._saved_modules and 'resources.lib.subtitles.download' in sys.modules:
            dl = sys.modules['resources.lib.subtitles.download']
            for k, v in self._saved_modules['sub_dl'].items():
                setattr(dl, k, v)

    def __enter__(self):
        self._baseline_leaks = set(find_repo_leaks())
        self._tmp_dir_obj = tempfile.TemporaryDirectory(prefix='otaku_e2e_')
        self.root_dir = self._tmp_dir_obj.name
        self.profile_dir = os.path.join(self.root_dir, 'profile_otaku')
        self.profile_root = os.path.join(self.root_dir, 'profile')
        self.temp_dir = os.path.join(self.root_dir, 'temp')
        self.userdata_dir = os.path.join(self.root_dir, 'userdata')
        self.addon_data_root = os.path.join(self.root_dir, 'addon_data')
        self.home_dir = os.path.join(self.root_dir, 'home')
        self.home_addons_dir = os.path.join(self.home_dir, 'addons')
        self.xbmc_dir = os.path.join(self.root_dir, 'xbmc')
        self.subtitle_temp_dir = os.path.join(
            self.addon_data_root, 'service.subtitles.otaku.rpdev', 'temp'
        )
        for d in (
            self.profile_dir,
            self.profile_root,
            self.temp_dir,
            self.userdata_dir,
            self.addon_data_root,
            self.home_dir,
            self.home_addons_dir,
            self.xbmc_dir,
            self.subtitle_temp_dir,
            os.path.join(self.addon_data_root, 'context.otaku.rpdev'),
        ):
            os.makedirs(d, exist_ok=True)

        self._seed_sandbox_files()

        # Snapshot conftest globals & sockets
        self._saved = {
            'settings_store': dict(conftest._settings_store),
            'window_props': dict(conftest._window_props),
            'TEST_PROFILE_DIR': conftest.TEST_PROFILE_DIR,
            'TEST_TEMP_DIR': conftest.TEST_TEMP_DIR,
            'TEST_USERDATA_DIR': conftest.TEST_USERDATA_DIR,
            'TEST_ADDON_DATA_DIR': conftest.TEST_ADDON_DATA_DIR,
            'TEST_PROFILE_ROOT': conftest.TEST_PROFILE_ROOT,
            'TEST_HOME_DIR': conftest.TEST_HOME_DIR,
            'TEST_XBMC_DIR': conftest.TEST_XBMC_DIR,
            'vfs_File': conftest.mock_xbmcvfs.File,
            'vfs_translatePath_se': conftest.mock_xbmcvfs.translatePath.side_effect,
            'vfs_exists_se': conftest.mock_xbmcvfs.exists.side_effect,
            'vfs_mkdirs_se': conftest.mock_xbmcvfs.mkdirs.side_effect,
            'vfs_delete_se': conftest.mock_xbmcvfs.delete.side_effect,
            'vfs_rename_se': conftest.mock_xbmcvfs.rename.side_effect,
            'vfs_copy_se': conftest.mock_xbmcvfs.copy.side_effect,
            'vfs_listdir_se': conftest.mock_xbmcvfs.listdir.side_effect,
            'Dialog': conftest.mock_xbmcgui.Dialog,
            'executebuiltin_se': conftest.mock_xbmc.executebuiltin.side_effect,
            'socket_connect': socket.socket.connect,
            'socket_connect_ex': socket.socket.connect_ex,
        }

        conftest.TEST_PROFILE_DIR = self.profile_dir
        conftest.TEST_TEMP_DIR = self.temp_dir
        conftest.TEST_USERDATA_DIR = self.userdata_dir
        conftest.TEST_ADDON_DATA_DIR = self.addon_data_root
        conftest.TEST_PROFILE_ROOT = self.profile_root
        conftest.TEST_HOME_DIR = self.home_dir
        conftest.TEST_XBMC_DIR = self.xbmc_dir

        kodi_profile.reset_settings_to_defaults(include_test_fixtures=True)
        conftest._window_props.clear()
        conftest.mock_xbmcplugin.reset()

        # Patch xbmcvfs completely
        translate_fn = self.translate_path

        def _vfs_exists(p):
            return os.path.exists(translate_fn(p))

        def _vfs_mkdirs(p):
            os.makedirs(translate_fn(p), exist_ok=True)
            return True

        def _vfs_delete(p):
            real_p = translate_fn(p)
            if os.path.exists(real_p):
                os.remove(real_p)
                return True
            return False

        def _vfs_rename(src, dst):
            src_real = translate_fn(src)
            dst_real = translate_fn(dst)
            if not os.path.exists(src_real):
                return False
            parent = os.path.dirname(os.path.abspath(dst_real))
            if parent:
                os.makedirs(parent, exist_ok=True)
            os.replace(src_real, dst_real)
            return True

        def _vfs_copy(src, dst):
            src_real = translate_fn(src)
            dst_real = translate_fn(dst)
            if not os.path.exists(src_real):
                return False
            parent = os.path.dirname(os.path.abspath(dst_real))
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.copy2(src_real, dst_real)
            return True

        def _vfs_listdir(p):
            real_p = translate_fn(p)
            if not os.path.exists(real_p):
                return ([], [])
            dirs = [d for d in os.listdir(real_p) if os.path.isdir(os.path.join(real_p, d))]
            files = [f for f in os.listdir(real_p) if os.path.isfile(os.path.join(real_p, f))]
            return (dirs, files)

        conftest.mock_xbmcvfs.File = self._build_vfs_file_cls()
        conftest.mock_xbmcvfs.translatePath.side_effect = translate_fn
        conftest.mock_xbmcvfs.exists.side_effect = _vfs_exists
        conftest.mock_xbmcvfs.mkdirs.side_effect = _vfs_mkdirs
        conftest.mock_xbmcvfs.delete.side_effect = _vfs_delete
        conftest.mock_xbmcvfs.rename.side_effect = _vfs_rename
        conftest.mock_xbmcvfs.copy.side_effect = _vfs_copy
        conftest.mock_xbmcvfs.listdir.side_effect = _vfs_listdir

        # Patch Dialog & executebuiltin captures
        self.dialog_capture = DialogCapture()
        conftest.mock_xbmcgui.Dialog = lambda: self.dialog_capture
        self.executebuiltin_calls = []

        def _exec_builtin(cmd, *args, **kwargs):
            self.executebuiltin_calls.append(str(cmd))
            return None

        conftest.mock_xbmc.executebuiltin.reset_mock()
        conftest.mock_xbmc.executebuiltin.side_effect = _exec_builtin

        # Loopback-only network guard (non-loopback including 10.13.0.16 always blocked)
        allow_loopback = self.allow_loopback
        real_connect = conftest._real_socket_connect
        real_connect_ex = conftest._real_socket_connect_ex

        def _e2e_socket_connect(sock_self, address):
            if allow_loopback and _is_loopback_address(address):
                return real_connect(sock_self, address)
            host = address[0] if isinstance(address, (list, tuple)) and address else str(address)
            port = address[1] if isinstance(address, (list, tuple)) and len(address) > 1 else '?'
            try:
                sock_self.close()
            except Exception:
                pass
            raise ConnectionRefusedError(
                f"E2E hermetic guard: non-loopback network connection blocked to {host}:{port}"
            )

        def _e2e_socket_connect_ex(sock_self, address):
            if allow_loopback and _is_loopback_address(address):
                return real_connect_ex(sock_self, address)
            return _e2e_socket_connect(sock_self, address)

        socket.socket.connect = _e2e_socket_connect
        socket.socket.connect_ex = _e2e_socket_connect_ex

        # Rebind paths on already-imported addon modules
        self._rebind_module_paths(translate_fn, _vfs_exists)

        # Enter KodiProfile
        self._kodi_profile_ctx = kodi_profile.KodiProfile(
            self.kodi_version,
            strict_settings=self.strict_settings,
            strict_skin_controls=self.strict_skin_controls,
        )
        self._kodi_profile_ctx.__enter__()
        if not hasattr(kodi_profile.MockInfoTagVideoBase, 'getTVShowTitle'):
            self._saved['added_getTVShowTitle'] = True
            kodi_profile.MockInfoTagVideoBase.getTVShowTitle = kodi_profile.MockInfoTagVideoBase.getTvShowTitle
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            # Close any lingering BaseWindow instances
            if 'resources.lib.windows.base_window' in sys.modules:
                bw = sys.modules['resources.lib.windows.base_window']
                active = getattr(bw.BaseWindow, '_active_windows', None)
                if active is not None:
                    for win in list(active):
                        try:
                            win.close()
                        except Exception:
                            pass
                    active.clear()
            # Clear Kodi video playlist
            try:
                conftest.mock_xbmc.PlayList(1).clear()
            except Exception:
                pass
            # Restore module paths and close DB connections
            self._restore_module_paths()
        finally:
            if self._kodi_profile_ctx is not None:
                self._kodi_profile_ctx.__exit__(exc_type, exc_val, exc_tb)
                self._kodi_profile_ctx = None

            if self._saved:
                if self._saved.get('added_getTVShowTitle') and hasattr(kodi_profile.MockInfoTagVideoBase, 'getTVShowTitle'):
                    delattr(kodi_profile.MockInfoTagVideoBase, 'getTVShowTitle')
                socket.socket.connect = self._saved['socket_connect']
                socket.socket.connect_ex = self._saved['socket_connect_ex']
                conftest.mock_xbmcgui.Dialog = self._saved['Dialog']
                conftest.mock_xbmc.executebuiltin.side_effect = self._saved['executebuiltin_se']

                conftest.mock_xbmcvfs.File = self._saved['vfs_File']
                conftest.mock_xbmcvfs.translatePath.side_effect = self._saved['vfs_translatePath_se']
                conftest.mock_xbmcvfs.exists.side_effect = self._saved['vfs_exists_se']
                conftest.mock_xbmcvfs.mkdirs.side_effect = self._saved['vfs_mkdirs_se']
                conftest.mock_xbmcvfs.delete.side_effect = self._saved['vfs_delete_se']
                conftest.mock_xbmcvfs.rename.side_effect = self._saved['vfs_rename_se']
                conftest.mock_xbmcvfs.copy.side_effect = self._saved['vfs_copy_se']
                conftest.mock_xbmcvfs.listdir.side_effect = self._saved['vfs_listdir_se']

                conftest.TEST_PROFILE_DIR = self._saved['TEST_PROFILE_DIR']
                conftest.TEST_TEMP_DIR = self._saved['TEST_TEMP_DIR']
                conftest.TEST_USERDATA_DIR = self._saved['TEST_USERDATA_DIR']
                conftest.TEST_ADDON_DATA_DIR = self._saved['TEST_ADDON_DATA_DIR']
                conftest.TEST_PROFILE_ROOT = self._saved['TEST_PROFILE_ROOT']
                conftest.TEST_HOME_DIR = self._saved['TEST_HOME_DIR']
                conftest.TEST_XBMC_DIR = self._saved['TEST_XBMC_DIR']

                conftest._settings_store.clear()
                conftest._settings_store.update(self._saved['settings_store'])
                conftest._window_props.clear()
                conftest._window_props.update(self._saved['window_props'])
                conftest.mock_xbmcplugin.reset()

            if self._tmp_dir_obj is not None:
                self._tmp_dir_obj.cleanup()
                self._tmp_dir_obj = None

        if exc_type is None:
            assert_no_new_repo_leaks(self._baseline_leaks)


# ── Custom Loopback E2E Mock Server ────────────────────────────────────────────

class _E2EMockHandler(MockServerHandler):
    """Extends MockServerHandler to dispatch dynamic per-test route hooks first."""

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        custom = getattr(self.server, 'custom_handler', None)
        if custom is not None:
            handled = custom(self, 'POST', parsed.path, parsed, self.headers, raw_body)
            if handled:
                return
        # Re-feed raw_body only when delegating to parent /v1
        if parsed.path == '/v1':
            self.rfile = io.BytesIO(raw_body)
            self.headers['Content-Length'] = str(len(raw_body))
        return super().do_POST()

    def _handle_get_or_head(self, is_head=False):
        parsed = urllib.parse.urlparse(self.path)
        method = 'HEAD' if is_head else 'GET'
        custom = getattr(self.server, 'custom_handler', None)
        if custom is not None:
            handled = custom(self, method, parsed.path, parsed, self.headers, b"")
            if handled:
                return
        return super()._handle_get_or_head(is_head=is_head)


class E2EMockServer(LocalMockServer):
    """
    Loopback HTTP mock daemon built on ``LocalMockServer`` supporting custom
    per-test dynamic routes, counters, custom headers (e.g. ``X-Seek-Offset``),
    and error status simulation alongside default ``LocalMockServer`` routes.
    """

    def __init__(self, handler=None, host="127.0.0.1", port=0):
        super().__init__(host=host, port=port)
        self._custom_handler = handler
        self._routes = {}
        self.requests = []

    def add_route(self, path, callback):
        """Register ``callback(handler, method, path, parsed, headers, body) -> bool``."""
        self._routes[path] = callback

    def _dispatch(self, req_handler, method, path, parsed, headers, body):
        self.requests.append({'method': method, 'path': path, 'query': parsed.query})
        if self._custom_handler is not None:
            if self._custom_handler(req_handler, method, path, parsed, headers, body):
                return True
        if path in self._routes:
            return bool(self._routes[path](req_handler, method, path, parsed, headers, body))
        return False

    def start(self):
        self.server = ThreadingHTTPServer((self.host, self.requested_port), _E2EMockHandler)
        self.server.custom_handler = self._dispatch
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        for _ in range(50):
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://{self.host}:{self.port}/v1", timeout=1.0) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                import time
                time.sleep(0.05)
        return self


def send_http_response(req_handler, status=200, body=b'', content_type='text/plain; charset=utf-8', extra_headers=None, is_head=False):
    """Helper for custom E2EMockServer route callbacks."""
    if isinstance(body, str):
        body = body.encode('utf-8')
    req_handler.send_response(int(status))
    req_handler._send_cors_headers()
    req_handler.send_header('Content-Type', content_type)
    req_handler.send_header('Content-Length', str(len(body)))
    if extra_headers:
        for k, v in extra_headers.items():
            req_handler.send_header(k, str(v))
    req_handler.end_headers()
    if not is_head and body:
        req_handler.wfile.write(body)


# ── Public Opaque-Box Entrypoint Drivers ───────────────────────────────────────

def _load_isolated_module(cache_name, file_path):
    spec = importlib.util.spec_from_file_location(cache_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[cache_name] = mod
    spec.loader.exec_module(mod)
    return mod


def invoke_plugin_route(route_path: str, params=None, handle: int = 1) -> dict:
    """
    Invoke ``plugin.video.otaku.rpdev/default.py`` via ``sys.argv`` just like Kodi's
    CPythonInvoker and return captured directory items, resolved URLs, dialogs,
    and ``xbmc.executebuiltin`` commands.
    """
    clean_route = str(route_path or '').lstrip('/')
    plugin_uri = f"plugin://plugin.video.otaku.rpdev/{clean_route}" if clean_route else "plugin://plugin.video.otaku.rpdev/"
    query_str = ('?' + urllib.parse.urlencode(params)) if params else ''

    saved_argv = list(sys.argv)
    conftest.mock_xbmcplugin.reset()

    from resources.lib.ui import control
    control._directory_ended = False
    if 'resources.lib.Main' in sys.modules:
        sys.modules['resources.lib.Main'].plugin_url = control.get_plugin_url(plugin_uri)

    dlg = conftest.mock_xbmcgui.Dialog()
    notif_start = len(getattr(dlg, 'notifications', []))
    ok_start = len(getattr(dlg, 'ok_dialogs', []))
    tv_start = len(getattr(dlg, 'textviewer_contents', []))

    builtin_calls = []
    prev_builtin_se = conftest.mock_xbmc.executebuiltin.side_effect

    def _capture_builtin(cmd, *args, **kwargs):
        builtin_calls.append(str(cmd))
        if prev_builtin_se is not None:
            return prev_builtin_se(cmd, *args, **kwargs)
        return None

    conftest.mock_xbmc.executebuiltin.side_effect = _capture_builtin
    default_py = os.path.join(ADDON_ROOT, 'default.py')
    try:
        sys.argv = [plugin_uri, str(int(handle)), query_str]
        with open(default_py, 'r', encoding='utf-8') as df:
            code = compile(df.read(), default_py, 'exec')
        exec(code, {'__name__': '__main__', '__file__': default_py})
    finally:
        sys.argv = saved_argv
        conftest.mock_xbmc.executebuiltin.side_effect = prev_builtin_se

    return {
        'directory_items': list(conftest.mock_xbmcplugin.directory_items),
        'resolved_urls': list(conftest.mock_xbmcplugin.resolved_urls),
        'end_of_directory': list(conftest.mock_xbmcplugin.end_of_directory_args),
        'content_type': conftest.mock_xbmcplugin.content_type,
        'sort_methods': list(conftest.mock_xbmcplugin.sort_methods),
        'properties': dict(conftest.mock_xbmcplugin.properties),
        'notifications': list(getattr(dlg, 'notifications', [])[notif_start:]),
        'ok_dialogs': list(getattr(dlg, 'ok_dialogs', [])[ok_start:]),
        'textviewer_contents': list(getattr(dlg, 'textviewer_contents', [])[tv_start:]),
        'executebuiltin_calls': builtin_calls,
    }


def invoke_context_action(action: str, listitem) -> list:
    """
    Invoke ``context.otaku.rpdev/default.py:main()`` with ``sys.argv`` and
    ``sys.listitem`` and return captured ``xbmc.executebuiltin`` command strings.
    """
    global _CONTEXT_MODULE_CACHE
    if _CONTEXT_MODULE_CACHE is None:
        _CONTEXT_MODULE_CACHE = _load_isolated_module(
            'context_default',
            os.path.join(CONTEXT_ROOT, 'default.py'),
        )

    saved_argv = list(sys.argv)
    had_listitem = hasattr(sys, 'listitem')
    saved_listitem = getattr(sys, 'listitem', None)
    prev_builtin_se = conftest.mock_xbmc.executebuiltin.side_effect
    captured = []

    def _capture_builtin(cmd, *args, **kwargs):
        captured.append(str(cmd))
        if prev_builtin_se is not None:
            return prev_builtin_se(cmd, *args, **kwargs)
        return None

    conftest.mock_xbmc.executebuiltin.side_effect = _capture_builtin
    try:
        sys.argv = ['default.py', str(action)]
        sys.listitem = listitem
        _CONTEXT_MODULE_CACHE.main()
    finally:
        sys.argv = saved_argv
        if had_listitem:
            sys.listitem = saved_listitem
        elif hasattr(sys, 'listitem'):
            delattr(sys, 'listitem')
        conftest.mock_xbmc.executebuiltin.side_effect = prev_builtin_se

    return captured


def invoke_subtitle_service(action: str, params=None, handle: int = 1) -> dict:
    """
    Invoke ``service.subtitles.otaku.rpdev/service.py:handle_request`` and return
    emitted item count, directory items, endOfDirectory calls, and dialogs.
    """
    global _SUBTITLE_MODULE_CACHE
    if _SUBTITLE_MODULE_CACHE is None:
        _SUBTITLE_MODULE_CACHE = _load_isolated_module(
            'subtitle_service_main',
            os.path.join(SUBTITLE_ROOT, 'service.py'),
        )

    conftest.mock_xbmcplugin.reset()
    dlg = conftest.mock_xbmcgui.Dialog()
    notif_start = len(getattr(dlg, 'notifications', []))
    ok_start = len(getattr(dlg, 'ok_dialogs', []))

    q_dict = {'action': str(action)}
    if params:
        q_dict.update(params)
    param_string = '?' + urllib.parse.urlencode(q_dict)

    emitted = _SUBTITLE_MODULE_CACHE.handle_request(int(handle), param_string)
    return {
        'emitted': emitted,
        'directory_items': list(conftest.mock_xbmcplugin.directory_items),
        'end_of_directory': list(conftest.mock_xbmcplugin.end_of_directory_args),
        'notifications': list(getattr(dlg, 'notifications', [])[notif_start:]),
        'ok_dialogs': list(getattr(dlg, 'ok_dialogs', [])[ok_start:]),
    }


def run_cli_script(script_rel_path: str, args=None, timeout: int = 60, env_overrides=None):
    """Execute a repository CLI script via subprocess in REPO_ROOT."""
    script_abs = os.path.join(REPO_ROOT, script_rel_path)
    cmd = [sys.executable, script_abs] + list(args or [])
    env = os.environ.copy()
    if env_overrides:
        env.update({str(k): str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
