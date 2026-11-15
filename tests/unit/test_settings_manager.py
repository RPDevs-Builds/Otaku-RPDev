# -*- coding: utf-8 -*-
"""Unit tests for Settings Manager, Modal Backup Dialog, and Settings Reset Suite.

Verifies:
1. Login/credential setting classification across Debrid, Watchlists, and Subtitles.
2. Canonical settings extraction and typing from resources/settings.xml.
3. Active settings retrieval across 'all', 'logins', and 'settings' scopes.
4. Export functionality generating schema-valid timestamped JSON backups.
5. Import functionality applying JSON backups and legacy settings.xml with scope filtering.
6. Per-category reset to addon defaults.
7. Non-destructive global reset to defaults preserving all login credentials.
8. Destructive Wipe Addon Data full factory reset.
9. SettingsBackupDialog modal interactions and fallbacks.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_PLUGIN_DIR = os.path.join(_REPO_ROOT, 'plugin.video.otaku.rpdev')
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401
from resources.lib.ui import control, settings_manager
from resources.lib.windows import settings_backup


class TestSettingsManager(unittest.TestCase):
    """Test suite for settings_manager.py and SettingsBackupDialog."""

    def setUp(self):
        control._settings_cache.clear()
        conftest.reset_settings_to_defaults(include_test_fixtures=True)
        self.temp_dir = tempfile.mkdtemp(prefix="otaku_settings_test_")

    def tearDown(self):
        control._settings_cache.clear()
        conftest.restore_fixture_settings()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_login_settings_classification(self):
        """Verify that all 53 credential/token keys are classified as logins, and general preferences are not."""
        # 1. All explicitly registered keys
        for sid in settings_manager.LOGIN_SETTING_IDS:
            self.assertTrue(settings_manager.is_login_setting(sid), f"Key '{sid}' must be recognized as login")

        # 2. General preferences must NOT be classified as logins
        non_logins = [
            'general.verify_ssl',
            'general.timeout',
            'general.autotrynext',
            'scraper.concurrency.workers',
            'playingnext.time',
            'playingnext.defaultaction',
            'general.subtitles',
            'db.sqlite.cache_size_mb',
            'first_time',
            'provider.nyaa',
        ]
        for sid in non_logins:
            self.assertFalse(settings_manager.is_login_setting(sid), f"Key '{sid}' should NOT be recognized as login")

        # 3. None and empty strings
        self.assertFalse(settings_manager.is_login_setting(''))
        self.assertFalse(settings_manager.is_login_setting(None))

    def test_get_canonical_settings(self):
        """Verify get_canonical_settings extracts all stored settings with proper types."""
        canonical = settings_manager.get_canonical_settings()
        self.assertIsInstance(canonical, dict)
        self.assertGreaterEqual(len(canonical), 390)

        # Inspect specific typed settings
        self.assertIn('first_time', canonical)
        self.assertEqual(canonical['first_time']['type'], 'boolean')
        self.assertTrue(canonical['first_time']['default'])

        self.assertIn('general.timeout', canonical)
        self.assertEqual(canonical['general.timeout']['type'], 'integer')
        self.assertEqual(canonical['general.timeout']['default'], 20)

        self.assertIn('realdebrid.token', canonical)
        self.assertEqual(canonical['realdebrid.token']['type'], 'string')

    def test_get_active_settings_scopes(self):
        """Verify get_active_settings filters correctly by 'all', 'logins', and 'settings' scopes."""
        all_settings = settings_manager.get_active_settings(scope='all')
        logins_only = settings_manager.get_active_settings(scope='logins')
        settings_only = settings_manager.get_active_settings(scope='settings')

        self.assertEqual(len(all_settings), len(logins_only) + len(settings_only))

        for sid in logins_only:
            self.assertTrue(settings_manager.is_login_setting(sid))

        for sid in settings_only:
            self.assertFalse(settings_manager.is_login_setting(sid))

    def test_export_settings_all_scopes(self):
        """Verify export_settings serializes settings to JSON with metadata across all scopes."""
        for scope in ('all', 'logins', 'settings'):
            success, filepath, count = settings_manager.export_settings(scope, self.temp_dir)
            self.assertTrue(success)
            self.assertTrue(os.path.isfile(filepath))
            self.assertGreater(count, 0)
            self.assertIn(f"otaku_backup_{scope}_", os.path.basename(filepath))

            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.assertEqual(data.get('otaku_backup_version'), 1)
            self.assertEqual(data.get('scope'), scope)
            self.assertEqual(data.get('settings_count'), count)
            self.assertIn('timestamp', data)
            self.assertIn('addon_version', data)
            self.assertIsInstance(data.get('settings'), dict)

    def test_import_settings_json_and_scope_filtering(self):
        """Verify import_settings correctly restores values from JSON backup files respecting scopes."""
        # Setup test backup payload
        backup_payload = {
            'otaku_backup_version': 1,
            'scope': 'all',
            'timestamp': '2026-11-14T23:00:00',
            'addon_version': '0.5.43',
            'settings': {
                'realdebrid.token': 'imported_rd_token_abc',
                'anilist.username': 'imported_anilist_user',
                'general.timeout': 45,
                'general.autotrynext': False,
            }
        }
        backup_file = os.path.join(self.temp_dir, 'test_backup.json')
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_payload, f)

        # 1. Import with scope='logins' -> only logins should change
        control.setString('realdebrid.token', 'original_token')
        control.setString('anilist.username', 'original_user')
        control.setInt('general.timeout', 15)

        success, count = settings_manager.import_settings('logins', backup_file)
        self.assertTrue(success)
        self.assertEqual(count, 2)
        self.assertEqual(control.getSetting('realdebrid.token'), 'imported_rd_token_abc')
        self.assertEqual(control.getSetting('anilist.username'), 'imported_anilist_user')
        # General timeout should remain unchanged
        self.assertEqual(control.getInt('general.timeout'), 15)

        # 2. Import with scope='settings' -> only preferences should change
        control.setString('realdebrid.token', 'keep_this_token')
        success, count = settings_manager.import_settings('settings', backup_file)
        self.assertTrue(success)
        self.assertEqual(count, 2)
        self.assertEqual(control.getSetting('realdebrid.token'), 'keep_this_token')
        self.assertEqual(control.getInt('general.timeout'), 45)
        self.assertFalse(control.getBool('general.autotrynext'))

    def test_import_settings_legacy_xml(self):
        """Verify import_settings can parse and apply settings from legacy Kodi settings.xml files."""
        legacy_xml_content = """<settings version="4">
            <setting id="realdebrid.token">xml_rd_token_xyz</setting>
            <setting id="general.timeout">30</setting>
            <setting id="general.autotrynext">false</setting>
        </settings>"""
        legacy_file = os.path.join(self.temp_dir, 'settings.xml')
        with open(legacy_file, 'w', encoding='utf-8') as f:
            f.write(legacy_xml_content)

        success, count = settings_manager.import_settings('all', legacy_file)
        self.assertTrue(success)
        self.assertEqual(count, 3)
        self.assertEqual(control.getSetting('realdebrid.token'), 'xml_rd_token_xyz')
        self.assertEqual(control.getInt('general.timeout'), 30)
        self.assertFalse(control.getBool('general.autotrynext'))

    def test_reset_category_settings(self):
        """Verify reset_category_settings reverts only the targeted category to canonical defaults."""
        # Mutate settings in Cache and Scraping
        control.setInt('general.timeout', 99)
        control.setInt('cache.scrapers.ttl', 999)

        # Reset only Cache
        count = settings_manager.reset_category_settings('Cache')
        self.assertGreater(count, 0)

        # Cache setting reverted to default (8)
        self.assertEqual(control.getInt('cache.scrapers.ttl'), 8)
        # Scraping timeout remained 99
        self.assertEqual(control.getInt('general.timeout'), 99)

    def test_reset_settings_to_defaults_preserves_logins(self):
        """Verify non-destructive reset_settings_to_defaults resets preferences but preserves logins."""
        # Mutate login credentials
        control.setString('realdebrid.token', 'my_important_debrid_token')
        control.setString('anilist.username', 'my_watchlist_user')
        control.setString('subtitles.opensubtitles.username', 'sub_user')

        # Mutate general preferences
        control.setInt('general.timeout', 99)
        control.setBool('general.autotrynext', False)
        control.setInt('cache.scrapers.ttl', 999)

        # Perform non-destructive reset
        count = settings_manager.reset_settings_to_defaults(preserve_logins=True)
        self.assertGreater(count, 300)

        # Assert logins are strictly preserved
        self.assertEqual(control.getSetting('realdebrid.token'), 'my_important_debrid_token')
        self.assertEqual(control.getSetting('anilist.username'), 'my_watchlist_user')
        self.assertEqual(control.getSetting('subtitles.opensubtitles.username'), 'sub_user')

        # Assert preferences reverted to canonical defaults
        self.assertEqual(control.getInt('general.timeout'), 20)
        self.assertTrue(control.getBool('general.autotrynext'))
        self.assertEqual(control.getInt('cache.scrapers.ttl'), 8)

    def test_wipe_addon_data_full_factory_reset(self):
        """Verify wipe_addon_data performs a complete factory reset wiping settings, logins, and DBs."""
        # Set test logins and preferences
        control.setString('realdebrid.token', 'rd_token_to_wipe')
        control.setString('anilist.username', 'user_to_wipe')
        control.setInt('general.timeout', 88)
        control.setBool('first_time', False)
        control.setString('version', '0.5.43')

        # Create dummy user files in dataPath
        dummy_db = os.path.join(control.dataPath, 'test_dummy.db')
        dummy_json = os.path.join(control.dataPath, 'test_dummy.json')
        with open(dummy_db, 'w') as f:
            f.write("sqlite format 3")
        with open(dummy_json, 'w') as f:
            f.write("{}")

        self.assertTrue(os.path.exists(dummy_db))
        self.assertTrue(os.path.exists(dummy_json))

        # Perform factory wipe
        with patch('resources.lib.ui.database_sync.SyncDatabase._create_all_tables') as mock_tables:
            with patch('resources.lib.ui.database_sync.SyncDatabase.set_base_activites') as mock_base:
                success = settings_manager.wipe_addon_data(silent=True)
                self.assertTrue(success)
                mock_tables.assert_called_once()
                mock_base.assert_called_once()

        # Assert logins are wiped
        self.assertEqual(control.getSetting('realdebrid.token'), '')
        self.assertEqual(control.getSetting('anilist.username'), '')

        # Assert preferences reverted to defaults
        self.assertEqual(control.getInt('general.timeout'), 20)
        self.assertTrue(control.getBool('first_time'))
        self.assertEqual(control.getSetting('version'), '')

        # Assert dummy files in dataPath were removed
        self.assertFalse(os.path.exists(dummy_db))
        self.assertFalse(os.path.exists(dummy_json))

    def test_settings_backup_dialog_items_and_modes(self):
        """Verify SettingsBackupDialog initializes properly for both export and import modes."""
        # 1. Export mode
        export_dlg = settings_backup.SettingsBackupDialog("settings_backup.xml", control.ADDON_PATH, mode='export')
        self.assertEqual(export_dlg.mode, 'export')
        self.assertEqual(len(export_dlg._items_meta), 3)
        self.assertEqual([item['action'] for item in export_dlg._items_meta], ['all', 'logins', 'settings'])
        self.assertIn("Export", export_dlg.header)

        # 2. Import mode
        import_dlg = settings_backup.SettingsBackupDialog("settings_backup.xml", control.ADDON_PATH, mode='import')
        self.assertEqual(import_dlg.mode, 'import')
        self.assertEqual(len(import_dlg._items_meta), 3)
        self.assertEqual([item['action'] for item in import_dlg._items_meta], ['all', 'logins', 'settings'])
        self.assertIn("Import", import_dlg.header)

    def test_show_settings_backup_dialog_fallback(self):
        """Verify show_settings_backup_dialog falls back to select_dialog if WindowXML raises."""
        with patch('resources.lib.windows.settings_backup.SettingsBackupDialog.doModal', side_effect=RuntimeError("No GUI")):
            with patch('resources.lib.ui.control.select_dialog', return_value=1) as mock_select:
                result = settings_backup.show_settings_backup_dialog(mode='export')
                self.assertEqual(result, 'logins')
                mock_select.assert_called_once()


if __name__ == '__main__':
    unittest.main()
