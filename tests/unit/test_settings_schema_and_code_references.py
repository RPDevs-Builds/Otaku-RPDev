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
import re
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

        cls.strings_po_path = os.path.join(
            cls.addon_dir, 'resources', 'language', 'resource.language.en_gb', 'strings.po'
        )
        if not os.path.exists(cls.strings_po_path):
            raise FileNotFoundError(f"strings.po not found at: {cls.strings_po_path}")

        cls.po_entries = {}
        cls.po_duplicates = []
        cls._parse_strings_po()

    @classmethod
    def _parse_strings_po(cls):
        """Parse strings.po extracting msgctxt, msgid, and checking for duplicates."""
        current_ctxt = None
        in_msgid = False
        in_msgstr = False

        with open(cls.strings_po_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith('#'):
                    continue
                if line_str.startswith('msgctxt'):
                    m = re.match(r'msgctxt\s+"#(\d+)"', line_str)
                    if m:
                        current_ctxt = m.group(1)
                        if current_ctxt in cls.po_entries:
                            cls.po_duplicates.append(current_ctxt)
                        cls.po_entries[current_ctxt] = {'msgid': '', 'msgstr': ''}
                    else:
                        current_ctxt = None
                    in_msgid = False
                    in_msgstr = False
                elif line_str.startswith('msgid') and current_ctxt:
                    m = re.match(r'msgid\s+"(.*)"', line_str)
                    if m:
                        cls.po_entries[current_ctxt]['msgid'] = m.group(1)
                        in_msgid = True
                        in_msgstr = False
                elif line_str.startswith('msgstr') and current_ctxt:
                    m = re.match(r'msgstr\s+"(.*)"', line_str)
                    if m:
                        cls.po_entries[current_ctxt]['msgstr'] = m.group(1)
                        in_msgstr = True
                        in_msgid = False
                elif line_str.startswith('"') and line_str.endswith('"') and current_ctxt:
                    inner = line_str[1:-1]
                    if in_msgid:
                        cls.po_entries[current_ctxt]['msgid'] += inner
                    elif in_msgstr:
                        cls.po_entries[current_ctxt]['msgstr'] += inner

    @staticmethod
    def _validate_bbcode(text):
        """Validate balanced Kodi BBCode tags ([B], [I], [COLOR <color>], [UPPERCASE], [LOWERCASE])."""
        paired_tags = {'B', 'I', 'COLOR', 'UPPERCASE', 'LOWERCASE'}
        self_closing = {'CR'}
        stack = []
        tokens = re.finditer(r'\[(/?[A-Za-z]+)(?:[ =][^\]]*)?\]', text)
        for m in tokens:
            full_tag = m.group(0)
            tag_name = m.group(1).upper()
            if tag_name in self_closing:
                continue
            if tag_name.startswith('/'):
                closetag = tag_name[1:]
                if closetag in paired_tags:
                    if not stack:
                        return f'Unexpected closing tag {full_tag}'
                    last_open = stack.pop()
                    if last_open != closetag:
                        return f'Mismatched tag: expected [/{last_open}], got {full_tag}'
            elif tag_name in paired_tags:
                stack.append(tag_name)
        if stack:
            return f'Unclosed BBCode tags: {stack}'
        return None

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
        target_methods = {
            'getSetting', 'setSetting',
            'getInt', 'setInt',
            'getBool', 'setBool',
            'getStr', 'setStr',
            'getNumber', 'setNumber',
            'getString', 'setString',
            'getStringList', 'setStringList',
            'getBoolList', 'setBoolList',
            'getIntList', 'setIntList',
            'getNumberList', 'setNumberList',
            'getSettingDefault'
        }
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

        # Active embed skip-time prefixes must have all 4 skip settings declared
        from resources.lib.pages import EMBED_SKIP_PREFIXES
        self.assertGreater(len(EMBED_SKIP_PREFIXES), 0, "Expected at least one active embed skip prefix")
        for prefix in EMBED_SKIP_PREFIXES:
            for key in ('skipintro.start', 'skipintro.end', 'skipoutro.start', 'skipoutro.end'):
                sid = f"{prefix}.{key}"
                self.assertIn(
                    sid,
                    self.declared_settings,
                    f"Embed skip setting '{sid}' missing from settings.xml"
                )

        # Debrid services audited in Tools Diagnostics must have enabled and token settings
        debrid_services = ['realdebrid', 'torbox', 'premiumize', 'alldebrid', 'debridlink', 'easydebrid']
        for d in debrid_services:
            self.assertIn(f"{d}.enabled", self.declared_settings, f"Debrid setting '{d}.enabled' missing from settings.xml")
            self.assertIn(f"{d}.token", self.declared_settings, f"Debrid setting '{d}.token' missing from settings.xml")
        self.assertIn("provider.easynews", self.declared_settings)

        # Watchlist services must have sort, order, and token settings
        for wf in ['mal', 'anilist', 'kitsu', 'simkl']:
            self.assertIn(f"{wf}.sort", self.declared_settings, f"Watchlist setting '{wf}.sort' missing from settings.xml")
            self.assertIn(f"{wf}.order", self.declared_settings, f"Watchlist setting '{wf}.order' missing from settings.xml")

    def test_all_categories_have_tooltips(self):
        """
        Verify that all 12 categories in settings.xml declare a valid, non-empty
        help attribute pointing to a string ID in strings.po (Milestone 1 requirement).
        """
        categories = self.root.findall('.//category')
        self.assertEqual(len(categories), 12, "Expected exactly 12 categories in settings.xml")

        missing_category_help = []
        invalid_category_help = []

        for cat in categories:
            cat_id = cat.get('id')
            help_val = cat.get('help')
            if not help_val or not help_val.strip():
                missing_category_help.append(cat_id)
                continue

            if not help_val.isdigit():
                invalid_category_help.append((cat_id, help_val, "Non-numeric help ID"))
                continue

            hid_int = int(help_val)
            if not (30000 <= hid_int <= 30999):
                invalid_category_help.append((cat_id, help_val, "Help ID outside #30000-#30999 range"))
                continue

            if help_val not in self.po_entries:
                invalid_category_help.append((cat_id, help_val, "Help ID missing from strings.po"))
                continue

            msg = self.po_entries[help_val]['msgid']
            if len(msg) < 25:
                invalid_category_help.append((cat_id, help_val, f"Category summary too short ({len(msg)} chars < 25)"))

        self.assertEqual(
            len(missing_category_help), 0,
            f"Categories missing required 'help' tooltip attribute: {missing_category_help}"
        )
        self.assertEqual(
            len(invalid_category_help), 0,
            f"Categories with invalid 'help' tooltips: {invalid_category_help}"
        )

    def test_user_visible_settings_have_help_tooltips(self):
        """
        Verify that 100% of user-visible settings (levels 0-3, 340 total) declare a valid
        non-empty help attribute pointing to strings.po, while level 4 internal settings
        remain without UI tooltips (Milestone 1 requirement).
        """
        user_visible_missing = []
        user_visible_invalid = []
        level4_with_help = []
        user_visible_count = 0
        level4_count = 0

        for sid, s in self.declared_settings.items():
            lvl_elem = s.find('level')
            level = int(lvl_elem.text.strip()) if (lvl_elem is not None and lvl_elem.text and lvl_elem.text.strip().isdigit()) else 0
            help_val = s.get('help')

            if level in (0, 1, 2, 3):
                user_visible_count += 1
                if not help_val or not help_val.strip():
                    user_visible_missing.append((sid, level))
                    continue

                if not help_val.isdigit():
                    user_visible_invalid.append((sid, help_val, "Non-numeric help ID"))
                    continue

                hid_int = int(help_val)
                if not (30000 <= hid_int <= 30999):
                    user_visible_invalid.append((sid, help_val, "Help ID outside #30000-#30999 range"))
                    continue

                if help_val not in self.po_entries:
                    user_visible_invalid.append((sid, help_val, "Help ID not defined in strings.po"))
                    continue

                msg = self.po_entries[help_val]['msgid']
                if len(msg) < 25:
                    user_visible_invalid.append((sid, help_val, f"Tooltip text too short ({len(msg)} chars < 25)"))
            elif level == 4:
                level4_count += 1
                if help_val and help_val.strip():
                    level4_with_help.append((sid, help_val))

        self.assertEqual(user_visible_count, 344, f"Expected 344 user-visible settings (level 0-3), found {user_visible_count}")
        self.assertEqual(level4_count, 127, f"Expected 127 hidden level 4 settings, found {level4_count}")
        self.assertEqual(
            len(user_visible_missing), 0,
            f"Found {len(user_visible_missing)} user-visible (level 0-3) settings MISSING help tooltips:\n" +
            "\n".join([f"  • {sid} (level {lvl})" for sid, lvl in user_visible_missing[:30]])
        )
        self.assertEqual(
            len(user_visible_invalid), 0,
            f"Settings with invalid help tooltips: {user_visible_invalid[:30]}"
        )
        self.assertEqual(
            len(level4_with_help), 0,
            f"Hidden internal level 4 settings should not have UI tooltips: {level4_with_help}"
        )

    def test_strings_po_schema_and_boundary_integrity(self):
        """
        Verify strings.po has zero duplicate msgctxt IDs, all IDs strictly within #30000-#30999,
        no strings in forbidden ranges, and all defined entries have non-empty msgid.
        """
        self.assertEqual(
            len(self.po_duplicates), 0,
            f"Found duplicate msgctxt string IDs in strings.po: {self.po_duplicates}"
        )

        out_of_range = []
        forbidden_core = []      # < 30000 (Kodi core)
        forbidden_skins = []     # 31000-31999 (Skins)
        forbidden_scripts = []   # 32000-32999 (Scripts)
        forbidden_common = []    # 33000-33999 (Common addon strings)
        forbidden_high = []      # >= 34000
        empty_msgid = []

        for id_str, entry in self.po_entries.items():
            id_int = int(id_str)
            if not (30000 <= id_int <= 30999):
                out_of_range.append(id_int)
                if id_int < 30000:
                    forbidden_core.append(id_int)
                elif 31000 <= id_int <= 31999:
                    forbidden_skins.append(id_int)
                elif 32000 <= id_int <= 32999:
                    forbidden_scripts.append(id_int)
                elif 33000 <= id_int <= 33999:
                    forbidden_common.append(id_int)
                else:
                    forbidden_high.append(id_int)

            if not entry['msgid'] or not entry['msgid'].strip():
                empty_msgid.append(id_str)

        self.assertEqual(len(out_of_range), 0, f"String IDs outside #30000-#30999: {out_of_range}")
        self.assertEqual(len(forbidden_core), 0, f"String IDs in forbidden Kodi core range (<30000): {forbidden_core}")
        self.assertEqual(len(forbidden_skins), 0, f"String IDs in forbidden Skin range (31000-31999): {forbidden_skins}")
        self.assertEqual(len(forbidden_scripts), 0, f"String IDs in forbidden Script range (32000-32999): {forbidden_scripts}")
        self.assertEqual(len(forbidden_common), 0, f"String IDs in forbidden Common range (33000-33999): {forbidden_common}")
        self.assertEqual(len(forbidden_high), 0, f"String IDs in forbidden high range (>=34000): {forbidden_high}")
        self.assertEqual(len(empty_msgid), 0, f"Strings with empty msgid in strings.po: {empty_msgid}")

    def test_all_settings_xml_labels_and_options_resolve_in_po(self):
        """
        Verify that all label, help, and option label references in settings.xml
        resolve to valid entries in strings.po (ignoring Kodi built-in strings < 30000).
        """
        missing_resolutions = []
        out_of_bound_references = []

        def check_ref(elem_tag, elem_id, attr_name, val_str):
            if not val_str or not val_str.isdigit():
                return
            val = int(val_str)
            if val < 30000:
                # Built-in Kodi core string (e.g. 20020, 20445, 21475)
                return
            if val > 30999:
                out_of_bound_references.append((elem_tag, elem_id, attr_name, val))
                return
            if val_str not in self.po_entries:
                missing_resolutions.append((elem_tag, elem_id, attr_name, val_str))

        for sec in self.root.findall('.//section'):
            check_ref('section', sec.get('id'), 'label', sec.get('label'))

        for cat in self.root.findall('.//category'):
            check_ref('category', cat.get('id'), 'label', cat.get('label'))
            check_ref('category', cat.get('id'), 'help', cat.get('help'))

        for grp in self.root.findall('.//group'):
            check_ref('group', grp.get('id'), 'label', grp.get('label'))

        for s in self.root.findall('.//setting'):
            sid = s.get('id')
            check_ref('setting', sid, 'label', s.get('label'))
            check_ref('setting', sid, 'help', s.get('help'))
            for opt in s.findall('.//option'):
                check_ref('option', sid, 'label', opt.get('label'))

        self.assertEqual(
            len(out_of_bound_references), 0,
            f"settings.xml references string IDs outside #30000-#30999: {out_of_bound_references}"
        )
        self.assertEqual(
            len(missing_resolutions), 0,
            f"settings.xml references string IDs missing from strings.po: {missing_resolutions}"
        )

    def test_help_strings_bbcode_formatting(self):
        """
        Verify that all strings in strings.po used as help tooltips have valid,
        balanced BBCode tags (e.g. [B]...[/B], [COLOR ...][/COLOR], [I]...[/I]).
        """
        bbcode_errors = []
        help_ids = set()
        for cat in self.root.findall('.//category'):
            h = cat.get('help')
            if h and h.isdigit():
                help_ids.add(h)
        for s in self.root.findall('.//setting'):
            h = s.get('help')
            if h and h.isdigit():
                help_ids.add(h)

        for hid in sorted(help_ids):
            entry = self.po_entries.get(hid)
            if not entry:
                continue
            msg = entry['msgid']
            err = self._validate_bbcode(msg)
            if err:
                bbcode_errors.append((hid, err, msg))

        self.assertEqual(
            len(bbcode_errors), 0,
            f"BBCode formatting errors found in help tooltips:\n" +
            "\n".join([f"  • #{hid}: {err} | '{msg}'" for hid, err, msg in bbcode_errors])
        )

    def test_shared_help_ids_decoupled(self):
        """
        Verify that previously overloaded shared help IDs are properly decoupled:
        - smartplay.stillwatching_count keeps #30570, while smartplay.stillwatching_timeout uses #30971
        - menu customization *.submenu.action and *.genres.action use dedicated #30972 and #30973
        """
        timeout_setting = self.declared_settings.get('smartplay.stillwatching_timeout')
        if timeout_setting is not None and timeout_setting.get('help'):
            self.assertEqual(
                timeout_setting.get('help'), '30971',
                f"smartplay.stillwatching_timeout should use dedicated help ID 30971, got {timeout_setting.get('help')}"
            )

        submenu_actions = [s for sid, s in self.declared_settings.items() if sid.endswith('.submenu.action')]
        for s in submenu_actions:
            if s.get('help'):
                self.assertEqual(
                    s.get('help'), '30972',
                    f"Setting {s.get('id')} should use dedicated help ID 30972, got {s.get('help')}"
                )

        genres_actions = [s for sid, s in self.declared_settings.items() if sid.endswith('.genres.action')]
        for s in genres_actions:
            if s.get('help'):
                self.assertEqual(
                    s.get('help'), '30973',
                    f"Setting {s.get('id')} should use dedicated help ID 30973, got {s.get('help')}"
                )

    def test_clean_settings_compatibility_with_real_schema(self):
        """
        Verify that clean_settings.get_active_setting_ids() returns all 471 declared settings
        from the canonical settings.xml and that legacy level 4 compatibility settings are preserved.
        """
        from resources.lib.ui import clean_settings
        active_ids = clean_settings.get_active_setting_ids(self.settings_xml_path)
        self.assertEqual(len(active_ids), 471, f"Expected 471 active setting IDs, got {len(active_ids)}")
        self.assertEqual(active_ids, set(self.declared_settings.keys()))

        legacy_compatibility_keys = [
            'regex.question',
            'interface.show_last_watched',
            'interface.show_watch_history',
            'resolve_season',
        ]
        for key in legacy_compatibility_keys:
            self.assertIn(
                key, active_ids,
                f"Legacy level 4 key '{key}' must remain in active_ids to prevent clean_settings pruning"
            )


if __name__ == '__main__':
    unittest.main()
