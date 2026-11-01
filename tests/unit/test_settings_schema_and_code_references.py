# -*- coding: utf-8 -*-
"""
test_settings_schema_and_code_references.py - Static Schema & AST Code Reference Integrity Tests
================================================================================================
Guarantees that resources/settings.xml satisfies Kodi C++ CAddonSettings deserializer
requirements and that all settings accessed in Python code exist in the schema.
Prevents mock-bypassing and ensures runtime settings integrity.
"""

import ast
import os
import unittest
import xml.etree.ElementTree as ET


KODI_VALID_SETTING_TYPES = {
    'boolean',
    'string',
    'integer',
    'number',
    'action',
    'select',
    'slider',
    'folder',
    'file',
    'path',
    'ipaddress',
    'date',
    'time',
    'addon',
    'list[string]',
    'list[String]',
}


class TestSettingsSchemaAndCodeReferences(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cls.addon_dir = os.path.join(cls.repo_root, 'plugin.video.otaku.rpdev')
        cls.settings_xml_path = os.path.join(cls.addon_dir, 'resources', 'settings.xml')

        if not os.path.exists(cls.settings_xml_path):
            raise FileNotFoundError(f"settings.xml not found at: {cls.settings_xml_path}")

        cls.tree = ET.parse(cls.settings_xml_path)
        cls.root = cls.tree.getroot()

        # Collect all declared settings
        cls.declared_settings = {}
        for s in cls.root.findall('.//setting'):
            sid = s.get('id')
            if sid:
                cls.declared_settings[sid] = s

    def test_section_structure_and_mandatory_attributes(self):
        """Kodi CSettingSection::Deserialize strictly enforces non-empty id on section, category, group, setting."""
        sections = self.root.findall('section')
        self.assertGreaterEqual(len(sections), 1, "settings.xml must contain at least one <section>")

        for sec in sections:
            sec_id = sec.get('id')
            self.assertTrue(sec_id and sec_id.strip(), f"<section> is missing required 'id' attribute in {self.settings_xml_path}")
            self.assertEqual(sec_id, 'otaku', f"<section id='{sec_id}'> should be 'otaku'")

        categories = self.root.findall('.//category')
        self.assertGreaterEqual(len(categories), 12, "Expected at least 12 categories")
        for cat in categories:
            cat_id = cat.get('id')
            self.assertTrue(cat_id and cat_id.strip(), f"<category> missing 'id': {ET.tostring(cat, encoding='unicode')[:100]}")
            self.assertIsNotNone(cat.get('label'), f"<category id='{cat_id}'> is missing required 'label' attribute")

        groups = self.root.findall('.//group')
        self.assertGreaterEqual(len(groups), 20, "Expected at least 20 groups")
        for grp in groups:
            grp_id = grp.get('id')
            self.assertTrue(grp_id and grp_id.strip(), f"<group> missing 'id': {ET.tostring(grp, encoding='unicode')[:100]}")
            self.assertIsNotNone(grp.get('label'), f"<group id='{grp_id}'> is missing required 'label' attribute")

        for sid, s in self.declared_settings.items():
            self.assertTrue(sid and sid.strip(), f"Setting has empty 'id'")
            self.assertIsNotNone(s.get('label'), f"<setting id='{sid}'> missing required 'label' attribute")
            self.assertIsNotNone(s.get('type'), f"<setting id='{sid}'> missing required 'type' attribute")

    def test_no_duplicate_setting_ids(self):
        """Ensure no two settings share the same id, which would corrupt Kodi's internal settings map."""
        all_ids = [s.get('id') for s in self.root.findall('.//setting') if s.get('id')]
        duplicates = set([x for x in all_ids if all_ids.count(x) > 1])
        self.assertEqual(len(duplicates), 0, f"Duplicate setting IDs found in settings.xml: {duplicates}")

    def test_all_setting_types_valid(self):
        """All declared setting types must conform to Kodi's supported type system."""
        invalid_types = []
        for sid, s in self.declared_settings.items():
            stype = s.get('type')
            if stype not in KODI_VALID_SETTING_TYPES:
                invalid_types.append((sid, stype))
        self.assertEqual(len(invalid_types), 0, f"Settings with invalid Kodi types: {invalid_types}")

    def test_setting_dependencies_reference_declared_settings(self):
        """All <dependency> rules in settings.xml must reference existing setting IDs."""
        broken_deps = []
        for sid, s in self.declared_settings.items():
            for dep in s.findall('.//dependency'):
                target = dep.get('setting')
                if target and target not in self.declared_settings:
                    broken_deps.append((sid, target))
        self.assertEqual(len(broken_deps), 0, f"Setting dependencies reference non-existent settings: {broken_deps}")

    def test_static_code_settings_map_to_settings_xml(self):
        """
        Scan all Python files via AST and guarantee 100% of static setting keys passed
        to control.getSetting(), setSetting(), getInt(), getBool(), getSettingDefault()
        are declared in resources/settings.xml.
        """
        target_methods = {'getSetting', 'setSetting', 'getInt', 'getBool', 'getSettingDefault'}
        static_keys = {}  # key -> list of (file, line_no)

        for root_dir, _, files in os.walk(self.addon_dir):
            for filename in files:
                if not filename.endswith('.py'):
                    continue
                filepath = os.path.join(root_dir, filename)
                relpath = os.path.relpath(filepath, self.addon_dir)

                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    try:
                        parsed_ast = ast.parse(f.read(), filename=filepath)
                    except Exception as e:
                        self.fail(f"AST parse failure on {relpath}: {e}")

                for node in ast.walk(parsed_ast):
                    if not isinstance(node, ast.Call):
                        continue

                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr in target_methods:
                        if node.args:
                            arg0 = node.args[0]
                            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                                key = arg0.value
                                static_keys.setdefault(key, []).append((relpath, getattr(node, 'lineno', 0)))

        # Assert every discovered static key is declared in settings.xml
        unmapped = {}
        for key, occurrences in static_keys.items():
            if key not in self.declared_settings:
                unmapped[key] = occurrences

        self.assertEqual(
            len(unmapped), 0,
            f"Found {len(unmapped)} settings referenced in Python code but MISSING from settings.xml:\n" +
            "\n".join([f"  • '{k}' referenced at: {locs}" for k, locs in unmapped.items()])
        )
        self.assertGreater(len(static_keys), 200, "Sanity check: expected at least 200 static settings scanned")

    def test_dynamic_code_settings_map_to_registered_providers(self):
        """Verify dynamic setting patterns (e.g. provider.{name}) match known provider registries."""
        from resources.lib.pages import _TORRENT_MODULES, _EMBED_MODULES, _HOSTER_MODULES

        # Torrent providers must have matching provider.<name> setting in settings.xml
        for name in _TORRENT_MODULES.keys():
            setting_id = f"provider.{name}"
            self.assertIn(
                setting_id,
                self.declared_settings,
                f"Torrent provider '{name}' missing corresponding setting '{setting_id}' in settings.xml"
            )

        # Embed providers must have matching provider.<name> setting in settings.xml
        for row in _EMBED_MODULES:
            name = row[0]
            setting_id = f"provider.{name}"
            self.assertIn(
                setting_id,
                self.declared_settings,
                f"Embed provider '{name}' missing corresponding setting '{setting_id}' in settings.xml"
            )

        # Hoster providers must have matching provider.<name> setting in settings.xml
        for name in _HOSTER_MODULES.keys():
            setting_id = f"provider.{name}"
            self.assertIn(
                setting_id,
                self.declared_settings,
                f"Hoster provider '{name}' missing corresponding setting '{setting_id}' in settings.xml"
            )


if __name__ == '__main__':
    unittest.main()
