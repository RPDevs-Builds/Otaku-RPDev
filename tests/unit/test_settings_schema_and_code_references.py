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
        cls.service_addon_dir = os.path.join(cls.repo_root, 'service.otaku.rpdev')
        cls.subtitle_addon_dir = os.path.join(cls.repo_root, 'service.subtitles.otaku.rpdev')
        cls.settings_xml_path = os.path.join(cls.addon_dir, 'resources', 'settings.xml')
        cls.service_settings_xml_path = os.path.join(cls.service_addon_dir, 'resources', 'settings.xml')
        cls.subtitle_settings_xml_path = os.path.join(cls.subtitle_addon_dir, 'resources', 'settings.xml')

        for p in (cls.settings_xml_path, cls.service_settings_xml_path, cls.subtitle_settings_xml_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"settings.xml not found at: {p}")

        cls.tree = ET.parse(cls.settings_xml_path)
        cls.root = cls.tree.getroot()
        cls.service_tree = ET.parse(cls.service_settings_xml_path)
        cls.service_root = cls.service_tree.getroot()
        cls.subtitle_tree = ET.parse(cls.subtitle_settings_xml_path)
        cls.subtitle_root = cls.subtitle_tree.getroot()

        # Collect declared settings per add-on and union
        cls.plugin_declared_settings = {}
        for s in cls.root.findall('.//setting'):
            sid = s.get('id')
            if sid:
                cls.plugin_declared_settings[sid] = s

        cls.service_declared_settings = {}
        for s in cls.service_root.findall('.//setting'):
            sid = s.get('id')
            if sid:
                cls.service_declared_settings[sid] = s

        cls.subtitle_declared_settings = {}
        for s in cls.subtitle_root.findall('.//setting'):
            sid = s.get('id')
            if sid:
                cls.subtitle_declared_settings[sid] = s

        cls.declared_settings = {}
        cls.declared_settings.update(cls.plugin_declared_settings)
        cls.declared_settings.update(cls.service_declared_settings)
        cls.declared_settings.update(cls.subtitle_declared_settings)

        cls.strings_po_path = os.path.join(
            cls.addon_dir, 'resources', 'language', 'resource.language.en_gb', 'strings.po'
        )
        cls.service_strings_po_path = os.path.join(
            cls.service_addon_dir, 'resources', 'language', 'resource.language.en_gb', 'strings.po'
        )
        cls.subtitle_strings_po_path = os.path.join(
            cls.subtitle_addon_dir, 'resources', 'language', 'resource.language.en_gb', 'strings.po'
        )
        for p in (cls.strings_po_path, cls.service_strings_po_path, cls.subtitle_strings_po_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"strings.po not found at: {p}")

        cls.po_entries, cls.po_duplicates = cls._parse_strings_po_file(cls.strings_po_path)
        cls.service_po_entries, cls.service_po_duplicates = cls._parse_strings_po_file(cls.service_strings_po_path)
        cls.subtitle_po_entries, cls.subtitle_po_duplicates = cls._parse_strings_po_file(cls.subtitle_strings_po_path)

    @classmethod
    def _parse_strings_po_file(cls, po_path):
        """Parse strings.po extracting msgctxt, msgid, and checking for duplicates."""
        entries = {}
        duplicates = []
        current_ctxt = None
        in_msgid = False
        in_msgstr = False

        with open(po_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith('#'):
                    continue
                if line_str.startswith('msgctxt'):
                    m = re.match(r'msgctxt\s+"#(\d+)"', line_str)
                    if m:
                        current_ctxt = m.group(1)
                        if current_ctxt in entries:
                            duplicates.append(current_ctxt)
                        entries[current_ctxt] = {'msgid': '', 'msgstr': ''}
                    else:
                        current_ctxt = None
                    in_msgid = False
                    in_msgstr = False
                elif line_str.startswith('msgid') and current_ctxt:
                    m = re.match(r'msgid\s+"(.*)"', line_str)
                    if m:
                        entries[current_ctxt]['msgid'] = m.group(1)
                        in_msgid = True
                        in_msgstr = False
                elif line_str.startswith('msgstr') and current_ctxt:
                    m = re.match(r'msgstr\s+"(.*)"', line_str)
                    if m:
                        entries[current_ctxt]['msgstr'] = m.group(1)
                        in_msgstr = True
                        in_msgid = False
                elif line_str.startswith('"') and line_str.endswith('"') and current_ctxt:
                    inner = line_str[1:-1]
                    if in_msgid:
                        entries[current_ctxt]['msgid'] += inner
                    elif in_msgstr:
                        entries[current_ctxt]['msgstr'] += inner
        return entries, duplicates

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
        for label, root_el, expected_sec_id, min_cats, min_groups in (
            ('plugin', self.root, 'otaku', 10, 20),
            ('service', self.service_root, 'service.otaku.rpdev', 3, 5),
            ('subtitles', self.subtitle_root, 'service.subtitles.otaku.rpdev', 2, 4),
        ):
            sections = root_el.findall('section')
            self.assertGreaterEqual(len(sections), 1, f"{label} settings.xml must contain at least one <section>")

            for sec in sections:
                sec_id = sec.get('id')
                self.assertTrue(sec_id and sec_id.strip(), f"<section> is missing required 'id' attribute in {label}")
                self.assertEqual(sec_id, expected_sec_id, f"<section id='{sec_id}'> should be '{expected_sec_id}'")

            categories = root_el.findall('.//category')
            self.assertGreaterEqual(len(categories), min_cats, f"Expected at least {min_cats} categories in {label}")
            for cat in categories:
                cat_id = cat.get('id')
                self.assertTrue(cat_id and cat_id.strip(), f"<category> missing 'id' in {label}")
                self.assertIsNotNone(cat.get('label'), f"<category id='{cat_id}'> missing 'label' in {label}")

            groups = root_el.findall('.//group')
            self.assertGreaterEqual(len(groups), min_groups, f"Expected at least {min_groups} groups in {label}")
            for grp in groups:
                grp_id = grp.get('id')
                self.assertTrue(grp_id and grp_id.strip(), f"<group> missing 'id' in {label}")
                self.assertIsNotNone(grp.get('label'), f"<group id='{grp_id}'> missing 'label' in {label}")

        for sid, s in self.declared_settings.items():
            self.assertTrue(sid and sid.strip(), "Setting has empty 'id'")
            self.assertIsNotNone(s.get('label'), f"<setting id='{sid}'> missing required 'label' attribute")
            self.assertIsNotNone(s.get('type'), f"<setting id='{sid}'> missing required 'type' attribute")

    def test_no_duplicate_setting_ids(self):
        """Ensure no two settings or category IDs collide within or across plugin, service, and subtitle schemas."""
        plugin_ids = [s.get('id') for s in self.root.findall('.//setting') if s.get('id')]
        service_ids = [s.get('id') for s in self.service_root.findall('.//setting') if s.get('id')]
        subtitle_ids = [s.get('id') for s in self.subtitle_root.findall('.//setting') if s.get('id')]
        plugin_dups = {x for x in plugin_ids if plugin_ids.count(x) > 1}
        service_dups = {x for x in service_ids if service_ids.count(x) > 1}
        subtitle_dups = {x for x in subtitle_ids if subtitle_ids.count(x) > 1}
        self.assertEqual(len(plugin_dups), 0, f"Duplicate setting IDs in plugin settings.xml: {plugin_dups}")
        self.assertEqual(len(service_dups), 0, f"Duplicate setting IDs in service settings.xml: {service_dups}")
        self.assertEqual(len(subtitle_dups), 0, f"Duplicate setting IDs in subtitle settings.xml: {subtitle_dups}")

        p_set, s_set, sub_set = set(plugin_ids), set(service_ids), set(subtitle_ids)
        self.assertEqual(p_set & s_set, set(), f"Overlapping setting IDs across plugin & service: {p_set & s_set}")
        self.assertEqual(p_set & sub_set, set(), f"Overlapping setting IDs across plugin & subtitles: {p_set & sub_set}")
        self.assertEqual(s_set & sub_set, set(), f"Overlapping setting IDs across service & subtitles: {s_set & sub_set}")

        # Assert globally unique case-insensitive <category id> across all 3 add-ons
        seen_cats = {}
        cat_collisions = []
        for label, root_el in (('plugin', self.root), ('service', self.service_root), ('subtitles', self.subtitle_root)):
            for cat in root_el.findall('.//category'):
                cid = (cat.get('id') or '').strip()
                norm = cid.lower().replace('_', ' ')
                if norm in seen_cats:
                    cat_collisions.append((cid, label, seen_cats[norm]))
                else:
                    seen_cats[norm] = f"{label}:{cid}"
        self.assertEqual(cat_collisions, [], f"Category ID collisions across add-on schemas: {cat_collisions}")

    def test_service_setting_ids_and_migration_specs_parity(self):
        """Verify control.SERVICE_SETTING_IDS / SUBTITLE_SETTING_IDS and migration specs match their settings.xml files."""
        from resources.lib.ui import control
        from otaku_service import migration

        service_value_ids = {
            sid for sid, s in self.service_declared_settings.items()
            if s.get('type') != 'action'
        }
        self.assertEqual(
            set(control.SERVICE_SETTING_IDS),
            service_value_ids,
            "control.SERVICE_SETTING_IDS must match all non-action service settings",
        )
        self.assertEqual(
            set(migration.SERVICE_SETTING_SPECS.keys()),
            service_value_ids,
            "migration.SERVICE_SETTING_SPECS keys must match all non-action service settings",
        )
        mismatched_types = []
        for sid, (expected_type, _default) in migration.SERVICE_SETTING_SPECS.items():
            xml_type = self.service_declared_settings[sid].get('type')
            if xml_type != expected_type:
                mismatched_types.append((sid, expected_type, xml_type))
        self.assertEqual(
            mismatched_types, [],
            f"SERVICE_SETTING_SPECS types do not match service.otaku.rpdev/resources/settings.xml: {mismatched_types}",
        )

        subtitle_value_ids = {
            sid for sid, s in self.subtitle_declared_settings.items()
            if s.get('type') != 'action'
        }
        self.assertEqual(
            set(control.SUBTITLE_SETTING_IDS),
            subtitle_value_ids,
            "control.SUBTITLE_SETTING_IDS must match all non-action subtitle service settings",
        )
        self.assertEqual(
            set(migration.SUBTITLE_SETTING_SPECS.keys()),
            subtitle_value_ids,
            "migration.SUBTITLE_SETTING_SPECS keys must match all non-action subtitle service settings",
        )
        sub_mismatched = []
        for sid, (expected_type, _default) in migration.SUBTITLE_SETTING_SPECS.items():
            xml_type = self.subtitle_declared_settings[sid].get('type')
            if xml_type != expected_type:
                sub_mismatched.append((sid, expected_type, xml_type))
        self.assertEqual(
            sub_mismatched, [],
            f"SUBTITLE_SETTING_SPECS types do not match service.subtitles.otaku.rpdev/resources/settings.xml: {sub_mismatched}",
        )

    def test_all_setting_types_valid(self):
        """All declared setting types must conform to Kodi's supported type system."""
        invalid_types = []
        for sid, s in self.declared_settings.items():
            stype = s.get('type')
            if stype not in KODI_VALID_SETTING_TYPES:
                invalid_types.append((sid, stype))
        self.assertEqual(len(invalid_types), 0, f"Settings with invalid Kodi types: {invalid_types}")

    def test_setting_dependencies_reference_declared_settings(self):
        """All <dependency>, <condition>, and parent references must resolve within the SAME add-on's settings.xml."""
        broken_deps = []
        for label, local_map in (
            ('plugin', self.plugin_declared_settings),
            ('service', self.service_declared_settings),
            ('subtitles', self.subtitle_declared_settings),
        ):
            for sid, s in local_map.items():
                parent_id = s.get('parent')
                if parent_id and parent_id not in local_map:
                    broken_deps.append((label, sid, 'parent', parent_id))
                for dep in s.findall('.//dependency'):
                    target = dep.get('setting')
                    if target and target not in local_map:
                        broken_deps.append((label, sid, 'dependency', target))
                    for cond in dep.findall('.//condition'):
                        ctarget = cond.get('setting')
                        if ctarget and ctarget not in local_map:
                            broken_deps.append((label, sid, 'condition', ctarget))
        self.assertEqual(len(broken_deps), 0, f"Cross-addon or missing setting dependencies: {broken_deps}")

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

        for scan_root in (self.addon_dir, self.service_addon_dir, self.subtitle_addon_dir):
            for root_dir, _, files in os.walk(scan_root):
                for filename in files:
                    if not filename.endswith('.py'):
                        continue
                    filepath = os.path.join(root_dir, filename)
                    relpath = os.path.relpath(filepath, self.repo_root)

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

    def test_all_dotted_otaku_setting_literals_map_to_settings_xml(self):
        """Scan Python string literals for dotted Otaku setting prefixes (including tuples/lists like tools.py)."""
        prefixes = {
            'realdebrid', 'premiumize', 'alldebrid', 'debridlink', 'torbox', 'easydebrid', 'easynews',
            'anilist', 'mal', 'kitsu', 'simkl', 'trakt', 'subtitles', 'smartplay', 'interface',
            'general', 'provider', 'skipintro', 'skipoutro', 'animeskip', 'watchlist', 'db',
            'reuselanguageinvoker',
        }
        non_setting_allowlist = {
            'skipintro.start', 'skipintro.end', 'skipoutro.start', 'skipoutro.end',
            'subtitles.1', 'subtitles.2', 'subtitles.languages', 'subtitles.movie', 'subtitles.tv',
        }
        dotted_re = re.compile(r'^[a-z]+(?:\.[a-z0-9_]+)+$')
        bad = {}
        scanned_literals = 0

        for root_dir, _, files in os.walk(self.addon_dir):
            for filename in files:
                if not filename.endswith('.py'):
                    continue
                filepath = os.path.join(root_dir, filename)
                relpath = os.path.relpath(filepath, self.addon_dir)
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    parsed_ast = ast.parse(f.read(), filename=filepath)
                for node in ast.walk(parsed_ast):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        val = node.value
                        if '.' not in val or not dotted_re.match(val):
                            continue
                        pref = val.split('.', 1)[0]
                        if pref not in prefixes:
                            continue
                        if val.endswith(('.com', '.net', '.org', '.io', '.tv', '.pw', '.py', '.xml', '.json', '.db', '.png', '.ass', '.srt', '.vtt', '.xz', '.gz')):
                            continue
                        if val in non_setting_allowlist:
                            continue
                        scanned_literals += 1
                        if val not in self.declared_settings:
                            bad.setdefault(val, []).append((relpath, getattr(node, 'lineno', 0)))

        self.assertGreater(scanned_literals, 300)
        self.assertEqual(
            bad,
            {},
            f"Undeclared dotted setting literals found (C-36 regression):\n{bad}",
        )

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
        Verify that all 10 plugin categories + 3 service categories declare a valid, non-empty
        help attribute pointing to their respective strings.po.
        """
        missing_category_help = []
        invalid_category_help = []

        for label, root_el, po_map, expected_count in (
            ('plugin', self.root, self.po_entries, 10),
            ('service', self.service_root, self.service_po_entries, 3),
            ('subtitles', self.subtitle_root, self.subtitle_po_entries, 2),
        ):
            categories = root_el.findall('.//category')
            self.assertEqual(len(categories), expected_count, f"Expected exactly {expected_count} categories in {label} settings.xml")
            for cat in categories:
                cat_id = f"{label}:{cat.get('id')}"
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
                if help_val not in po_map:
                    invalid_category_help.append((cat_id, help_val, "Help ID missing from strings.po"))
                    continue
                msg = po_map[help_val]['msgid']
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
        Verify that 100% of user-visible settings (levels 0-3) across plugin and service add-ons
        declare a valid non-empty help attribute pointing to their own strings.po, while level 4
        internal settings remain without UI tooltips.
        """
        user_visible_missing = []
        user_visible_invalid = []
        level4_with_help = []
        counts = {'plugin': [0, 0], 'service': [0, 0], 'subtitles': [0, 0]}

        for label, declared_map, po_map in (
            ('plugin', self.plugin_declared_settings, self.po_entries),
            ('service', self.service_declared_settings, self.service_po_entries),
            ('subtitles', self.subtitle_declared_settings, self.subtitle_po_entries),
        ):
            for sid, s in declared_map.items():
                lvl_elem = s.find('level')
                level = int(lvl_elem.text.strip()) if (lvl_elem is not None and lvl_elem.text and lvl_elem.text.strip().isdigit()) else 0
                help_val = s.get('help')

                if level in (0, 1, 2, 3):
                    counts[label][0] += 1
                    if not help_val or not help_val.strip():
                        user_visible_missing.append((f"{label}:{sid}", level))
                        continue
                    if not help_val.isdigit():
                        user_visible_invalid.append((f"{label}:{sid}", help_val, "Non-numeric help ID"))
                        continue
                    hid_int = int(help_val)
                    if not (30000 <= hid_int <= 30999):
                        user_visible_invalid.append((f"{label}:{sid}", help_val, "Help ID outside #30000-#30999 range"))
                        continue
                    if help_val not in po_map:
                        user_visible_invalid.append((f"{label}:{sid}", help_val, "Help ID not defined in strings.po"))
                        continue
                    msg = po_map[help_val]['msgid']
                    if len(msg) < 25:
                        user_visible_invalid.append((f"{label}:{sid}", help_val, f"Tooltip text too short ({len(msg)} chars < 25)"))
                elif level == 4:
                    counts[label][1] += 1
                    if help_val and help_val.strip():
                        level4_with_help.append((f"{label}:{sid}", help_val))

        self.assertEqual(counts['plugin'], [312, 119], f"Expected plugin [312 visible, 119 level-4], found {counts['plugin']}")
        self.assertEqual(counts['service'], [52, 9], f"Expected service [52 visible, 9 level-4], found {counts['service']}")
        self.assertEqual(counts['subtitles'], [28, 1], f"Expected subtitles [28 visible, 1 level-4], found {counts['subtitles']}")
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
        Verify both plugin and service strings.po files have zero duplicate msgctxt IDs,
        all IDs strictly within #30000-#30999, and non-empty msgid.
        """
        for label, po_map, po_dups in (
            ('plugin', self.po_entries, self.po_duplicates),
            ('service', self.service_po_entries, self.service_po_duplicates),
            ('subtitles', self.subtitle_po_entries, self.subtitle_po_duplicates),
        ):
            self.assertEqual(
                len(po_dups), 0,
                f"Found duplicate msgctxt string IDs in {label} strings.po: {po_dups}"
            )
            out_of_range = []
            empty_msgid = []
            for id_str, entry in po_map.items():
                id_int = int(id_str)
                if not (30000 <= id_int <= 30999):
                    out_of_range.append(id_int)
                if not entry['msgid'] or not entry['msgid'].strip():
                    empty_msgid.append(id_str)
            self.assertEqual(len(out_of_range), 0, f"{label} string IDs outside #30000-#30999: {out_of_range}")
            self.assertEqual(len(empty_msgid), 0, f"{label} strings with empty msgid: {empty_msgid}")

    def test_all_settings_xml_labels_and_options_resolve_in_po(self):
        """
        Verify that all label, help, and option label references in both plugin and service settings.xml
        resolve to valid entries in their own strings.po (ignoring Kodi built-in strings < 30000).
        """
        missing_resolutions = []
        out_of_bound_references = []

        for label, root_el, po_map in (
            ('plugin', self.root, self.po_entries),
            ('service', self.service_root, self.service_po_entries),
            ('subtitles', self.subtitle_root, self.subtitle_po_entries),
        ):
            def check_ref(elem_tag, elem_id, attr_name, val_str, _label=label, _po=po_map):
                if not val_str or not val_str.isdigit():
                    return
                val = int(val_str)
                if val < 30000:
                    return
                if val > 30999:
                    out_of_bound_references.append((_label, elem_tag, elem_id, attr_name, val))
                    return
                if val_str not in _po:
                    missing_resolutions.append((_label, elem_tag, elem_id, attr_name, val_str))

            for sec in root_el.findall('.//section'):
                check_ref('section', sec.get('id'), 'label', sec.get('label'))
            for cat in root_el.findall('.//category'):
                check_ref('category', cat.get('id'), 'label', cat.get('label'))
                check_ref('category', cat.get('id'), 'help', cat.get('help'))
            for grp in root_el.findall('.//group'):
                check_ref('group', grp.get('id'), 'label', grp.get('label'))
            for s in root_el.findall('.//setting'):
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
        Verify that all strings in plugin and service strings.po used as help tooltips have valid,
        balanced BBCode tags.
        """
        bbcode_errors = []
        for label, root_el, po_map in (
            ('plugin', self.root, self.po_entries),
            ('service', self.service_root, self.service_po_entries),
            ('subtitles', self.subtitle_root, self.subtitle_po_entries),
        ):
            help_ids = set()
            for cat in root_el.findall('.//category'):
                h = cat.get('help')
                if h and h.isdigit():
                    help_ids.add(h)
            for s in root_el.findall('.//setting'):
                h = s.get('help')
                if h and h.isdigit():
                    help_ids.add(h)

            for hid in sorted(help_ids):
                entry = po_map.get(hid)
                if not entry:
                    continue
                msg = entry['msgid']
                err = self._validate_bbcode(msg)
                if err:
                    bbcode_errors.append((label, hid, err, msg))

        self.assertEqual(
            len(bbcode_errors), 0,
            "BBCode formatting errors found in help tooltips:\n" +
            "\n".join([f"  • [{lbl}] #{hid}: {err} | '{msg}'" for lbl, hid, err, msg in bbcode_errors])
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
        Verify that clean_settings.get_active_setting_ids() returns all declared settings
        from both canonical settings.xml files and that legacy level 4 compatibility settings are preserved.
        """
        from resources.lib.ui import clean_settings
        plugin_active_ids = clean_settings.get_active_setting_ids(self.settings_xml_path)
        service_active_ids = clean_settings.get_active_setting_ids(self.service_settings_xml_path)
        subtitle_active_ids = clean_settings.get_active_setting_ids(self.subtitle_settings_xml_path)
        self.assertEqual(len(plugin_active_ids), 431, f"Expected 431 plugin active setting IDs, got {len(plugin_active_ids)}")
        self.assertEqual(len(service_active_ids), 61, f"Expected 61 service active setting IDs, got {len(service_active_ids)}")
        self.assertEqual(len(subtitle_active_ids), 29, f"Expected 29 subtitle active setting IDs, got {len(subtitle_active_ids)}")
        self.assertEqual(plugin_active_ids, set(self.plugin_declared_settings.keys()))
        self.assertEqual(service_active_ids, set(self.service_declared_settings.keys()))
        self.assertEqual(subtitle_active_ids, set(self.subtitle_declared_settings.keys()))

        legacy_compatibility_keys = [
            'regex.question',
            'interface.show_last_watched',
            'interface.show_watch_history',
            'resolve_season',
        ]
        for key in legacy_compatibility_keys:
            self.assertIn(
                key, plugin_active_ids,
                f"Legacy level 4 key '{key}' must remain in plugin active_ids to prevent clean_settings pruning"
            )


if __name__ == '__main__':
    unittest.main()
