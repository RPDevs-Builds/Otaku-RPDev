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
SUBTITLE_ADDON_DIR = os.path.join(REPO_ROOT, 'service.subtitles.otaku.rpdev')
SKIN_XML_DIR = os.path.join(ADDON_DIR, 'resources', 'skins', 'Default', '1080i')
CONTROL_PY_PATH = os.path.normpath(os.path.join(ADDON_DIR, 'resources', 'lib', 'ui', 'control.py'))


def _iter_addon_py_files(include_context=True):
    """Yield all Python source files across plugin.video.otaku.rpdev, context.otaku.rpdev, and service.subtitles.otaku.rpdev."""
    roots = [ADDON_DIR]
    if include_context and os.path.isdir(CONTEXT_ADDON_DIR):
        roots.append(CONTEXT_ADDON_DIR)
    if include_context and os.path.isdir(SUBTITLE_ADDON_DIR):
        roots.append(SUBTITLE_ADDON_DIR)
    seen = set()
    for root in roots:
        for path in sorted(glob.glob(f"{root}/**/*.py", recursive=True)):
            if '__pycache__' in path or '/scripts/' in path:
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


def _find_bs4_css_selectors(tree, filename='<ast>'):
    """Detect BeautifulSoup .select(...) / .select_one(...) calls that crash when soupsieve is absent in Kodi."""
    imports_bs4 = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'bs4' or alias.name.startswith('bs4.'):
                    imports_bs4 = True
        elif isinstance(node, ast.ImportFrom) and node.module and (
            node.module == 'bs4' or node.module.startswith('bs4.')
        ):
            imports_bs4 = True

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == 'select_one':
                violations.append((filename, node.lineno, 'select_one'))
            elif node.func.attr == 'select' and imports_bs4:
                violations.append((filename, node.lineno, 'select'))
    return violations


