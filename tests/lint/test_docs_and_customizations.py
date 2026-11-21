# -*- coding: utf-8 -*-
"""
test_docs_and_customizations.py - Workspace Rules, Skills & Docs Drift Linter
=============================================================================
Catches documentation, rule-budget, and LLM customization drift early:
1. Otaku-RPDev/AGENTS.md must stay strictly < 22,000 bytes (below Antigravity's 24 KB truncation cap).
2. Every .agents/skills/*/SKILL.md must have valid YAML frontmatter (name matching folder, description).
3. All relative Markdown links in README.md, AGENTS.md, docs/*.md, and .agents/skills/*/SKILL.md must exist.
4. plugin.video.otaku.rpdev/news.txt horizontal '=' / '-' dividers must stay <= 32 characters.
5. docs/CONCERNS.md must contain a valid integer Next review offset cursor.
"""

import glob
import os
import re
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

AGENTS_MD_MAX_BYTES = 22000  # 2 KB safety buffer below Antigravity's 24,000-byte per-file rule cap
MD_LINK_RE = re.compile(r'(?<!!)\[[^\]]+\]\(([^)]+)\)')


def _parse_frontmatter(text):
    """Minimal dependency-free YAML frontmatter parser for SKILL.md (supports folded scalars)."""
    if not text.startswith('---\n'):
        return None
    parts = text.split('\n---\n', 1)
    if len(parts) != 2:
        return None
    header = parts[0][4:]
    data = {}
    current_key = None
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')) and ':' in line:
            k, v = line.split(':', 1)
            k = k.strip()
            v = v.strip()
            if v in ('>-', '>', '|-', '|'):
                data[k] = ''
                current_key = k
            else:
                data[k] = v.strip('"\'')
                current_key = k
        elif current_key:
            data[current_key] = (data[current_key] + ' ' + line.strip()).strip()
    return data


