# -*- coding: utf-8 -*-
"""
test_subtitle_settings_split.py — Unit & Contract Tests for service.subtitles.otaku.rpdev Settings Split (v1.1.0)
==================================================================================================================
Covers all 6 implementation guardrails:
1. On-disk v1.1.0+ schema readiness check in migrate_subtitle_settings() (v1.0.3 stub defers cleanly without marker).
2. Pre-prune raw-XML migration (Kodi v2 text + legacy v1 value="...", idempotency, fresh install, malformed XML).
3. Lazy migration fallback & defensive service.otaku.rpdev/resources/lib sys.path bridge in service.py & subtitles/__init__.py.
4. 3-way control._settings_target routing under KodiProfile('22', strict_settings=True) & resilient _SettingsProxy fallback.
5. Cross-addon cache invalidation via otaku.subtitle_settings_epoch, os.stat instant-sync, and daemon.Monitor watcher.
6. Tri-profile settings_manager (migration marker exclusion, subtitles backup scope, Jimaku redaction/reconciliation,
   category resets, wipe_addon_data preserving C-30 temp/), and shortcut routes / Tools menu parity.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
for _p in (_REPO_ROOT, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import conftest  # noqa: F401
from tests.kodi_profile import KodiProfile
from resources.lib.ui import control, settings_manager
from resources.lib import subtitles as sub_pkg
from resources.lib.routes import subtitles as sub_routes
from resources.lib import Main
from otaku_service import migration, daemon


class _InMemoryKodiSettings:
    """Minimal typed xbmcaddon.Settings double recording all writes."""

    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def getBool(self, key):
        return bool(self.data.get(key, False))

    def setBool(self, key, val):
        self.data[key] = bool(val)

    def getInt(self, key):
        return int(self.data.get(key, 0))

    def setInt(self, key, val):
        self.data[key] = int(val)

    def getNumber(self, key):
        return float(self.data.get(key, 0.0))

    def setNumber(self, key, val):
        self.data[key] = float(val)

    def getString(self, key):
        return str(self.data.get(key, ''))

    def setString(self, key, val):
        self.data[key] = str(val)


class _InMemorySubtitleAddon:
    def __init__(self, path, initial=None):
        self._path = path
        self.settings = _InMemoryKodiSettings(initial)
        self.get_settings_called = 0

    def getAddonInfo(self, key):
        if key == 'path':
            return self._path
        return ''

    def getSettings(self):
        self.get_settings_called += 1
        return self.settings


def _load_subtitle_service_module():
    path = os.path.join(_REPO_ROOT, 'service.subtitles.otaku.rpdev', 'service.py')
    spec = importlib.util.spec_from_file_location('otaku_subtitles_service_split_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSubtitleSettingsSplit(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        conftest.reset_settings_to_defaults(include_test_fixtures=True)
        sub_pkg._SUBTITLE_MIGRATION_CHECKED = False
        control._last_subtitle_settings_epoch = ''
        control._last_subtitle_settings_stat = control._UNSET_STAT
        control._last_subtitle_stat_check_ts = 0.0
        control.homeWindow.clearProperty(control._SUBTITLE_SETTINGS_EPOCH_PROP)

    def tearDown(self):
        control.clearSettingsCache()
        conftest.restore_fixture_settings()
        sub_pkg._SUBTITLE_MIGRATION_CHECKED = False

    # ── 1. Guardrail 1: On-Disk v1.1.0+ Schema Readiness Guard ───────────────

    def test_migration_defers_cleanly_when_v103_stub_is_on_disk(self):
        """Guardrail 1: If service.subtitles.otaku.rpdev v1.0.3 is still on disk, return 0 without touching settings."""
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = os.path.join(tmp, 'service.subtitles.otaku.rpdev')
            os.makedirs(os.path.join(stub_dir, 'resources'), exist_ok=True)
            with open(os.path.join(stub_dir, 'resources', 'settings.xml'), 'w', encoding='utf-8') as f:
                f.write(
                    '<settings version="1"><section id="service.subtitles.otaku.rpdev">'
                    '<category id="general" label="30001"><group id="1" label="30001">'
                    '<setting id="open_otaku_settings" type="action" label="30002"/>'
                    '</group></category></section></settings>'
                )
            plugin_xml = os.path.join(tmp, 'plugin_settings.xml')
            with open(plugin_xml, 'w', encoding='utf-8') as f:
                f.write(
                    '<settings version="2">'
                    '<setting id="subtitles.subdl.apikey">keep_me_safe</setting>'
                    '</settings>'
                )

            addon_double = _InMemorySubtitleAddon(stub_dir)
            count = migration.migrate_subtitle_settings(
                plugin_settings_xml=plugin_xml,
                subtitle_addon=addon_double,
            )
            self.assertEqual(count, 0)
            self.assertEqual(addon_double.get_settings_called, 0)
            self.assertNotIn('subtitles.migrated_from_plugin_v1', addon_double.settings.data)

    # ── 2. Pre-Prune Raw-XML Migration (v2 & v1 formats) ────────────────────

    def test_migration_copies_v2_and_v1_values_and_is_idempotent(self):
        """Pre-prune raw-XML migration preserves provider toggles, credentials, and tuning across v2 & v1 XML."""
        real_sub_dir = os.path.join(_REPO_ROOT, 'service.subtitles.otaku.rpdev')
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = os.path.join(tmp, 'settings.xml')
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<settings version="2">\n'
                    '  <setting id="subtitles.enabled">false</setting>\n'
                    '  <setting id="subtitles.timeout">25</setting>\n'
                    '  <setting id="subtitles.results_limit" value="35" />\n'
                    '  <setting id="subtitles.prefer_forced" value="true" />\n'
                    '  <setting id="subtitles.opensubtitles.username">anime_fan</setting>\n'
                    '  <setting id="subtitles.opensubtitles.password">s3cr3t_pw</setting>\n'
                    '  <setting id="subtitles.subdl.apikey">subdl_abc</setting>\n'
                    '  <setting id="subtitles.subsource.apikey">subsrc_xyz</setting>\n'
                    '  <setting id="subtitles.jimaku.apikey">jimaku_jp_key</setting>\n'
                    '  <setting id="subtitles.provider.addic7ed">false</setting>\n'
                    '  <setting id="subtitles.provider.podnadpisi" default="true">true</setting>\n'
                    '  <setting id="general.smartplay">true</setting>\n'
                    '</settings>\n'
                )

            addon_double = _InMemorySubtitleAddon(real_sub_dir)
            migrated = migration.migrate_subtitle_settings(
                plugin_settings_xml=xml_path,
                subtitle_addon=addon_double,
            )
            self.assertEqual(migrated, 10)
            self.assertTrue(addon_double.settings.data['subtitles.migrated_from_plugin_v1'])
            self.assertFalse(addon_double.settings.data['subtitles.enabled'])
            self.assertEqual(addon_double.settings.data['subtitles.timeout'], 25)
            self.assertEqual(addon_double.settings.data['subtitles.results_limit'], 35)
            self.assertTrue(addon_double.settings.data['subtitles.prefer_forced'])
            self.assertEqual(addon_double.settings.data['subtitles.opensubtitles.username'], 'anime_fan')
            self.assertEqual(addon_double.settings.data['subtitles.opensubtitles.password'], 's3cr3t_pw')
            self.assertEqual(addon_double.settings.data['subtitles.subdl.apikey'], 'subdl_abc')
            self.assertEqual(addon_double.settings.data['subtitles.subsource.apikey'], 'subsrc_xyz')
            self.assertEqual(addon_double.settings.data['subtitles.jimaku.apikey'], 'jimaku_jp_key')
            self.assertFalse(addon_double.settings.data['subtitles.provider.addic7ed'])
            self.assertNotIn('subtitles.provider.podnadpisi', addon_double.settings.data)
            self.assertNotIn('general.smartplay', addon_double.settings.data)

            # Second run must be a strict no-op
            migrated_again = migration.migrate_subtitle_settings(
                plugin_settings_xml=xml_path,
                subtitle_addon=addon_double,
            )
            self.assertEqual(migrated_again, 0)

    def test_migration_fresh_install_and_corrupt_xml_safe(self):
        real_sub_dir = os.path.join(_REPO_ROOT, 'service.subtitles.otaku.rpdev')
        with tempfile.TemporaryDirectory() as tmp:
            # Fresh install: missing plugin settings.xml -> marks migrated cleanly
            missing_xml = os.path.join(tmp, 'does_not_exist.xml')
            addon_fresh = _InMemorySubtitleAddon(real_sub_dir)
            self.assertEqual(migration.migrate_subtitle_settings(missing_xml, addon_fresh), 0)
            self.assertTrue(addon_fresh.settings.data.get('subtitles.migrated_from_plugin_v1'))

            # Corrupt XML -> returns 0 without crashing or marking migrated
            bad_xml = os.path.join(tmp, 'corrupt.xml')
            with open(bad_xml, 'w', encoding='utf-8') as f:
                f.write('<settings><broken')
            addon_bad = _InMemorySubtitleAddon(real_sub_dir)
            self.assertEqual(migration.migrate_subtitle_settings(bad_xml, addon_bad), 0)
            self.assertFalse(addon_bad.settings.data.get('subtitles.migrated_from_plugin_v1', False))

    # ── 3. Guardrail 2: Lazy Fallback & sys.path Bridge ─────────────────────

    def test_lazy_migration_fallback_and_service_sys_path_bridge(self):
        """Both subtitles/__init__.py and service.subtitles.otaku.rpdev/service.py bridge otaku_service safely."""
        svc_mod = _load_subtitle_service_module()
        lib_dir = svc_mod._ensure_otaku_service_on_path()
        self.assertTrue(lib_dir and os.path.isdir(lib_dir))
        self.assertIn(lib_dir, sys.path)

        with patch('otaku_service.migration.migrate_subtitle_settings', return_value=3) as mock_mig:
            self.assertEqual(svc_mod._ensure_subtitle_settings_migrated(), 3)
            mock_mig.assert_called_once()

        with patch('otaku_service.migration.migrate_subtitle_settings', side_effect=RuntimeError('disabled')):
            self.assertEqual(svc_mod._ensure_subtitle_settings_migrated(), 0)
            sub_pkg._SUBTITLE_MIGRATION_CHECKED = False
            self.assertEqual(sub_pkg._ensure_subtitle_settings_migrated(), 0)

    # ── 4. Guardrail 5: Strict Kodi 22 Routing, Proxy Fallback & Epoch/Stat ─

    def test_strict_kodi22_routing_and_proxy_runtime_error_fallback(self):
        """All 24 SUBTITLE_SETTING_IDS route cleanly under KodiProfile('22', strict_settings=True)."""
        with KodiProfile('22', strict_settings=True):
            control.setBool('subtitles.enabled', True)
            control.setBool('subtitles.prefer_forced', True)
            control.setInt('subtitles.timeout', 18)
            control.setSetting('subtitles.jimaku.apikey', 'jm_strict_22')
            self.assertTrue(control.getBool('subtitles.enabled'))
            self.assertTrue(control.getBool('subtitles.prefer_forced'))
            self.assertEqual(control.getInt('subtitles.timeout'), 18)
            self.assertEqual(control.getSetting('subtitles.jimaku.apikey'), 'jm_strict_22')

            # Plugin-owned Subtitles setting still routes to plugin.video.otaku.rpdev
            control.setInt('general.subtitles', 2)
            self.assertEqual(control.getInt('general.subtitles'), 2)

        # Resilient _SettingsProxy fallback on RuntimeError with once-per-session warning
        proxy = control._SettingsProxy(control.SUBTITLE_ADDON_ID)
        conftest.mock_xbmc.log.reset_mock()
        with patch.object(control.xbmcaddon, 'Addon', side_effect=RuntimeError('subtitle addon disabled')):
            self.assertEqual(proxy.getBool('subtitles.enabled', True), True)
            self.assertEqual(proxy.getInt('subtitles.timeout', 15), 15)
            self.assertEqual(proxy.getString('subtitles.subdl.apikey', 'fallback'), 'fallback')
            self.assertFalse(proxy.setBool('subtitles.enabled', False))
        warn_calls = [
            c for c in conftest.mock_xbmc.log.call_args_list
            if 'service.subtitles.otaku.rpdev unavailable' in str(c)
        ]
        self.assertEqual(len(warn_calls), 1, "Unavailable companion warning must log once per session")

    def test_cross_addon_epoch_and_mtime_instant_cache_invalidation(self):
        """Both otaku.subtitle_settings_epoch and subtitle settings.xml mtime/size immediately evict cache."""
        control.setInt('subtitles.timeout', 12)
        ep1 = control.homeWindow.getProperty(control._SUBTITLE_SETTINGS_EPOCH_PROP)
        self.assertTrue(ep1.isdigit() and int(ep1) >= 1)
        self.assertEqual(control.getInt('subtitles.timeout'), 12)

        # Simulate another process mutating underlying store + bumping epoch
        conftest._settings_store['subtitles.timeout'] = '22'
        control.homeWindow.setProperty(control._SUBTITLE_SETTINGS_EPOCH_PROP, str(int(ep1) + 1))
        self.assertEqual(control.getInt('subtitles.timeout'), 22)

        # Simulate Kodi GUI editing service.subtitles.otaku.rpdev/settings.xml directly (mtime/size change)
        sub_profile = conftest.mock_xbmcvfs.translatePath('special://profile/addon_data/service.subtitles.otaku.rpdev/')
        os.makedirs(sub_profile, exist_ok=True)
        sub_xml = os.path.join(sub_profile, 'settings.xml')
        with open(sub_xml, 'w', encoding='utf-8') as f:
            f.write('<settings version="2"><setting id="subtitles.timeout">22</setting></settings>')
        control._sync_subtitle_settings_epoch(force_stat=True)

        # Now mutate file size & underlying store without bumping epoch -> force_stat=True via init_session() evicts
        conftest._settings_store['subtitles.timeout'] = '29'
        with open(sub_xml, 'w', encoding='utf-8') as f:
            f.write('<settings version="2"><setting id="subtitles.timeout">29</setting><!-- changed --></settings>')
        control.init_session()
        self.assertEqual(control.getInt('subtitles.timeout'), 29)

        # Monitor.check_subtitle_settings_changed detects subsequent edits and bumps epoch
        mon = daemon.Monitor()
        self.assertFalse(mon.check_subtitle_settings_changed(force=False))
        ep_before = control.homeWindow.getProperty(control._SUBTITLE_SETTINGS_EPOCH_PROP)
        with open(sub_xml, 'w', encoding='utf-8') as f:
            f.write('<settings version="2"><setting id="subtitles.timeout">14</setting><!-- monitor edit --></settings>')
        self.assertTrue(mon.check_subtitle_settings_changed(force=False))
        ep_after = control.homeWindow.getProperty(control._SUBTITLE_SETTINGS_EPOCH_PROP)
        self.assertGreater(int(ep_after), int(ep_before))

        # Missing settings.xml / OSError in _stat_subtitle_settings_file is ignored cleanly
        with patch('os.stat', side_effect=FileNotFoundError('missing')):
            self.assertIsNone(control._stat_subtitle_settings_file())
            control._sync_subtitle_settings_epoch(force_stat=True)

    # ── 5. Guardrails 4 & 6: Tri-Profile Settings Manager, Wipe & Shortcuts ─

    def test_tri_profile_category_resets_and_subtitles_backup_scope(self):
        """Category resets preserve migration markers; subtitles backup scope covers all 3 subtitle categories."""
        control.setBool('service.migrated_from_plugin_v1', True)
        control.setBool('subtitles.migrated_from_plugin_v1', True)
        control.setInt('general.subtitles', 5)
        control.setInt('subtitles.timeout', 27)
        control.setSetting('subtitles.jimaku.apikey', 'jimaku_secret_key_99')
        control.setBool('subtitles.provider.jimaku', False)

        # Resetting SubtitleService only resets SubtitleService, NOT plugin Subtitles or SubtitleProviders or marker
        reset_svc = settings_manager.reset_category_settings('SubtitleService')
        self.assertEqual(reset_svc, 10)
        self.assertEqual(control.getInt('subtitles.timeout'), 15)
        self.assertEqual(control.getInt('general.subtitles'), 5)
        self.assertEqual(control.getSetting('subtitles.jimaku.apikey'), 'jimaku_secret_key_99')
        self.assertTrue(control.getBool('subtitles.migrated_from_plugin_v1'))

        # Resetting Subtitles resets only plugin's 7 Subtitles value settings
        reset_plg = settings_manager.reset_category_settings('Subtitles')
        self.assertEqual(reset_plg, 7)
        self.assertEqual(control.getInt('general.subtitles'), 1)
        self.assertEqual(control.getSetting('subtitles.jimaku.apikey'), 'jimaku_secret_key_99')

        # Resetting SubtitleProviders resets the 13 provider settings
        reset_prov = settings_manager.reset_category_settings('SubtitleProviders')
        self.assertEqual(reset_prov, 13)
        self.assertEqual(control.getSetting('subtitles.jimaku.apikey'), '')

        # Export & import under 'subtitles' scope + Jimaku reconciliation + migration marker exclusion
        control.setInt('general.subtitles', 2)
        control.setInt('subtitles.timeout', 19)
        control.setSetting('subtitles.jimaku.apikey', 'jm_reconcile_token_77')
        control.setBool('subtitles.provider.jimaku', True)

        with tempfile.TemporaryDirectory() as tmp:
            ok, bpath, cnt = settings_manager.export_settings('subtitles', tmp)
            self.assertTrue(ok)
            self.assertEqual(cnt, 30)  # 7 plugin + 10 engine + 13 providers (excludes migration marker)
            with open(bpath, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            self.assertEqual(payload['addon_versions']['service.subtitles.otaku.rpdev'], '1.1.0')
            self.assertNotIn('subtitles.migrated_from_plugin_v1', payload['settings'])
            self.assertNotIn('service.migrated_from_plugin_v1', payload['settings'])

            # Inject migration marker into backup to verify import ignores it
            payload['settings']['subtitles.migrated_from_plugin_v1'] = False
            payload['settings'].pop('subtitles.provider.jimaku', None)
            with open(bpath, 'w', encoding='utf-8') as f:
                json.dump(payload, f)

            control.setInt('general.subtitles', 0)
            control.setInt('subtitles.timeout', 10)
            control.setSetting('subtitles.jimaku.apikey', '')
            control.setBool('subtitles.provider.jimaku', False)
            control.setBool('subtitles.migrated_from_plugin_v1', True)

            ok_imp, imp_cnt = settings_manager.import_settings('subtitles', bpath)
            self.assertTrue(ok_imp)
            self.assertEqual(imp_cnt, 29)
            self.assertEqual(control.getInt('general.subtitles'), 2)
            self.assertEqual(control.getInt('subtitles.timeout'), 19)
            self.assertEqual(control.getSetting('subtitles.jimaku.apikey'), 'jm_reconcile_token_77')
            self.assertTrue(control.getBool('subtitles.provider.jimaku'))
            self.assertTrue(control.getBool('subtitles.migrated_from_plugin_v1'))

    def test_wipe_addon_data_wipes_subtitle_profile_and_preserves_c30_temp(self):
        """Guardrail 6: wipe_addon_data deletes subtitle settings.xml, resets both markers, and preserves C-30 temp/."""
        sub_profile = conftest.mock_xbmcvfs.translatePath('special://profile/addon_data/service.subtitles.otaku.rpdev/')
        sub_temp = os.path.join(sub_profile, 'temp')
        os.makedirs(sub_temp, exist_ok=True)
        sub_settings_file = os.path.join(sub_profile, 'settings.xml')
        staged_sub = os.path.join(sub_temp, 'staged_ep01.ass')
        with open(sub_settings_file, 'w', encoding='utf-8') as f:
            f.write('<settings version="2"><setting id="subtitles.subdl.apikey">secret</setting></settings>')
        with open(staged_sub, 'w', encoding='utf-8') as f:
            f.write('[Script Info]\n')

        control.setBool('service.migrated_from_plugin_v1', True)
        control.setBool('subtitles.migrated_from_plugin_v1', True)
        control.setSetting('subtitles.jimaku.apikey', 'wipe_this_jimaku_key')

        with patch('resources.lib.ui.database_sync.SyncDatabase._create_all_tables'), \
             patch('resources.lib.ui.database_sync.SyncDatabase.set_base_activites'):
            self.assertTrue(settings_manager.wipe_addon_data(silent=True))

        self.assertFalse(os.path.exists(sub_settings_file))
        self.assertTrue(os.path.isdir(sub_temp), "C-30 temp staging directory must be preserved during wipe_addon_data")
        self.assertTrue(os.path.isfile(staged_sub))
        self.assertEqual(control.getSetting('subtitles.jimaku.apikey'), '')
        self.assertFalse(control.getBool('service.migrated_from_plugin_v1'))
        self.assertFalse(control.getBool('subtitles.migrated_from_plugin_v1'))

    def test_jimaku_log_redaction_and_shortcut_routes_and_tools_menu(self):
        """sanitize_log redacts Jimaku API key; open_subtitle_service_settings route & Tools entry work cleanly."""
        control.setSetting('subtitles.jimaku.apikey', 'JM_TOP_SECRET_8899')
        sanitized = control.sanitize_log('Authorization: JM_TOP_SECRET_8899 failed')
        self.assertNotIn('JM_TOP_SECRET_8899', sanitized)
        self.assertIn('[REDACTED]', sanitized)

        conftest.mock_xbmc.executebuiltin.reset_mock()
        with patch.object(control, 'exit_code', return_value=None) as mock_exit:
            sub_routes.handle_open_subtitle_service_settings('', {})
            mock_exit.assert_called_once()
        conftest.mock_xbmc.executebuiltin.assert_called_with('Addon.OpenSettings(service.subtitles.otaku.rpdev)')

        tools_entries = Main._tools_menu()
        tool_paths = [row[1] for row in tools_entries]
        self.assertIn('open_service_settings', tool_paths)
        self.assertIn('open_subtitle_service_settings', tool_paths)
        self.assertEqual(tool_paths.index('open_subtitle_service_settings'), tool_paths.index('open_service_settings') + 1)


if __name__ == '__main__':
    unittest.main()
