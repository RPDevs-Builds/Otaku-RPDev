"""
Unit tests for Orphaned Settings Pruner (clean_settings.py)
"""

# Standardized Otaku Test Bootstrap
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from resources.lib.ui import clean_settings


class TestCleanSettings(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        # Create mock canonical settings.xml
        self.canonical_xml = os.path.join(self.temp_dir.name, 'canonical_settings.xml')
        canonical_content = """<?xml version="1.0" encoding="utf-8"?>
<settings version="1">
    <section id="plugin.video.otaku.rpdev">
        <category id="general">
            <group id="1">
                <setting id="general.smartplay" type="boolean" default="true" />
                <setting id="general.dialog" type="integer" default="1" />
            </group>
        </category>
        <category id="debrid">
            <group id="1">
                <setting id="premiumize.token" type="string" default="" />
                <setting id="premiumize.enabled" type="boolean" default="false" />
            </group>
        </category>
    </section>
</settings>"""
        with open(self.canonical_xml, 'w', encoding='utf-8') as f:
            f.write(canonical_content)

        # Create mock profile settings.xml containing valid and obsolete settings
        self.profile_xml = os.path.join(self.temp_dir.name, 'profile_settings.xml')
        profile_content = """<?xml version="1.0" encoding="utf-8"?>
<settings version="2">
    <setting id="general.smartplay">true</setting>
    <setting id="premiumize.token">my_secret_token</setting>
    <setting id="obsolete.old_scraper_toggle">false</setting>
    <setting id="dangling.legacy_cache_key">12345</setting>
    <setting id="premiumize.enabled">true</setting>
</settings>"""
        with open(self.profile_xml, 'w', encoding='utf-8') as f:
            f.write(profile_content)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_active_setting_ids(self):
        """Extracts valid setting IDs correctly from canonical schema."""
        ids = clean_settings.get_active_setting_ids(self.canonical_xml)
        self.assertIn('general.smartplay', ids)
        self.assertIn('general.dialog', ids)
        self.assertIn('premiumize.token', ids)
        self.assertIn('premiumize.enabled', ids)
        self.assertNotIn('obsolete.old_scraper_toggle', ids)

    def test_clean_settings_pruning(self):
        """Prunes only orphaned setting tags while preserving user credentials."""
        count, removed = clean_settings.clean_settings(
            profile_settings_path=self.profile_xml,
            canonical_settings_path=self.canonical_xml
        )
        self.assertEqual(count, 2)
        self.assertIn('obsolete.old_scraper_toggle', removed)
        self.assertIn('dangling.legacy_cache_key', removed)

        # Verify pruned file contents
        tree = ET.parse(self.profile_xml)
        remaining_ids = [s.get('id') for s in tree.getroot()]
        self.assertEqual(len(remaining_ids), 3)
        self.assertIn('general.smartplay', remaining_ids)
        self.assertIn('premiumize.token', remaining_ids)
        self.assertIn('premiumize.enabled', remaining_ids)

        # Verify user token was preserved verbatim
        token_elem = tree.getroot().find("./setting[@id='premiumize.token']")
        self.assertEqual(token_elem.text, 'my_secret_token')

    def test_clean_settings_already_clean(self):
        """Returns (0, []) when profile settings.xml has no orphaned tags."""
        clean_settings.clean_settings(self.profile_xml, self.canonical_xml)
        # Second run should find 0 orphans
        count, removed = clean_settings.clean_settings(self.profile_xml, self.canonical_xml)
        self.assertEqual(count, 0)
        self.assertEqual(removed, [])


if __name__ == '__main__':
    unittest.main()