def _find_mutating_audit_calls(tree, filename='<ast>'):
    """Detect subprocess/SSH/ADB or mutating HTTP operations forbidden in read-only ONN log auditing."""
    forbidden_modules = {'subprocess', 'paramiko', 'shutil', 'ftplib', 'telnetlib', 'pty'}
    mutating_http = {'POST', 'PUT', 'DELETE', 'PATCH'}
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split('.')[0]
                if root_mod in forbidden_modules:
                    violations.append((filename, node.lineno, f"forbidden import {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_mod = node.module.split('.')[0]
            if root_mod in forbidden_modules:
                violations.append((filename, node.lineno, f"forbidden import {node.module}"))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                attr = func.attr
                if isinstance(func.value, ast.Name) and func.value.id == 'os':
                    if attr in ('system', 'popen') or attr.startswith(('spawn', 'exec', 'fork')):
                        violations.append((filename, node.lineno, f"os.{attr}"))
                if attr.lower() in ('post', 'put', 'delete', 'patch') and isinstance(func.value, ast.Name) and func.value.id in ('requests', 'client'):
                    violations.append((filename, node.lineno, f"mutating HTTP {func.value.id}.{attr}"))
            for kw in node.keywords:
                if kw.arg == 'method' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if kw.value.value.upper() in mutating_http:
                        violations.append((filename, node.lineno, f"method={kw.value.value.upper()}"))
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    val_low = arg.value.strip().lower()
                    if val_low == 'adb' or val_low.startswith('adb '):
                        violations.append((filename, node.lineno, "adb command literal"))
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

    def test_zero_bs4_css_selectors_requiring_soupsieve(self):
        """BeautifulSoup .select() / .select_one() require optional soupsieve not guaranteed in Kodi; use find/find_all."""
        violations = []
        for f, tree in self._parsed_files:
            violations.extend(_find_bs4_css_selectors(tree, f))

        self.assertEqual(
            violations,
            [],
            f"BeautifulSoup .select()/.select_one() calls found (use .find()/.find_all() instead): {violations}",
        )

    def test_ast_guardrail_detectors_catch_synthetic_violations(self):
        """Self-test ensuring every AGENTS.md AST detector positively flags offending code patterns."""
        sample = ast.parse(
            "import json as _j\n"
            "from json import loads as _jl\n"
            "from bs4 import BeautifulSoup\n"
            "class Demo(Base):\n"
            "    def bad(self, a=[], b={}, *, c=set()):\n"
            "        super(Demo, self).__init__()\n"
            "        print('debug leak')\n"
            "        control.monitor.waitForAbort(3)\n"
            "        if control.monitor.waitForAbort(1):\n"
            "            return None\n"
            "        _j.loads('{}')\n"
            "        _jl('[]')\n"
            "        soup = BeautifulSoup('', 'html.parser')\n"
            "        soup.select('.item')\n"
            "        soup.select_one('.link')\n"
        )
        self.assertEqual(len(_find_unchecked_wait_for_abort(sample)), 1)
        self.assertEqual(len(_find_mutable_default_arguments(sample)), 3)
        self.assertEqual(len(_find_legacy_super_calls(sample)), 1)
        self.assertEqual(len(_find_raw_print_calls(sample)), 1)
        self.assertEqual(len(_find_direct_json_loads(sample)), 2)
        self.assertEqual(len(_find_bs4_css_selectors(sample)), 2)

        audit_sample = ast.parse(
            "import os\n"
            "import subprocess\n"
            "import urllib.request\n"
            "os.system('adb shell tail -n 10 kodi.log')\n"
            "urllib.request.Request('http://10.13.0.16:8081/tail', method='POST')\n"
            "urllib.request.Request('http://10.13.0.16:8081/tail', method='GET')\n"
        )
        audit_violations = _find_mutating_audit_calls(audit_sample)
        self.assertEqual(len(audit_violations), 4)

    def test_audit_onn_logs_strictly_read_only(self):
        """scripts/audit_onn_logs.py must remain strictly read-only (HTTP GET + explicit timeout only)."""
        audit_path = os.path.join(REPO_ROOT, 'scripts', 'audit_onn_logs.py')
        self.assertTrue(os.path.isfile(audit_path), f"Missing {audit_path}")
        with open(audit_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=audit_path)

        violations = _find_mutating_audit_calls(tree, filename='scripts/audit_onn_logs.py')
        self.assertEqual(violations, [], f"Mutating/subprocess calls forbidden in audit_onn_logs.py: {violations}")

        untimed = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                is_urlopen = (
                    (isinstance(func, ast.Attribute) and func.attr == 'urlopen')
                    or (isinstance(func, ast.Name) and func.id == 'urlopen')
                )
                if is_urlopen:
                    has_timeout = any(kw.arg == 'timeout' for kw in node.keywords) or len(node.args) >= 3
                    if not has_timeout:
                        untimed.append(node.lineno)
        self.assertEqual(untimed, [], f"urlopen missing timeout in audit_onn_logs.py: {untimed}")

    def test_zero_repo_root_test_leak_artifacts(self):
        """Tests must never leak special:/ or MagicMock/ directories into repository root."""
        for leak_name in ('special:', 'MagicMock'):
            leak_path = os.path.join(REPO_ROOT, leak_name)
            self.assertFalse(
                os.path.exists(leak_path),
                f"Test leak artifact directory exists at repo root: {leak_path}",
            )
        translated = conftest.mock_xbmcvfs.translatePath('special://temp/')
        self.assertFalse(translated.startswith('special://'))
        self.assertEqual(os.path.normpath(translated), conftest.TEST_TEMP_DIR)

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

    def test_zero_deprecated_ssl_protocol_constants(self):
        """AGENTS.md §4/§11: Deprecated ssl.PROTOCOL_TLSv1* / PROTOCOL_TLS constants are forbidden; use PROTOCOL_TLS_CLIENT."""
        deprecated = {'PROTOCOL_TLS', 'PROTOCOL_TLSv1', 'PROTOCOL_TLSv1_1', 'PROTOCOL_TLSv1_2', 'PROTOCOL_SSLv23'}
        violations = []
        for path in _iter_addon_py_files():
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in deprecated:
                    violations.append((os.path.relpath(path, REPO_ROOT), node.lineno, node.attr))
        self.assertEqual(violations, [], f"Deprecated SSL protocol constants detected: {violations}")

    def test_zero_deprecated_listitem_setinfo_calls(self):
        """AGENTS.md §4: Deprecated ListItem.setInfo() calls are forbidden; use getVideoInfoTag()."""
        violations = []
        for path in _iter_addon_py_files():
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'setInfo':
                    violations.append((os.path.relpath(path, REPO_ROOT), node.lineno))
        self.assertEqual(violations, [], f"Deprecated ListItem.setInfo() calls detected: {violations}")

    def test_zero_int_timeout_truncation_in_client_py(self):
        """AGENTS.md §11: client.py must cast timeouts via float(timeout), never int(timeout)."""
        client_path = os.path.join(ADDON_DIR, 'resources', 'lib', 'ui', 'client.py')
        with open(client_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=client_path)
        violations = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'int'
                and node.args
                and isinstance(node.args[0], ast.Name)
                and 'timeout' in node.args[0].id.lower()
            ):
                violations.append((os.path.relpath(client_path, REPO_ROOT), node.lineno))
        self.assertEqual(violations, [], f"int(timeout) truncation detected in client.py: {violations}")

    def test_zero_circular_addon_dependencies(self):
        """All repo addon.xml <requires>/<import> graphs must be acyclic (Kodi 22 freezes on circular deps)."""
        addon_xmls = sorted(glob.glob(os.path.join(REPO_ROOT, '*', 'addon.xml')))
        self.assertGreaterEqual(len(addon_xmls), 3, f"Expected >= 3 addon.xml files, found {len(addon_xmls)}")

        graph = {}
        for xml_path in addon_xmls:
            root = ET.parse(xml_path).getroot()
            aid = root.attrib.get('id', '').strip()
            deps = [
                imp.attrib.get('addon', '').strip()
                for imp in root.findall('./requires/import')
                if imp.attrib.get('addon', '').strip()
            ]
            if aid:
                graph[aid] = deps

        cycles = []

        def _dfs(node, path, visiting):
            visiting.add(node)
            for dep in graph.get(node, []):
                if dep in visiting:
                    cycles.append(' -> '.join(path + [dep]))
                elif dep in graph:
                    _dfs(dep, path + [dep], visiting)
            visiting.remove(node)

        for aid in sorted(graph):
            _dfs(aid, [aid], set())

        self.assertEqual(
            cycles, [],
            "Circular add-on dependency cycle(s) detected (causes Kodi DialogAddonInfo freeze):\n  " + "\n  ".join(cycles),
        )

    def test_zero_case_insensitive_asset_collisions_and_oversized_pngs(self):
        """CR-01: Zero case-insensitive filename collisions across all 3 add-ons and root PNG size limits."""
        png_magic = b'\x89PNG\r\n\x1a\n'
        collisions = []
        for addon_dir in (ADDON_DIR, CONTEXT_ADDON_DIR, SUBTITLE_ADDON_DIR):
            for dirpath, _dirnames, filenames in os.walk(addon_dir):
                if '__pycache__' in dirpath:
                    continue
                seen_lower = {}
                for fn in filenames:
                    low = fn.lower()
                    if low in seen_lower:
                        collisions.append((os.path.relpath(dirpath, REPO_ROOT), seen_lower[low], fn))
                    else:
                        seen_lower[low] = fn

            poster_path = os.path.join(addon_dir, 'poster.png')
            icon_path = os.path.join(addon_dir, 'icon.png')
            self.assertTrue(os.path.isfile(poster_path), f"Missing {poster_path}")
            self.assertTrue(os.path.isfile(icon_path), f"Missing {icon_path}")
            self.assertLess(os.path.getsize(poster_path), 350 * 1024, f"Oversized poster.png in {addon_dir}")
            self.assertLess(os.path.getsize(icon_path), 150 * 1024, f"Oversized icon.png in {addon_dir}")
            with open(poster_path, 'rb') as pf:
                self.assertEqual(pf.read(8), png_magic)
            with open(icon_path, 'rb') as icf:
                self.assertEqual(icf.read(8), png_magic)

        self.assertEqual(collisions, [], f"Case-insensitive filename collisions found: {collisions}")

    def test_studio_logos_zero_slug_or_sha256_duplicates(self):
        """P32-03: context.otaku.rpdev studio logos must have 0 alphanumeric-slug or SHA-256 duplicates."""
        import hashlib
        import unicodedata

        c_dir = os.path.join(CONTEXT_ADDON_DIR, 'resources', 'images', 'studios', 'coloured')
        w_dir = os.path.join(CONTEXT_ADDON_DIR, 'resources', 'images', 'studios', 'white')
        self.assertTrue(os.path.isdir(c_dir))
        self.assertTrue(os.path.isdir(w_dir))

        c_files = sorted(os.listdir(c_dir))
        w_files = sorted(os.listdir(w_dir))
        self.assertGreaterEqual(len(c_files), 450)
        self.assertEqual(c_files, w_files, "coloured and white studio logo filenames must match identically")

        for style_name, d_path, fns in (('coloured', c_dir, c_files), ('white', w_dir, w_files)):
            slugs = {}
            hashes = {}
            for fn in fns:
                stem = os.path.splitext(fn)[0]
                ascii_stem = unicodedata.normalize('NFKD', stem).encode('ascii', 'ignore').decode('ascii')
                slug = re.sub(r'[^a-z0-9]', '', ascii_stem.lower())
                slugs.setdefault(slug, []).append(fn)
                with open(os.path.join(d_path, fn), 'rb') as fp:
                    digest = hashlib.sha256(fp.read()).hexdigest()
                hashes.setdefault(digest, []).append(fn)
            slug_dups = {k: v for k, v in slugs.items() if len(v) > 1}
            sha_dups = {k[:10]: v for k, v in hashes.items() if len(v) > 1}
            self.assertEqual(slug_dups, {}, f"{style_name} studio alphanumeric-slug duplicates: {slug_dups}")
            self.assertEqual(sha_dups, {}, f"{style_name} studio SHA-256 duplicates: {sha_dups}")

    def test_c36_indirect_and_template_setting_keys_resolve_in_settings_xml(self):
        """P32-02 (C-36): Resolve f-string template setting keys (provider/flavor/embed) against settings.xml."""
        settings_xml = os.path.join(ADDON_DIR, 'resources', 'settings.xml')
        declared_ids = {
            e.attrib['id']
            for e in ET.parse(settings_xml).getroot().findall('.//setting')
            if e.attrib.get('id')
        }
        self.assertGreaterEqual(len(declared_ids), 495)

        setting_funcs = {'getSetting', 'getBool', 'getInt', 'getStr', 'getNumber', 'getStringList', 'setSetting', 'setBool', 'setInt'}
        template_domains = {
            ('name', 'userid'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'authvar'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'token'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'refresh'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'username'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'password'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'sort'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('name', 'order'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('flavor', 'token'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('flavor', 'password'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('flavor', 'username'): ('anilist', 'kitsu', 'mal', 'simkl'),
            ('prefix', 'skipintro.start'): ('hianime', 'animekai', 'anikoto'),
            ('prefix', 'skipintro.end'): ('hianime', 'animekai', 'anikoto'),
            ('prefix', 'skipoutro.start'): ('hianime', 'animekai', 'anikoto'),
            ('prefix', 'skipoutro.end'): ('hianime', 'animekai', 'anikoto'),
            ('embed', 'skipintro.start'): ('hianime', 'animekai', 'anikoto'),
            ('embed', 'skipintro.end'): ('hianime', 'animekai', 'anikoto'),
            ('embed', 'skipoutro.start'): ('hianime', 'animekai', 'anikoto'),
            ('embed', 'skipoutro.end'): ('hianime', 'animekai', 'anikoto'),
        }

        missing = []
        templates_checked = 0
        for path in _iter_addon_py_files(include_context=False):
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in setting_funcs and node.args):
                    continue
                arg0 = node.args[0]
                if isinstance(arg0, ast.JoinedStr) and len(arg0.values) >= 2:
                    v0 = arg0.values[0]
                    if (
                        isinstance(v0, ast.FormattedValue)
                        and isinstance(v0.value, ast.Name)
                        and all(isinstance(p, ast.Constant) and isinstance(p.value, str) for p in arg0.values[1:])
                    ):
                        suffix = ''.join(p.value for p in arg0.values[1:])
                        if suffix.startswith('.'):
                            suffix = suffix[1:]
                        domain = template_domains.get((v0.value.id, suffix))
                        if domain:
                            for prefix_val in domain:
                                resolved = f"{prefix_val}.{suffix}"
                                templates_checked += 1
                                if resolved not in declared_ids:
                                    missing.append((os.path.relpath(path, REPO_ROOT), node.lineno, resolved))

        self.assertGreaterEqual(templates_checked, 40, f"Expected >= 40 resolved template keys, got {templates_checked}")
        self.assertEqual(missing, [], f"Undeclared template setting keys detected: {missing}")


if __name__ == '__main__':
    unittest.main()
