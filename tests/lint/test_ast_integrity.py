"""
Lint test ensuring AST syntax integrity, architectural safety invariants, and AGENTS.md static guardrails.
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
import re
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_DIR = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
CONTEXT_ADDON_DIR = os.path.join(REPO_ROOT, 'context.otaku.rpdev')
SKIN_XML_DIR = os.path.join(ADDON_DIR, 'resources', 'skins', 'Default', '1080i')
CONTROL_PY_PATH = os.path.normpath(os.path.join(ADDON_DIR, 'resources', 'lib', 'ui', 'control.py'))


def _iter_addon_py_files(include_context=True):
    """Yield all Python source files across plugin.video.otaku.rpdev (and context.otaku.rpdev)."""
    roots = [ADDON_DIR]
    if include_context and os.path.isdir(CONTEXT_ADDON_DIR):
        roots.append(CONTEXT_ADDON_DIR)
    seen = set()
    for root in roots:
        for path in sorted(glob.glob(f"{root}/**/*.py", recursive=True)):
            if '__pycache__' in path:
                continue
            norm = os.path.normpath(path)
            if norm not in seen:
                seen.add(norm)
                yield norm


def _find_unchecked_wait_for_abort(tree, filename='<ast>'):
    """Detect standalone ast.Expr calls to waitForAbort / wait_for_abort whose return value is discarded."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr in ('waitForAbort', 'wait_for_abort'):
                violations.append((filename, node.lineno))
            elif isinstance(func, ast.Name) and func.id in ('waitForAbort', 'wait_for_abort'):
                violations.append((filename, node.lineno))
    return violations


def _find_mutable_default_arguments(tree, filename='<ast>'):
    """Detect mutable default arguments ([], {}, set(), list(), dict()) in function/method definitions."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for default_node in defaults:
                is_mutable = isinstance(default_node, (ast.List, ast.Dict, ast.Set))
                if not is_mutable and isinstance(default_node, ast.Call):
                    if isinstance(default_node.func, ast.Name) and default_node.func.id in ('list', 'dict', 'set'):
                        is_mutable = True
                if is_mutable:
                    violations.append((filename, node.lineno, node.name))
    return violations


def _find_legacy_super_calls(tree, filename='<ast>'):
    """Detect Python 2 style super(Class, self) calls instead of cooperative super()."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'super':
            if node.args or node.keywords:
                violations.append((filename, node.lineno))
    return violations


