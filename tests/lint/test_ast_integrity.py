"""
Lint test ensuring zero AST syntax errors, zero bare excepts, and zero raw pickle.loads calls outside database.py.
"""

import ast
import glob
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_DIR = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')


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


if __name__ == '__main__':
    unittest.main()
