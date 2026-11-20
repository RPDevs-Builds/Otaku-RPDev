# -*- coding: utf-8 -*-
"""
test_suite_quality.py - Meta-Test Quality & Anti-Placeholder Guardrails
=======================================================================
Mechanically enforces high-signal, actionable testing standards across all
test silos (tests/unit/, tests/integration/, tests/lint/):
1. Zero-assertion tests are forbidden (every test_* method must assert).
2. Tautological assertions (assertTrue(True), assertFalse(False), assertEqual(x, x)) are forbidden.
3. Swallowing broad exceptions (except Exception: pass / bare except: pass) inside test_* is forbidden.
4. Unexecuted importlib.util.module_from_spec() without exec_module() is forbidden.
5. Import-only placeholder tests whose only assertions are assertIsNotNone(<name>) are forbidden.
"""

import ast
import glob
import os
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401

TESTS_ROOT = os.path.join(_REPO_ROOT, 'tests')
ASSERT_CALL_NAMES = {
    'assertEqual', 'assertNotEqual', 'assertTrue', 'assertFalse',
    'assertIs', 'assertIsNot', 'assertIsNone', 'assertIsNotNone',
    'assertIn', 'assertNotIn', 'assertIsInstance', 'assertNotIsInstance',
    'assertRaises', 'assertRaisesRegex', 'assertAlmostEqual', 'assertNotAlmostEqual',
    'assertGreater', 'assertGreaterEqual', 'assertLess', 'assertLessEqual',
    'assertRegex', 'assertNotRegex', 'assertCountEqual',
    'assert_called', 'assert_called_once', 'assert_called_with',
    'assert_called_once_with', 'assert_any_call', 'assert_not_called',
    'assert_has_calls', 'fail',
}


def _iter_test_files():
    for sub in ('unit', 'integration', 'lint'):
        folder = os.path.join(TESTS_ROOT, sub)
        if not os.path.isdir(folder):
            continue
        for path in sorted(glob.glob(os.path.join(folder, 'test_*.py'))):
            yield os.path.relpath(path, _REPO_ROOT), path


