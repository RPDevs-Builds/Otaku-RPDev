"""
Lint test ensuring zero AST syntax errors, zero bare excepts, and zero raw pickle.loads calls outside database.py.
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

import ast
import glob
import os
import re
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_DIR = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
CONTEXT_ADDON_DIR = os.path.join(REPO_ROOT, 'context.otaku.rpdev')
SKIN_XML_DIR = os.path.join(ADDON_DIR, 'resources', 'skins', 'Default', '1080i')


class TestASTIntegrity(unittest.TestCase):

    def test_all_python_files_pass_ast_parse(self):
        """Every Python file in the add-on must compile cleanly with ast.parse."""
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)
        self.assertGreater(len(py_files), 50, "Should scan at least 50 Python files")

        for f in py_files:
            if '__pycache__' in f:
                continue
            with open(f, 'rb') as fp:
                try:
                    ast.parse(fp.read(), filename=f)
                except SyntaxError as e:
                    self.fail(f"SyntaxError in {f}: {e}")

    def test_zero_bare_excepts(self):
        """Zero bare 'except:' blocks are permitted across the codebase."""
        bare_excepts = []
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)

        for f in py_files:
            if '__pycache__' in f:
                continue
            with open(f, 'rb') as fp:
                tree = ast.parse(fp.read(), filename=f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ExceptHandler) and node.type is None:
                        bare_excepts.append((f, node.lineno))

        self.assertEqual(bare_excepts, [], f"Found bare except blocks: {bare_excepts}")

    def test_zero_raw_pickle_loads_outside_database(self):
        """raw pickle.loads() is forbidden outside database.py to prevent RCE."""
        forbidden_pickle_loads = []
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)

        for f in py_files:
            if '__pycache__' in f or f.endswith('database.py'):
                continue
            with open(f, 'rb') as fp:
                tree = ast.parse(fp.read(), filename=f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        if isinstance(func, ast.Attribute) and func.attr == 'loads':
                            if isinstance(func.value, ast.Name) and func.value.id == 'pickle':
                                forbidden_pickle_loads.append((f, node.lineno))

        self.assertEqual(forbidden_pickle_loads, [], f"Raw pickle.loads calls found: {forbidden_pickle_loads}")

    def test_zero_unauthorized_pickle_imports(self):
        """Zero modules outside database.py are permitted to import pickle."""
        forbidden_pickle_imports = []
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)

        for f in py_files:
            if '__pycache__' in f or f.endswith('database.py'):
                continue
            with open(f, 'rb') as fp:
                tree = ast.parse(fp.read(), filename=f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == 'pickle':
                                forbidden_pickle_imports.append((f, node.lineno))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module == 'pickle':
                            forbidden_pickle_imports.append((f, node.lineno))

        self.assertEqual(forbidden_pickle_imports, [], f"Unauthorized pickle imports found: {forbidden_pickle_imports}")

    def test_all_threads_marked_daemon(self):
        """Every threading.Thread instantiation must explicitly declare daemon=True."""
        non_daemon_threads = []
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)

        for f in py_files:
            if '__pycache__' in f:
                continue
            with open(f, 'rb') as fp:
                tree = ast.parse(fp.read(), filename=f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        is_thread = False
                        if isinstance(func, ast.Attribute) and func.attr == 'Thread':
                            is_thread = True
                        elif isinstance(func, ast.Name) and func.id == 'Thread':
                            is_thread = True

                        if is_thread:
                            has_daemon_kw = any(kw.arg == 'daemon' for kw in node.keywords)
                            if not has_daemon_kw:
                                non_daemon_threads.append((f, node.lineno))

        self.assertEqual(non_daemon_threads, [], f"Threads missing daemon=True found: {non_daemon_threads}")

    def test_zero_untimed_urlopen_calls(self):
        """Every direct urlopen call must explicitly specify a timeout."""
        untimed_urlopen = []
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)

        for f in py_files:
            if '__pycache__' in f:
                continue
            with open(f, 'rb') as fp:
                tree = ast.parse(fp.read(), filename=f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        is_urlopen = False
                        if isinstance(func, ast.Attribute) and func.attr == 'urlopen':
                            is_urlopen = True
                        elif isinstance(func, ast.Name) and func.id == 'urlopen':
                            is_urlopen = True

                        if is_urlopen:
                            has_timeout_kw = any(kw.arg == 'timeout' for kw in node.keywords)
                            has_pos_timeout = len(node.args) >= 3
                            if not (has_timeout_kw or has_pos_timeout):
                                untimed_urlopen.append((f, node.lineno))

        self.assertEqual(untimed_urlopen, [], f"urlopen calls missing timeout found: {untimed_urlopen}")

    def test_zero_unsafe_datapath_concatenations(self):
        """Zero direct string concatenations of control.dataPath + ... are permitted."""
        unsafe_concat = []
        py_files = glob.glob(f"{ADDON_DIR}/**/*.py", recursive=True)

        for f in py_files:
            if '__pycache__' in f:
                continue
            with open(f, 'rb') as fp:
                tree = ast.parse(fp.read(), filename=f)
                for node in ast.walk(tree):
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                        left = node.left
                        if isinstance(left, ast.Attribute) and left.attr == 'dataPath':
                            if isinstance(left.value, ast.Name) and left.value.id == 'control':
                                unsafe_concat.append((f, node.lineno))

        self.assertEqual(unsafe_concat, [], f"Unsafe control.dataPath string concatenations found: {unsafe_concat}")

    def test_all_skin_xmls_valid_etree(self):
        """Every XML template in resources/skins must parse cleanly with ElementTree."""
        xml_files = glob.glob(f"{SKIN_XML_DIR}/*.xml")
        self.assertGreaterEqual(len(xml_files), 35, f"Should find at least 35 skin XMLs, got {len(xml_files)}")
        parse_errors = []
        for xf in xml_files:
            try:
                ET.parse(xf)
            except Exception as e:
                parse_errors.append((os.path.basename(xf), str(e)))
        self.assertEqual(parse_errors, [], f"Skin XML parse errors encountered: {parse_errors}")

    def test_skin_xml_defaultcontrol_references(self):
        """Every skin XML with an integer defaultcontrol must declare a matching control id."""
        xml_files = glob.glob(f"{SKIN_XML_DIR}/*.xml")
        missing_defaultcontrols = []
        for xf in xml_files:
            tree = ET.parse(xf)
            root = tree.getroot()
            dc_elem = root.find('defaultcontrol')
            if dc_elem is not None and dc_elem.text and dc_elem.text.strip().isdigit():
                dc_id = dc_elem.text.strip()
                # Find all control id attributes and param id values
                control_ids = {elem.get('id') for elem in root.iter('control') if elem.get('id')}
                param_ids = {elem.get('value') or (elem.text and elem.text.strip()) for elem in root.iter('param') if elem.get('name') == 'id'}
                all_ids = (control_ids | param_ids) - {None}
                if dc_id not in all_ids:
                    missing_defaultcontrols.append((os.path.basename(xf), dc_id))
        self.assertEqual(missing_defaultcontrols, [], f"Skin XML defaultcontrol IDs not found in control tree: {missing_defaultcontrols}")

    def test_skin_xml_bbcode_integrity(self):
        """Skin XML files must not contain malformed or unclosed BBCode tags."""
        xml_files = glob.glob(f"{SKIN_XML_DIR}/*.xml")
        bbcode_errors = []
        color_typo_re = re.compile(r'\[COLOR[a-zA-Z]')  # Missing space like [COLORdeepskyblue]
        for xf in xml_files:
            with open(xf, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
            if color_typo_re.search(content):
                bbcode_errors.append((os.path.basename(xf), "Malformed [COLOR...] tag without space"))
            # Check tag balance for common Kodi skin BBCodes
            open_cnt = len(re.findall(r'\[COLOR(?:\s+|=)[^\]]+\]', content, re.IGNORECASE))
            close_cnt = len(re.findall(r'\[/COLOR\]', content, re.IGNORECASE))
            if open_cnt != close_cnt:
                bbcode_errors.append((os.path.basename(xf), f"Unbalanced [COLOR] ({open_cnt}) vs [/COLOR] ({close_cnt})"))
            for tag in ('UPPERCASE', 'LOWERCASE', 'B', 'I'):
                open_cnt = len(re.findall(rf'\[{tag}\]', content, re.IGNORECASE))
                close_cnt = len(re.findall(rf'\[/{tag}\]', content, re.IGNORECASE))
                if open_cnt != close_cnt:
                    bbcode_errors.append((os.path.basename(xf), f"Unbalanced [{tag}] ({open_cnt}) vs [/{tag}] ({close_cnt})"))
        self.assertEqual(bbcode_errors, [], f"BBCode formatting errors in skin XMLs: {bbcode_errors}")


if __name__ == '__main__':
    unittest.main()