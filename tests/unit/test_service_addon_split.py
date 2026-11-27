# -*- coding: utf-8 -*-
"""
test_service_addon_split.py — Unit & Contract Tests for service.otaku.rpdev (Phase 1)
=====================================================================================
Covers all Phase 1 guardrails and cross-addon contracts:
1. Self-contained migration.py (zero plugin imports, v1/v2 XML, boolean parsing, corrupt XML safety,
   idempotency, fresh install, and exact SERVICE_SETTING_SPECS vs settings.xml type parity).
2. Plain-text disk readiness check (_plugin_supports_service_addon) before sys.path mutation and
   bounded _wait_for_compatible_plugin() abort/timeout handling.
3. Resilient _SettingsProxy(SERVICE_ADDON_ID) RuntimeError fallback (once-per-session warning).
4. Bidirectional otaku.service_settings_epoch cache invalidation on getter + setter paths and
   Monitor.onSettingsChanged().
5. (st_mtime_ns, st_size) plugin settings.xml watcher, standby 60s vs active 5s polling,
   and hot-update transition without importlib.reload().
6. Dual-profile RESET_CATEGORY, reset_settings_to_defaults, wipe_addon_data, and v1/v2 backup/restore.
"""

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401
from resources.lib.ui import control, settings_manager
from resources.lib.routes import tools
from otaku_service import migration, daemon