def _find_raw_print_calls(tree, filename='<ast>'):
    """Detect raw built-in print() calls that bypass control.log() / xbmc.log()."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == 'print':
                violations.append((filename, node.lineno))
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == 'print'
                and isinstance(func.value, ast.Name)
                and func.value.id == 'builtins'
            ):
                violations.append((filename, node.lineno))
    return violations


def _find_direct_json_loads(tree, filename='<ast>'):
    """Detect direct json.loads(...) or imported loads(...) from json module."""
    json_mod_aliases = {'json'}
    json_loads_aliases = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'json':
                    json_mod_aliases.add(alias.asname or 'json')
        elif isinstance(node, ast.ImportFrom) and node.module == 'json':
            for alias in node.names:
                if alias.name == 'loads':
                    json_loads_aliases.add(alias.asname or 'loads')

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == 'loads'
                and isinstance(func.value, ast.Name)
                and func.value.id in json_mod_aliases
            ):
                violations.append((filename, node.lineno))
            elif isinstance(func, ast.Name) and func.id in json_loads_aliases:
                violations.append((filename, node.lineno))
    return violations


class TestASTIntegrity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Parse all add-on Python files once to keep static AST gates fast over NFS/sharedroot."""
        cls._syntax_errors = []
        cls._parsed_files = []
        for f in _iter_addon_py_files(include_context=True):
            with open(f, 'rb') as fp:
                try:
                    tree = ast.parse(fp.read(), filename=f)
                    cls._parsed_files.append((f, tree))
                except SyntaxError as e:
                    cls._syntax_errors.append((f, str(e)))

    def test_all_python_files_pass_ast_parse(self):
        """Every Python file in both add-ons must compile cleanly with ast.parse."""
        self.assertEqual(self._syntax_errors, [], f"SyntaxError encountered: {self._syntax_errors}")
        self.assertGreater(len(self._parsed_files), 50, "Should scan at least 50 Python files")

    def test_zero_bare_excepts(self):
        """Zero bare 'except:' blocks are permitted across the codebase."""
        bare_excepts = []
        for f, tree in self._parsed_files:
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    bare_excepts.append((f, node.lineno))

        self.assertEqual(bare_excepts, [], f"Found bare except blocks: {bare_excepts}")

    def test_zero_raw_pickle_loads_outside_database(self):
        """raw pickle.loads() is forbidden outside database.py to prevent RCE."""
        forbidden_pickle_loads = []
        for f, tree in self._parsed_files:
            if f.endswith('database.py'):
                continue
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
        for f, tree in self._parsed_files:
            if f.endswith('database.py'):
                continue
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
        for f, tree in self._parsed_files:
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
        for f, tree in self._parsed_files:
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
        for f, tree in self._parsed_files:
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                    left = node.left
                    if isinstance(left, ast.Attribute) and left.attr == 'dataPath':
                        if isinstance(left.value, ast.Name) and left.value.id == 'control':
                            unsafe_concat.append((f, node.lineno))

        self.assertEqual(unsafe_concat, [], f"Unsafe control.dataPath string concatenations found: {unsafe_concat}")

    def test_zero_unchecked_standalone_wait_for_abort(self):
        """AGENTS.md §9: Standalone waitForAbort(...) expression statements (ast.Expr) are forbidden."""
        violations = []
        for f, tree in self._parsed_files:
            violations.extend(_find_unchecked_wait_for_abort(tree, f))

        self.assertEqual(
            violations,
            [],
            f"Unchecked standalone waitForAbort() calls found (must inspect boolean return): {violations}",
        )

    def test_zero_mutable_default_arguments(self):
        """AGENTS.md §4: Mutable default arguments ([], {}, set()) are forbidden in persistent Python invokers."""
        violations = []
        for f, tree in self._parsed_files:
            violations.extend(_find_mutable_default_arguments(tree, f))

        self.assertEqual(
            violations,
            [],
            f"Mutable default arguments found (use None sentinel instead): {violations}",
        )

    def test_zero_legacy_python2_super_calls(self):
        """AGENTS.md §4: Legacy super(ClassName, self) calls are forbidden; use cooperative super()."""
        violations = []
        for f, tree in self._parsed_files:
            violations.extend(_find_legacy_super_calls(tree, f))

        self.assertEqual(
            violations,
            [],
            f"Legacy Python 2 super(Class, self) calls found: {violations}",
        )

    def test_zero_raw_print_calls(self):
        """AGENTS.md §4: Raw built-in print() calls are forbidden; route diagnostics via control.log()."""
        violations = []
        for f, tree in self._parsed_files:
            violations.extend(_find_raw_print_calls(tree, f))

        self.assertEqual(
            violations,
            [],
            f"Raw print() calls found (use control.log instead): {violations}",
        )

    def test_zero_direct_json_loads_outside_control(self):
        """AGENTS.md §11: Direct json.loads() calls outside control.py are forbidden; use safe_json / loads_json."""
        violations = []
        for f, tree in self._parsed_files:
            if os.path.normpath(f) == CONTROL_PY_PATH:
                continue
            violations.extend(_find_direct_json_loads(tree, f))

        self.assertEqual(
            violations,
            [],
            f"Direct json.loads() calls outside control.py found (use control.loads_json / safe_json): {violations}",
        )

    def test_ast_guardrail_detectors_catch_synthetic_violations(self):
        """Self-test ensuring every AGENTS.md AST detector positively flags offending code patterns."""
        sample = ast.parse(
            "import json as _j\n"
            "from json import loads as _jl\n"
            "class Demo(Base):\n"
            "    def bad(self, a=[], b={}, *, c=set()):\n"
            "        super(Demo, self).__init__()\n"
            "        print('debug leak')\n"
            "        control.monitor.waitForAbort(3)\n"
            "        if control.monitor.waitForAbort(1):\n"
            "            return None\n"
            "        _j.loads('{}')\n"
            "        _jl('[]')\n"
        )
        self.assertEqual(len(_find_unchecked_wait_for_abort(sample)), 1)
        self.assertEqual(len(_find_mutable_default_arguments(sample)), 3)
        self.assertEqual(len(_find_legacy_super_calls(sample)), 1)
        self.assertEqual(len(_find_raw_print_calls(sample)), 1)
        self.assertEqual(len(_find_direct_json_loads(sample)), 2)

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