class TestDocsAndCustomizations(unittest.TestCase):
    """Mechanical guardrails for rules, skills, news.txt formatting, and documentation links."""

    def test_agents_md_within_24kb_context_budget(self):
        agents_path = os.path.join(_REPO_ROOT, 'AGENTS.md')
        self.assertTrue(os.path.isfile(agents_path), "AGENTS.md missing at repo root")
        size_bytes = os.path.getsize(agents_path)
        self.assertLess(
            size_bytes,
            AGENTS_MD_MAX_BYTES,
            f"AGENTS.md is {size_bytes} bytes (>= {AGENTS_MD_MAX_BYTES} byte budget; risks 24 KB truncation)",
        )

    def test_project_skills_have_valid_frontmatter(self):
        skills_dir = os.path.join(_REPO_ROOT, '.agents', 'skills')
        skill_files = sorted(glob.glob(os.path.join(skills_dir, '*', 'SKILL.md')))
        self.assertGreaterEqual(len(skill_files), 3, "Expected at least 3 project skills under .agents/skills/")
        for sf in skill_files:
            folder_name = os.path.basename(os.path.dirname(sf))
            with open(sf, 'r', encoding='utf-8') as f:
                text = f.read()
            fm = _parse_frontmatter(text)
            self.assertIsNotNone(fm, f"{sf} missing valid YAML frontmatter")
            self.assertEqual(fm.get('name'), folder_name, f"{sf} frontmatter name must match folder '{folder_name}'")
            self.assertRegex(folder_name, r'^[a-z0-9-]+$', f"Skill name '{folder_name}' must be lowercase hyphenated")
            self.assertGreaterEqual(len(fm.get('description', '')), 25, f"{sf} description too short/missing")

    def test_markdown_relative_links_resolve(self):
        md_files = [
            os.path.join(_REPO_ROOT, 'README.md'),
            os.path.join(_REPO_ROOT, 'AGENTS.md'),
            os.path.join(_REPO_ROOT, 'CHANGEREPORT.md'),
            os.path.join(_REPO_ROOT, 'PROJECT_REVIEW_REPORT.md'),
        ]
        md_files += sorted(glob.glob(os.path.join(_REPO_ROOT, 'docs', '*.md')))
        md_files += sorted(glob.glob(os.path.join(_REPO_ROOT, 'docs', 'teamwork', '**', '*.md'), recursive=True))
        md_files += sorted(glob.glob(os.path.join(_REPO_ROOT, '.agents', 'skills', '*', 'SKILL.md')))

        broken = []
        scanned = 0
        for mf in md_files:
            if not os.path.isfile(mf):
                continue
            scanned += 1
            with open(mf, 'r', encoding='utf-8') as f:
                text = f.read()
            # Strip fenced code blocks before scanning links
            stripped = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
            base_dir = os.path.dirname(mf)
            for match in MD_LINK_RE.finditer(stripped):
                target = match.group(1).strip()
                if not target or target.startswith(('http://', 'https://', 'mailto:', '#', 'file://', 'plugin://')):
                    continue
                rel_target = target.split('#', 1)[0].split('?', 1)[0].strip()
                if not rel_target:
                    continue
                resolved = os.path.normpath(os.path.join(base_dir, rel_target))
                if not os.path.exists(resolved):
                    broken.append(f"{os.path.relpath(mf, _REPO_ROOT)} -> {target}")

        self.assertGreaterEqual(scanned, 15, f"Expected >= 15 markdown/skill docs scanned, got {scanned}")
        self.assertEqual(broken, [], "Broken relative Markdown links:\n  " + "\n  ".join(broken))

    def test_news_txt_dividers_fit_textviewer_width(self):
        news_path = os.path.join(_REPO_ROOT, 'plugin.video.otaku.rpdev', 'news.txt')
        self.assertTrue(os.path.isfile(news_path))
        violations = []
        with open(news_path, 'r', encoding='utf-8') as f:
            for lineno, line in enumerate(f, 1):
                s = line.strip()
                if len(s) > 32 and set(s) <= {'=', '-'}:
                    violations.append(f"news.txt:{lineno} divider length {len(s)} > 32")
        self.assertEqual(violations, [], "news.txt horizontal dividers exceed 32-char textviewer.xml limit:\n  " + "\n  ".join(violations))

    def test_concerns_md_has_valid_review_cursor(self):
        concerns_path = os.path.join(_REPO_ROOT, 'docs', 'CONCERNS.md')
        self.assertTrue(os.path.isfile(concerns_path))
        with open(concerns_path, 'r', encoding='utf-8') as f:
            text = f.read()
        m = re.search(r'\*\*Next review offset\*\*\s*\|\s*\*\*(\d+)\*\*', text)
        self.assertIsNotNone(m, "docs/CONCERNS.md missing valid **Next review offset** integer cursor")
        self.assertGreaterEqual(int(m.group(1)), 0)

    def test_coverage_fail_below_threshold_parity_across_ci_scripts_and_docs(self):
        """Enforce identical --fail-below 65 threshold across CI, scripts, rules, and docs."""
        targets = [
            '.github/workflows/ci.yml',
            '.github/workflows/release.yml',
            'scripts/release_addon.py',
            'scripts/verify_all.py',
            'AGENTS.md',
            'docs/ARCHITECTURE.md',
            'docs/TESTING.md',
            'docs/AUTOMATION.md',
        ]
        mismatches = []
        for rel in targets:
            path = os.path.join(_REPO_ROOT, rel)
            self.assertTrue(os.path.isfile(path), f"Missing target file: {rel}")
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            found = re.findall(r'--fail-below["\',=\s]+(\d+(?:\.\d+)?)', content)
            self.assertTrue(found, f"{rel} has no --fail-below threshold reference")
            for val in found:
                if float(val) != 65.0:
                    mismatches.append(f"{rel}: found --fail-below {val} (expected 65)")
        self.assertEqual(mismatches, [], "Coverage --fail-below threshold drift detected:\n  " + "\n  ".join(mismatches))

    def test_concern_patterns_in_audit_onn_logs_align_with_concerns_md(self):
        """Verify CONCERN_PATTERNS in scripts/audit_onn_logs.py align with docs/CONCERNS.md definitions."""
        from scripts import audit_onn_logs
        concerns_path = os.path.join(_REPO_ROOT, 'docs', 'CONCERNS.md')
        with open(concerns_path, 'r', encoding='utf-8') as f:
            table_rows = [ln for ln in f.readlines() if ln.lstrip().startswith('|')]

        expected_keywords = {
            'C-06': 'CHANGE_LOG',
            'C-11': 'subtitle parser',
            'C-14': 'peer(56)',
            'C-34': 'resolve_silent',
            'C-35': 'wlf_auth',
        }
        for cid, pattern in audit_onn_logs.CONCERN_PATTERNS.items():
            cid_re = re.compile(rf'(?:^\|\s*{re.escape(cid)}\s*\||^\|\s*R-\d+\s*\|\s*[^|]*\b{re.escape(cid)}\b)')
            matching_rows = [r for r in table_rows if cid_re.search(r)]
            self.assertTrue(matching_rows, f"{cid} in CONCERN_PATTERNS missing from docs/CONCERNS.md Open/Resolved tables")
            if cid in expected_keywords:
                kw = expected_keywords[cid]
                self.assertIn(
                    kw.lower(),
                    pattern.pattern.lower().replace('\\(', '(').replace('\\)', ')'),
                    f"CONCERN_PATTERNS[{cid!r}] regex {pattern.pattern!r} does not match canonical domain keyword {kw!r}",
                )
                self.assertTrue(
                    any(kw.lower() in row.lower() for row in matching_rows),
                    f"docs/CONCERNS.md table row for {cid} missing expected domain keyword {kw!r}",
                )

    def test_plans_md_numbered_sections_are_sequential(self):
        """Ensure top-level numbered sections (## 1. .. ## N.) in docs/PLANS.md have no skipped numbers."""
        plans_path = os.path.join(_REPO_ROOT, 'docs', 'PLANS.md')
        self.assertTrue(os.path.isfile(plans_path))
        with open(plans_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        nums = []
        for line in lines:
            m = re.match(r'^##\s+(\d+)\.\s+', line)
            if m:
                nums.append(int(m.group(1)))
        self.assertGreaterEqual(len(nums), 7, f"Expected >= 7 numbered sections in docs/PLANS.md, found {nums}")
        self.assertEqual(nums, list(range(1, len(nums) + 1)), f"Non-sequential section numbering in docs/PLANS.md: {nums}")


if __name__ == '__main__':
    unittest.main()
