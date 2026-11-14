#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_function_coverage.py - Exhaustive Function & Module Coverage Audit Gate
=============================================================================
Parses all 139 Python source files across plugin.video.otaku.rpdev/ and
context.otaku.rpdev/ using Python's stdlib AST, catalogs every class,
function, and method, and traces test suite execution using Python 3.12+
sys.monitoring (tool=COVERAGE_ID) with transparent sys.settrace fallback.

Enforces:
1. 100% Module Coverage (0 unreferenced or unimported source modules out of all 139 files).
2. Function & Method Coverage tracking with configurable --fail-below threshold.
3. Machine-readable JSON and Markdown reporting.
"""

import argparse
import ast
import json
import os
import re
import sys
import time
import unittest
from collections import defaultdict

# ---------------------------------------------------------------------------
# Path Resolution
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
ADDON_DIR = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
CONTEXT_DIR = os.path.join(REPO_ROOT, 'context.otaku.rpdev')
TESTS_DIR = os.path.join(REPO_ROOT, 'tests')

for p in (REPO_ROOT, ADDON_DIR, CONTEXT_DIR, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# AST Discovery & Symbol Parsing
# ---------------------------------------------------------------------------
def discover_source_files(repo_root=REPO_ROOT):
    """
    Discover all 139 Python files across plugin.video.otaku.rpdev and context.otaku.rpdev.
    Returns sorted list of (rel_path, abs_path).
    """
    source_dirs = [
        os.path.join(repo_root, 'plugin.video.otaku.rpdev'),
        os.path.join(repo_root, 'context.otaku.rpdev'),
    ]
    files = []
    for s_dir in source_dirs:
        if not os.path.exists(s_dir):
            continue
        for root, _, filenames in os.walk(s_dir):
            for fn in filenames:
                if fn.endswith('.py'):
                    abs_p = os.path.normpath(os.path.join(root, fn))
                    rel_p = os.path.normpath(os.path.relpath(abs_p, repo_root))
                    files.append((rel_p, abs_p))
    files.sort(key=lambda x: x[0])
    return files


def get_possible_import_names(rel_path):
    """Generate all standard Python import strings that can resolve to rel_path."""
    parts = os.path.normpath(rel_path).split(os.sep)
    if parts[0] == 'plugin.video.otaku.rpdev':
        sub = parts[1:]
    else:
        sub = parts

    if sub[-1] == '__init__.py':
        mod_parts = sub[:-1]
    elif sub[-1].endswith('.py'):
        mod_parts = sub[:-1] + [sub[-1][:-3]]
    else:
        mod_parts = sub

    names = set()
    if mod_parts:
        names.add('.'.join(mod_parts))
        for i in range(1, len(mod_parts)):
            names.add('.'.join(mod_parts[i:]))

    basename = os.path.splitext(os.path.basename(rel_path))[0]
    if basename != 'default':
        names.add(basename)
    if parts[0] == 'context.otaku.rpdev':
        names.add('context_default')
        names.add('context.default')
    elif parts[0] == 'plugin.video.otaku.rpdev' and rel_path.endswith('default.py'):
        names.add('plugin_default')
        names.add('plugin.video.otaku.rpdev.default')
    return names


class SourceFileVisitor(ast.NodeVisitor):
    """Extract classes, functions, and methods from a Python AST."""

    def __init__(self, rel_path, abs_path):
        self.rel_path = rel_path
        self.abs_path = abs_path
        self.classes = []       # list of dict(name, lineno, end_lineno)
        self.functions = []     # list of dict(name, qualname, class_name, lineno, end_lineno, is_method, is_dunder, is_public)
        self.current_classes = []

    def visit_ClassDef(self, node):
        self.classes.append({
            'name': node.name,
            'lineno': node.lineno,
            'end_lineno': getattr(node, 'end_lineno', node.lineno),
        })
        self.current_classes.append(node.name)
        self.generic_visit(node)
        self.current_classes.pop()

    def visit_FunctionDef(self, node):
        self._record_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._record_func(node)
        self.generic_visit(node)

    def _record_func(self, node):
        cls_name = self.current_classes[-1] if self.current_classes else None
        qualname = f"{cls_name}.{node.name}" if cls_name else node.name
        is_dunder = node.name.startswith('__') and node.name.endswith('__')
        is_public = not (node.name.startswith('_') and not is_dunder)
        is_method = cls_name is not None

        self.functions.append({
            'name': node.name,
            'qualname': qualname,
            'class_name': cls_name,
            'lineno': node.lineno,
            'end_lineno': getattr(node, 'end_lineno', node.lineno),
            'is_method': is_method,
            'is_dunder': is_dunder,
            'is_public': is_public,
        })


def parse_source_tree(repo_root=REPO_ROOT):
    """Parse all source files and return file info dict."""
    source_files = discover_source_files(repo_root)
    catalog = {}

    for rel_path, abs_path in source_files:
        with open(abs_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=abs_path)
        visitor = SourceFileVisitor(rel_path, abs_path)
        visitor.visit(tree)
        catalog[rel_path] = {
            'abs_path': abs_path,
            'classes': visitor.classes,
            'functions': visitor.functions,
            'possible_imports': get_possible_import_names(rel_path),
        }
    return catalog


# ---------------------------------------------------------------------------
# Test Execution Tracer (sys.monitoring / sys.settrace)
# ---------------------------------------------------------------------------
class ExecutionTracer:
    """
    Hermetic runtime execution tracer.
    Uses sys.monitoring on Python 3.12+ for near-zero overhead, falling back
    to sys.settrace on earlier Python runtimes.
    """

    def __init__(self, repo_root=REPO_ROOT):
        self.repo_root = os.path.normpath(repo_root)
        self.executed_files = set()  # normalized abs paths and rel paths
        self.executed_qualnames = defaultdict(set)  # norm_path -> set of (qualname, name)
        self.executed_lines = defaultdict(set)      # norm_path -> set of line numbers
        self.monitoring_tool_id = None
        self._is_active = False

    def _normalize_filename(self, fn):
        if not fn or fn.startswith('<'):
            return None
        norm = os.path.normpath(os.path.abspath(fn))
        if norm.startswith(self.repo_root):
            return norm
        return None

    def start(self):
        if self._is_active:
            return
        self._is_active = True

        if hasattr(sys, 'monitoring') and hasattr(sys.monitoring, 'COVERAGE_ID'):
            tool_id = None
            candidate_ids = [sys.monitoring.COVERAGE_ID, 3, 4, 5]
            if hasattr(sys.monitoring, 'PROFILER_ID'):
                candidate_ids.append(sys.monitoring.PROFILER_ID)

            for tid in candidate_ids:
                if sys.monitoring.get_tool(tid) is None:
                    tool_id = tid
                    break

            if tool_id is not None:
                self.monitoring_tool_id = tool_id
                sys.monitoring.use_tool_id(tool_id, f'otaku_coverage_{tool_id}')

                def on_py_start(code, offset):
                    fn = self._normalize_filename(code.co_filename)
                    if fn:
                        self.executed_files.add(fn)
                        rel = os.path.relpath(fn, self.repo_root)
                        self.executed_files.add(rel)

                        qual = getattr(code, 'co_qualname', code.co_name)
                        name = code.co_name
                        self.executed_qualnames[fn].add(qual)
                        self.executed_qualnames[fn].add(name)
                        self.executed_qualnames[rel].add(qual)
                        self.executed_qualnames[rel].add(name)
                        self.executed_lines[fn].add(code.co_firstlineno)
                        self.executed_lines[rel].add(code.co_firstlineno)
                    return sys.monitoring.DISABLE

                sys.monitoring.register_callback(tool_id, sys.monitoring.events.PY_START, on_py_start)
                sys.monitoring.set_events(tool_id, sys.monitoring.events.PY_START)
                return
        else:
            def trace_func(frame, event, arg):
                if event == 'call':
                    fn = self._normalize_filename(frame.f_code.co_filename)
                    if fn:
                        self.executed_files.add(fn)
                        rel = os.path.relpath(fn, self.repo_root)
                        self.executed_files.add(rel)

                        qual = getattr(frame.f_code, 'co_qualname', frame.f_code.co_name)
                        name = frame.f_code.co_name
                        self.executed_qualnames[fn].add(qual)
                        self.executed_qualnames[fn].add(name)
                        self.executed_qualnames[rel].add(qual)
                        self.executed_qualnames[rel].add(name)
                        self.executed_lines[fn].add(frame.f_code.co_firstlineno)
                        self.executed_lines[rel].add(frame.f_code.co_firstlineno)
                return trace_func

            sys.settrace(trace_func)

    def stop(self):
        if not self._is_active:
            return
        if self.monitoring_tool_id is not None:
            try:
                sys.monitoring.set_events(self.monitoring_tool_id, sys.monitoring.events.NO_EVENTS)
                sys.monitoring.free_tool_id(self.monitoring_tool_id)
            except Exception:
                pass
            self.monitoring_tool_id = None
        else:
            sys.settrace(None)
        self._is_active = False


# ---------------------------------------------------------------------------
# Coverage Computation & Audit Logic
# ---------------------------------------------------------------------------
def compute_coverage(catalog, tracer, active_modules=None):
    """
    Compare discovered AST symbols with traced runtime execution.
    Returns dict containing comprehensive breakdown.
    """
    if active_modules is None:
        active_modules = set(sys.modules.keys())

    total_files = len(catalog)
    covered_files = []
    uncovered_files = []

    total_funcs = 0
    covered_funcs = 0
    public_funcs = 0
    covered_public_funcs = 0

    per_file_data = {}

    for rel_path, data in catalog.items():
        abs_p = data['abs_path']
        possible_mods = data['possible_imports']

        # File is considered covered if executed by tracer OR imported in sys.modules
        is_imported = any(mod in active_modules for mod in possible_mods)
        if not is_imported:
            norm_abs = os.path.normpath(abs_p)
            for m in list(sys.modules.values()):
                f = getattr(m, '__file__', None)
                if f and os.path.normpath(os.path.abspath(f)) == norm_abs:
                    is_imported = True
                    break

        is_traced = (abs_p in tracer.executed_files) or (rel_path in tracer.executed_files)
        file_covered = is_imported or is_traced

        if file_covered:
            covered_files.append(rel_path)
        else:
            uncovered_files.append(rel_path)

        file_executed_quals = tracer.executed_qualnames.get(abs_p, set()) | tracer.executed_qualnames.get(rel_path, set())
        file_executed_lines = tracer.executed_lines.get(abs_p, set()) | tracer.executed_lines.get(rel_path, set())

        file_funcs = data['functions']
        f_total = len(file_funcs)
        f_hit = 0
        f_pub_total = 0
        f_pub_hit = 0

        func_details = []
        for fn in file_funcs:
            name = fn['name']
            qual = fn['qualname']
            lineno = fn['lineno']
            end_lineno = fn['end_lineno']
            is_pub = fn['is_public']

            total_funcs += 1
            if is_pub:
                public_funcs += 1
                f_pub_total += 1

            # Hit condition: exact qualname hit, or simple name hit with line range match
            hit = False
            if qual in file_executed_quals or name in file_executed_quals:
                hit = True
            elif any(lineno <= l <= end_lineno for l in file_executed_lines):
                hit = True

            if hit:
                f_hit += 1
                covered_funcs += 1
                if is_pub:
                    f_pub_hit += 1
                    covered_public_funcs += 1

            func_details.append({
                'name': name,
                'qualname': qual,
                'is_public': is_pub,
                'is_method': fn['is_method'],
                'lineno': lineno,
                'hit': hit,
            })

        f_pct = (f_hit / f_total * 100.0) if f_total > 0 else 100.0
        f_pub_pct = (f_pub_hit / f_pub_total * 100.0) if f_pub_total > 0 else 100.0

        per_file_data[rel_path] = {
            'abs_path': abs_p,
            'covered': file_covered,
            'classes_count': len(data['classes']),
            'functions_count': f_total,
            'functions_hit': f_hit,
            'functions_pct': f_pct,
            'public_functions_count': f_pub_total,
            'public_functions_hit': f_pub_hit,
            'public_functions_pct': f_pub_pct,
            'functions': func_details,
        }

    mod_pct = (len(covered_files) / total_files * 100.0) if total_files > 0 else 0.0
    func_pct = (covered_funcs / total_funcs * 100.0) if total_funcs > 0 else 0.0
    pub_func_pct = (covered_public_funcs / public_funcs * 100.0) if public_funcs > 0 else 0.0

    return {
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'summary': {
            'total_source_files': total_files,
            'covered_source_files': len(covered_files),
            'uncovered_source_files_count': len(uncovered_files),
            'module_coverage_pct': round(mod_pct, 2),
            'total_functions': total_funcs,
            'covered_functions': covered_funcs,
            'function_coverage_pct': round(func_pct, 2),
            'total_public_functions': public_funcs,
            'covered_public_functions': covered_public_funcs,
            'public_function_coverage_pct': round(pub_func_pct, 2),
            'uncovered_files': uncovered_files,
        },
        'files': per_file_data,
    }


# ---------------------------------------------------------------------------
# Report Generators
# ---------------------------------------------------------------------------
def generate_text_summary(report, verbose=False):
    lines = []
    s = report['summary']
    lines.append("=" * 80)
    lines.append("  OTAKU-RPDEV FUNCTION & MODULE COVERAGE AUDIT REPORT")
    lines.append("=" * 80)
    lines.append(f"  Total Source Files:       {s['total_source_files']}")
    lines.append(f"  Covered Source Files:     {s['covered_source_files']} ({s['module_coverage_pct']}%)")
    lines.append(f"  Uncovered Source Files:   {s['uncovered_source_files_count']}")
    lines.append(f"  Public Functions/Methods: {s['covered_public_functions']} / {s['total_public_functions']} ({s['public_function_coverage_pct']}%)")
    lines.append(f"  All Functions/Methods:    {s['covered_functions']} / {s['total_functions']} ({s['function_coverage_pct']}%)")
    lines.append("-" * 80)

    if s['uncovered_files']:
        lines.append("  UNCOVERED FILES (VIOLATIONS):")
        for uf in s['uncovered_files']:
            lines.append(f"    - {uf}")
        lines.append("-" * 80)
    else:
        lines.append("  ✓ 100% MODULE COVERAGE ACHIEVED: 0 unreferenced/unimported source modules.")
        lines.append("-" * 80)

    if verbose:
        lines.append(f"  {'File':<62} | {'Funcs':<7} | {'Hit':<5} | {'Cov %':<6}")
        lines.append("  " + "-" * 76)
        for rel_p, d in sorted(report['files'].items()):
            fn_str = f"{d['functions_hit']}/{d['functions_count']}"
            lines.append(f"  {rel_p:<62} | {fn_str:<7} | {d['functions_hit']:<5} | {d['functions_pct']:>5.1f}%")
        lines.append("=" * 80)

    return "\n".join(lines)


def generate_markdown_report(report):
    s = report['summary']
    lines = [
        "# Otaku-RPDev Function & Module Coverage Audit Report",
        "",
        f"- **Timestamp**: `{report['timestamp']}`",
        f"- **Total Source Files**: `{s['total_source_files']}`",
        f"- **Module Coverage**: `{s['covered_source_files']}/{s['total_source_files']}` (**{s['module_coverage_pct']}%**)",
        f"- **Uncovered Files**: `{s['uncovered_source_files_count']}`",
        f"- **Public Function Coverage**: `{s['covered_public_functions']}/{s['total_public_functions']}` (**{s['public_function_coverage_pct']}%**)",
        f"- **All Function Coverage**: `{s['covered_functions']}/{s['total_functions']}` (**{s['function_coverage_pct']}%**)",
        "",
    ]

    if s['uncovered_files']:
        lines.extend([
            "### ❌ Uncovered Source Files",
            "",
            "The following source files were neither imported nor executed in the test suite:",
            "",
        ])
        for uf in s['uncovered_files']:
            lines.append(f"- `{uf}`")
        lines.append("")
    else:
        lines.extend([
            "### ✅ Module Coverage Invariant Satisfied",
            "",
            "100% of all 139 source files across `plugin.video.otaku.rpdev/` and `context.otaku.rpdev/` are imported and referenced in the test suite.",
            "",
        ])

    lines.extend([
        "### Module Breakdown",
        "",
        "| Source File | Classes | Total Funcs | Hit | Coverage | Public Hit |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ])

    for rel_p, d in sorted(report['files'].items()):
        f_cov = f"{d['functions_pct']:.1f}%"
        pub_cov = f"{d['public_functions_hit']}/{d['public_functions_count']}"
        lines.append(f"| `{rel_p}` | {d['classes_count']} | {d['functions_count']} | {d['functions_hit']} | {f_cov} | {pub_cov} |")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner Execution
# ---------------------------------------------------------------------------
def run_audit(tests_dir=TESTS_DIR, test_target=None, fail_below=None, output_json=None, output_md=None, verbose=False):
    """
    Run test discovery under tracer, compute coverage metrics, and enforce invariants.
    Returns (success_boolean, report_dict).
    """
    # 1. Parse AST of all 139 source files
    catalog = parse_source_tree(REPO_ROOT)

    # 2. Setup hermetic execution tracer
    tracer = ExecutionTracer(REPO_ROOT)
    tracer.start()

    # 3. Ensure conftest is imported so Kodi mocks and network guards are active
    try:
        import conftest  # noqa: F401
    except Exception as e:
        sys.stderr.write(f"Warning importing conftest: {e}\n")

    # 4. Discover and execute unittest suite
    test_loader = unittest.defaultTestLoader
    if test_target:
        if os.path.isfile(test_target):
            # Load specific test file
            rel_test = os.path.relpath(test_target, REPO_ROOT)
            suite = test_loader.loadTestsFromName(rel_test.replace(os.sep, '.').rstrip('.py'))
        else:
            suite = test_loader.loadTestsFromName(test_target)
    else:
        suite = test_loader.discover(tests_dir)

    test_runner = unittest.TextTestRunner(verbosity=1 if verbose else 0, stream=sys.stderr)
    test_result = test_runner.run(suite)

    # 5. Stop tracer
    tracer.stop()

    # 6. Compute coverage against active sys.modules
    report = compute_coverage(catalog, tracer, set(sys.modules.keys()))

    # 7. Print summary and output files
    summary_text = generate_text_summary(report, verbose=verbose)
    print(summary_text)

    if output_json:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        print(f"JSON report written to: {output_json}")

    if output_md:
        with open(output_md, 'w', encoding='utf-8') as f:
            f.write(generate_markdown_report(report))
        print(f"Markdown report written to: {output_md}")

    # 8. Assertions and exit criteria
    s = report['summary']
    all_tests_passed = test_result.wasSuccessful()
    module_100_percent = (s['uncovered_source_files_count'] == 0)

    coverage_threshold_met = True
    if fail_below is not None:
        coverage_threshold_met = (s['function_coverage_pct'] >= float(fail_below))

    success = all_tests_passed and module_100_percent and coverage_threshold_met

    if not all_tests_passed:
        print(f"\n[FAIL] Test suite had {len(test_result.failures)} failures and {len(test_result.errors)} errors.")
    if not module_100_percent:
        print(f"\n[FAIL] Module coverage is {s['module_coverage_pct']}% (< 100%). {s['uncovered_source_files_count']} files unreferenced.")
    if fail_below is not None and not coverage_threshold_met:
        print(f"\n[FAIL] Function coverage is {s['function_coverage_pct']}% (< required {fail_below}%).")

    return success, report


def main():
    parser = argparse.ArgumentParser(description="Audit function and module coverage across Otaku-RPDev source files.")
    parser.add_argument('--fail-below', type=float, default=None, help="Fail if function coverage is below this percentage.")
    parser.add_argument('--output', '--json', dest='output_json', default=None, help="Path to write JSON coverage report.")
    parser.add_argument('--markdown', '--md', dest='output_md', default=None, help="Path to write Markdown coverage report.")
    parser.add_argument('--test-target', default=None, help="Specific test module or path to run instead of entire discover suite.")
    parser.add_argument('--tests-dir', default=TESTS_DIR, help="Tests directory to discover from.")
    parser.add_argument('-v', '--verbose', action='store_true', help="Verbose per-file breakdown.")

    args = parser.parse_args()
    success, _ = run_audit(
        tests_dir=args.tests_dir,
        test_target=args.test_target,
        fail_below=args.fail_below,
        output_json=args.output_json,
        output_md=args.output_md,
        verbose=args.verbose,
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
