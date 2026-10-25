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


if __name__ == '__main__':
    unittest.main()