def _iter_test_functions(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
            yield node


def _collect_assertion_nodes(func_node):
    found = []
    for sub in ast.walk(func_node):
        if isinstance(sub, ast.Assert):
            found.append(sub)
        elif isinstance(sub, ast.Call):
            fname = ''
            if isinstance(sub.func, ast.Attribute):
                fname = sub.func.attr
            elif isinstance(sub.func, ast.Name):
                fname = sub.func.id
            if fname in ASSERT_CALL_NAMES or fname.startswith('assert') or fname.startswith('_assert') or fname.startswith('_verify'):
                found.append(sub)
    return found


class TestSuiteQuality(unittest.TestCase):
    """Meta-lint suite preventing placeholder, zero-assertion, and false-positive tests."""

    def test_zero_assertion_tests_forbidden(self):
        """Every test_* method across unit/integration/lint must contain at least one assertion."""
        violations = []
        scanned = 0
        for rel, path in _iter_test_files():
            scanned += 1
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=rel)
            for fn in _iter_test_functions(tree):
                # Allow explicit skipTest-only tests if decorated
                is_skipped = any('skip' in ast.unparse(d).lower() for d in fn.decorator_list)
                if is_skipped:
                    continue
                if not _collect_assertion_nodes(fn):
                    violations.append(f"{rel}:{fn.lineno} {fn.name}")
        self.assertGreaterEqual(scanned, 90, f"Expected >= 90 test files scanned under {TESTS_ROOT}, got {scanned}")
        self.assertEqual(
            violations, [],
            "Zero-assertion tests detected (add concrete behavioral assertions):\n  " + "\n  ".join(violations),
        )

    def test_tautological_assertions_forbidden(self):
        """Disallow assertTrue(True), assertFalse(False), and assertEqual(x, x) tautologies."""
        violations = []
        for rel, path in _iter_test_files():
            if rel.endswith('test_suite_quality.py'):
                continue
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=rel)
            for fn in _iter_test_functions(tree):
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.Assert) and isinstance(sub.test, ast.Constant) and sub.test.value is True:
                        violations.append(f"{rel}:{sub.lineno} assert True")
                    elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        attr = sub.func.attr
                        if attr == 'assertTrue' and sub.args:
                            arg0 = sub.args[0]
                            if isinstance(arg0, ast.Constant) and arg0.value is True:
                                violations.append(f"{rel}:{sub.lineno} assertTrue(True)")
                            elif isinstance(arg0, ast.BoolOp) and isinstance(arg0.op, ast.Or):
                                if any(isinstance(v, ast.Constant) and v.value is True for v in arg0.values):
                                    violations.append(f"{rel}:{sub.lineno} assertTrue(... or True)")
                        elif attr == 'assertFalse' and sub.args and isinstance(sub.args[0], ast.Constant) and sub.args[0].value is False:
                            violations.append(f"{rel}:{sub.lineno} assertFalse(False)")
                        elif attr == 'assertEqual' and len(sub.args) >= 2 and ast.dump(sub.args[0]) == ast.dump(sub.args[1]):
                            violations.append(f"{rel}:{sub.lineno} assertEqual(x, x)")
        self.assertEqual(
            violations, [],
            "Tautological assertions detected:\n  " + "\n  ".join(violations),
        )

    def test_broad_exception_swallowing_in_tests_forbidden(self):
        """Disallow except Exception: pass or bare except: pass inside test_* methods (can swallow AssertionError)."""
        violations = []
        for rel, path in _iter_test_files():
            if rel.endswith('test_suite_quality.py'):
                continue
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=rel)
            for fn in _iter_test_functions(tree):
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.ExceptHandler):
                        is_pass_only = len(sub.body) == 1 and isinstance(sub.body[0], (ast.Pass, ast.Continue))
                        if not is_pass_only:
                            continue
                        if sub.type is None or (isinstance(sub.type, ast.Name) and sub.type.id in ('Exception', 'BaseException')):
                            violations.append(f"{rel}:{sub.lineno} {fn.name} swallows broad exception")
        self.assertEqual(
            violations, [],
            "Broad exception swallowing inside test methods detected (may hide AssertionError/crashes):\n  " + "\n  ".join(violations),
        )

    def test_unexecuted_module_from_spec_placeholders_forbidden(self):
        """Disallow module_from_spec() tests that never call exec_module()."""
        violations = []
        for rel, path in _iter_test_files():
            if rel.endswith('test_suite_quality.py'):
                continue
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
                tree = ast.parse(src, filename=rel)
            for fn in _iter_test_functions(tree):
                seg = ast.get_source_segment(src, fn) or ''
                if 'module_from_spec' in seg and 'exec_module' not in seg:
                    violations.append(f"{rel}:{fn.lineno} {fn.name}")
        self.assertEqual(
            violations, [],
            "Tests call module_from_spec without exec_module (placeholder import test):\n  " + "\n  ".join(violations),
        )

    def test_import_only_is_not_none_placeholders_forbidden(self):
        """Disallow tests whose ONLY assertions are assertIsNotNone(<simple variable>)."""
        violations = []
        for rel, path in _iter_test_files():
            if rel.endswith('test_suite_quality.py'):
                continue
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=rel)
            for fn in _iter_test_functions(tree):
                asserts = _collect_assertion_nodes(fn)
                if not asserts:
                    continue
                if all(
                    isinstance(a, ast.Call)
                    and isinstance(a.func, ast.Attribute)
                    and a.func.attr == 'assertIsNotNone'
                    and len(a.args) == 1
                    and isinstance(a.args[0], ast.Name)
                    for a in asserts
                ):
                    violations.append(f"{rel}:{fn.lineno} {fn.name} ({len(asserts)} assertIsNotNone-only)")
        self.assertEqual(
            violations, [],
            "Placeholder assertIsNotNone-only tests detected (assert concrete behavior/values):\n  " + "\n  ".join(violations),
        )


if __name__ == '__main__':
    unittest.main()