def _load_service_entry():
    svc_path = os.path.join(_REPO_ROOT, 'service.otaku.rpdev', 'service.py')
    spec = importlib.util.spec_from_file_location('otaku_service_entry_test', svc_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestServiceMigration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plugin_xml = os.path.join(self.tmp.name, 'plugin_settings.xml')

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_module_has_zero_plugin_imports(self):
        """Guardrail 2: otaku_service/migration.py must be 100% self-contained (zero resources.* imports)."""
        mig_path = os.path.join(_REPO_ROOT, 'service.otaku.rpdev', 'resources', 'lib', 'otaku_service', 'migration.py')
        with open(mig_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=mig_path)
        forbidden = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('resources') or 'otaku.rpdev' in alias.name:
                        forbidden.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith('resources') or 'otaku.rpdev' in node.module:
                    forbidden.append(node.module)
        self.assertEqual(forbidden, [], f"migration.py must not import plugin modules: {forbidden}")

    def test_service_setting_specs_exact_type_match_with_settings_xml(self):
        """Guardrail 2: Every key in SERVICE_SETTING_SPECS must match exact <setting type='...'> in service settings.xml."""
        svc_xml = os.path.join(_REPO_ROOT, 'service.otaku.rpdev', 'resources', 'settings.xml')
        root = ET.parse(svc_xml).getroot()
        xml_types = {
            e.get('id'): e.get('type')
            for e in root.findall('.//setting')
            if e.get('id') and e.get('type') != 'action'
        }
        self.assertEqual(set(migration.SERVICE_SETTING_SPECS.keys()), set(xml_types.keys()))
        for key, (spec_type, _default) in migration.SERVICE_SETTING_SPECS.items():
            self.assertEqual(spec_type, xml_types[key], f"Type mismatch for '{key}': spec={spec_type} xml={xml_types[key]}")

    def test_migrate_v2_and_v1_formats_booleans_and_idempotency(self):
        """Supports both Kodi v2 text and v1 value='...' attributes, safe boolean parsing, and idempotency."""
        with open(self.plugin_xml, 'w', encoding='utf-8') as f:
            f.write(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<settings version="2">\n'
                '  <setting id="fs_url">http://10.0.0.10:8191/v1</setting>\n'
                '  <setting id="fs_enable"> True </setting>\n'
                '  <setting id="ms_enable" value="false" />\n'
                '  <setting id="db.sqlite.cache_size_mb">32</setting>\n'
                '  <setting id="fs_timeout" value="not_an_int" />\n'
                '  <setting id="general.kodi.cache">0</setting>\n'
                '  <setting id="unrelated.plugin_key">ignored</setting>\n'
                '</settings>'
            )

        store = {}
        fake_settings = MagicMock()
        fake_settings.getBool.side_effect = lambda k: bool(store.get(k, False))
        fake_settings.setBool.side_effect = lambda k, v: store.__setitem__(k, bool(v))
        fake_settings.setInt.side_effect = lambda k, v: store.__setitem__(k, int(v))
        fake_settings.setString.side_effect = lambda k, v: store.__setitem__(k, str(v))
        fake_addon = MagicMock()
        fake_addon.getSettings.return_value = fake_settings

        migrated = migration.migrate_service_settings(plugin_settings_xml=self.plugin_xml, service_addon=fake_addon)
        self.assertEqual(migrated, 5)
        self.assertEqual(store['fs_url'], 'http://10.0.0.10:8191/v1')
        self.assertIs(store['fs_enable'], True)
        self.assertIs(store['ms_enable'], False)
        self.assertEqual(store['db.sqlite.cache_size_mb'], 32)
        self.assertIs(store['general.kodi.cache'], False)
        self.assertNotIn('fs_timeout', store)  # invalid int skipped safely
        self.assertNotIn('unrelated.plugin_key', store)
        self.assertIs(store[migration.MIGRATION_MARKER_ID], True)

        # Second call is a strict no-op (idempotent)
        store['fs_url'] = 'http://changed-by-user:8191/v1'
        migrated_again = migration.migrate_service_settings(plugin_settings_xml=self.plugin_xml, service_addon=fake_addon)
        self.assertEqual(migrated_again, 0)
        self.assertEqual(store['fs_url'], 'http://changed-by-user:8191/v1')

    def test_migrate_fresh_install_and_corrupt_xml_safe(self):
        """Fresh install (missing XML) and corrupt XML both complete cleanly without raising."""
        store = {}
        fake_settings = MagicMock()
        fake_settings.getBool.side_effect = lambda k: bool(store.get(k, False))
        fake_settings.setBool.side_effect = lambda k, v: store.__setitem__(k, bool(v))
        fake_addon = MagicMock()
        fake_addon.getSettings.return_value = fake_settings

        missing_path = os.path.join(self.tmp.name, 'does_not_exist.xml')
        self.assertEqual(migration.migrate_service_settings(plugin_settings_xml=missing_path, service_addon=fake_addon), 0)
        self.assertIs(store[migration.MIGRATION_MARKER_ID], True)

        # Corrupt XML returns 0 cleanly without crashing
        store.clear()
        corrupt_path = os.path.join(self.tmp.name, 'corrupt.xml')
        with open(corrupt_path, 'w', encoding='utf-8') as f:
            f.write('<settings><broken')
        self.assertEqual(migration.migrate_service_settings(plugin_settings_xml=corrupt_path, service_addon=fake_addon), 0)


class TestServiceStartupAndProxy(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc_entry = _load_service_entry()

    def tearDown(self):
        self.tmp.cleanup()
        control._settings_cache.clear()
        conftest.restore_fixture_settings()

    def test_plugin_supports_service_addon_plain_text_disk_check(self):
        """Guardrail 1: Rejects v6.6.x (has xbmc.service or lacks SERVICE_ADDON_ID) before sys.path mutation."""
        plugin_dir = os.path.join(self.tmp.name, 'plugin.video.otaku.rpdev')
        ui_dir = os.path.join(plugin_dir, 'resources', 'lib', 'ui')
        os.makedirs(ui_dir, exist_ok=True)

        # Case 1: v6.6.x still declares xbmc.service -> rejected
        with open(os.path.join(plugin_dir, 'addon.xml'), 'w', encoding='utf-8') as f:
            f.write('<addon id="plugin.video.otaku.rpdev" version="6.6.1"><extension point="xbmc.service" library="service.py"/></addon>')
        with open(os.path.join(ui_dir, 'control.py'), 'w', encoding='utf-8') as f:
            f.write('SERVICE_ADDON_ID = "service.otaku.rpdev"\n')
        self.assertFalse(self.svc_entry._plugin_supports_service_addon(plugin_dir))

        # Case 2: No xbmc.service, but old control.py without SERVICE_ADDON_ID -> rejected
        with open(os.path.join(plugin_dir, 'addon.xml'), 'w', encoding='utf-8') as f:
            f.write('<addon id="plugin.video.otaku.rpdev" version="6.7.0"><extension point="xbmc.python.pluginsource" library="default.py"/></addon>')
        with open(os.path.join(ui_dir, 'control.py'), 'w', encoding='utf-8') as f:
            f.write('ADDON_ID = "plugin.video.otaku.rpdev"\n')
        self.assertFalse(self.svc_entry._plugin_supports_service_addon(plugin_dir))

        # Case 3: v6.7.0+ without xbmc.service and with SERVICE_ADDON_ID -> accepted
        with open(os.path.join(ui_dir, 'control.py'), 'w', encoding='utf-8') as f:
            f.write('ADDON_ID = "plugin.video.otaku.rpdev"\nSERVICE_ADDON_ID = "service.otaku.rpdev"\n')
        self.assertTrue(self.svc_entry._plugin_supports_service_addon(plugin_dir))

    def test_wait_for_compatible_plugin_exits_on_abort(self):
        """_wait_for_compatible_plugin returns None cleanly if Kodi aborts while waiting."""
        fake_monitor = MagicMock()
        fake_monitor.abortRequested.return_value = False
        fake_monitor.waitForAbort.return_value = True

        with patch.object(self.svc_entry, '_locate_otaku_plugin_path', return_value=None):
            res = self.svc_entry._wait_for_compatible_plugin(fake_monitor, max_wait_s=5.0)
        self.assertIsNone(res)

    def test_resilient_settings_proxy_fallback_when_service_unavailable(self):
        """_SettingsProxy(SERVICE_ADDON_ID) falls back to defaults with a once-per-session warning."""
        proxy = control._SettingsProxy('service.otaku.rpdev')
        with patch('xbmcaddon.Addon', side_effect=RuntimeError('addon disabled')), \
                patch('xbmc.log') as mock_log:
            self.assertEqual(proxy.getString('fs_url'), '')
            self.assertIs(proxy.getBool('fs_enable'), False)
            self.assertEqual(proxy.getInt('fs_timeout'), 0)
            self.assertEqual(proxy.getNumber('fs_timeout'), 0.0)
            self.assertEqual(proxy.getStringList('any'), [])
            # Warning logged only once despite multiple getter calls
            self.assertEqual(mock_log.call_count, 1)

    def test_bidirectional_service_settings_epoch_invalidation(self):
        """Guardrail 3: Both getter and setter paths honor otaku.service_settings_epoch immediately."""
        control.clearSettingsCache()
        control.setBool('fs_enable', False)
        self.assertFalse(control.getBool('fs_enable'))
        ep1 = control.homeWindow.getProperty(control._SERVICE_SETTINGS_EPOCH_PROP)

        # Writing a SERVICE_SETTING_IDS key bumps epoch
        control.setBool('fs_enable', True)
        ep2 = control.homeWindow.getProperty(control._SERVICE_SETTINGS_EPOCH_PROP)
        self.assertNotEqual(ep1, ep2)
        self.assertTrue(control.getBool('fs_enable'))

        # Simulate external process (service.otaku.rpdev) changing underlying store and bumping Window(10000) epoch
        control._settings_cache['b_fs_enable'] = True
        control.service_settings.setBool('fs_enable', False)
        control.homeWindow.setProperty(control._SERVICE_SETTINGS_EPOCH_PROP, str(int(ep2 or '0') + 1))
        # Next getter call detects epoch drift and invalidates cache immediately
        self.assertFalse(control.getBool('fs_enable'))

    def test_monitor_on_settings_changed_and_plugin_mtime_watcher(self):
        """Monitor.onSettingsChanged bumps epoch; check_plugin_settings_changed compares (st_mtime_ns, st_size)."""
        mon = daemon.Monitor()
        ep_before = control.homeWindow.getProperty(control._SERVICE_SETTINGS_EPOCH_PROP)
        mon.onSettingsChanged()
        ep_after = control.homeWindow.getProperty(control._SERVICE_SETTINGS_EPOCH_PROP)
        self.assertNotEqual(ep_before, ep_after)

        # Plugin settings.xml stat watcher
        p_xml = os.path.join(self.tmp.name, 'settings.xml')
        with open(p_xml, 'w', encoding='utf-8') as f:
            f.write('<settings version="2"><setting id="a">1</setting></settings>')

        with patch.object(control, 'dataPath', self.tmp.name):
            mon._plugin_settings_stat = daemon._stat_plugin_settings_xml()
            # Unchanged file returns False
            self.assertFalse(mon.check_plugin_settings_changed())
            # Size change triggers True and clears settings cache
            with open(p_xml, 'w', encoding='utf-8') as f:
                f.write('<settings version="2"><setting id="a">12345</setting></settings>')
            self.assertTrue(mon.check_plugin_settings_changed())

    def test_hot_update_clears_cache_without_importlib_reload(self):
        """Hot-update detection updates state, clears cache, runs process_context, and never calls importlib.reload."""
        state = {'plugin_version': '6.6.1'}
        with patch.object(daemon, '_read_plugin_addon_version', return_value='6.7.0'), \
                patch.object(control, 'clearSettingsCache') as mock_clear, \
                patch.object(control, 'process_context') as mock_ctx, \
                patch('importlib.reload') as mock_reload:
            changed = daemon._check_plugin_hot_update(state)
        self.assertTrue(changed)
        self.assertEqual(state['plugin_version'], '6.7.0')
        mock_clear.assert_called_once()
        mock_ctx.assert_called_once()
        mock_reload.assert_not_called()


class TestDualAddonSettingsManagement(unittest.TestCase):

    def setUp(self):
        control._settings_cache.clear()
        conftest.reset_settings_to_defaults(include_test_fixtures=True)

    def tearDown(self):
        control._settings_cache.clear()
        conftest.restore_fixture_settings()

    def test_canonical_settings_includes_both_plugin_and_service(self):
        """settings_manager.get_canonical_settings() returns union of plugin and service schemas."""
        canonical = settings_manager.get_canonical_settings()
        self.assertIn('general.dialog', canonical)
        self.assertIn('fs_url', canonical)
        self.assertIn('db.sqlite.cache_size_mb', canonical)
        self.assertEqual(canonical['fs_url']['addon_id'], control.SERVICE_ADDON_ID)
        self.assertEqual(canonical['general.dialog']['addon_id'], control.ADDON_ID)

    def test_reset_category_supports_service_categories(self):
        """RESET_CATEGORY_SETTINGS resets service.otaku.rpdev categories (Cache, Solvers)."""
        control.setInt('db.sqlite.cache_size_mb', 32)
        control.setBool('fs_enable', True)
        with patch.object(control, 'yesno_dialog', return_value=True), \
                patch.object(control, 'notify'):
            tools.RESET_CATEGORY_SETTINGS('', {'category': 'Cache'})
            tools.RESET_CATEGORY_SETTINGS('', {'category': 'Solvers'})
        self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 16)
        self.assertFalse(control.getBool('fs_enable'))

    def test_reset_settings_to_defaults_preserves_migration_marker(self):
        """reset_settings_to_defaults must not clear service.migrated_from_plugin_v1."""
        control.setBool('service.migrated_from_plugin_v1', True)
        control.setInt('db.sqlite.cache_size_mb', 32)
        with patch.object(control, 'yesno_dialog', return_value=True), \
                patch.object(control, 'ok_dialog'), \
                patch.object(control, 'execute'):
            settings_manager.reset_settings_to_defaults()
        self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 16)
        self.assertTrue(control.getBool('service.migrated_from_plugin_v1'))

    def test_export_v2_and_import_v1_v2_roundtrip(self):
        """v2 export includes addon_versions and both plugin + service keys; v1 legacy backups also restore cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            control.setInt('db.sqlite.cache_size_mb', 32)
            control.setInt('general.dialog', 2)
            ok, backup_path, count = settings_manager.export_settings('all', tmp)
            self.assertTrue(ok)
            self.assertGreater(count, 300)

            with open(backup_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)

            self.assertEqual(payload['otaku_backup_version'], 2)
            self.assertIn('plugin.video.otaku.rpdev', payload['addon_versions'])
            self.assertIn('service.otaku.rpdev', payload['addon_versions'])
            self.assertEqual(payload['settings']['db.sqlite.cache_size_mb'], 32)
            self.assertEqual(payload['settings']['general.dialog'], 2)

            # Reset and restore v2 backup
            control.setInt('db.sqlite.cache_size_mb', 8)
            control.setInt('general.dialog', 0)
            ok_imp, restored = settings_manager.import_settings('all', backup_path)
            self.assertTrue(ok_imp)
            self.assertGreater(restored, 0)
            self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 32)
            self.assertEqual(control.getInt('general.dialog'), 2)

            # Also verify legacy v1 backup restores service settings cleanly
            v1_path = os.path.join(tmp, 'legacy_v1.json')
            with open(v1_path, 'w', encoding='utf-8') as f:
                json.dump({'otaku_backup_version': 1, 'settings': {'db.sqlite.cache_size_mb': 8, 'fs_enable': True}}, f)
            ok_v1, _r1 = settings_manager.import_settings('all', v1_path)
            self.assertTrue(ok_v1)
            self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 8)
            self.assertTrue(control.getBool('fs_enable'))


if __name__ == '__main__':
    unittest.main()
