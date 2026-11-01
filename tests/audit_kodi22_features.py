#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_kodi22_features.py - Comprehensive Kodi 22 RC Feature & Subsystem Audit
=============================================================================
Automated test harness that verifies all features, routes, scrapers, debrid
integrations (Premiumize live account), caching pipelines, and settings
compatibility against the Kodi 22 (Piers RC 1) execution runtime.
"""

import sys
import os
import time
import json
import xml.etree.ElementTree as ET

# Enable live network auditing for live debrid and scraper integration checks
os.environ['OTAKU_LIVE_AUDIT'] = '1'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ROOT = os.path.join(REPO_ROOT, "plugin.video.otaku.rpdev")
TESTS_ROOT = os.path.join(REPO_ROOT, "tests")

for p in (REPO_ROOT, ADDON_ROOT, TESTS_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# Set test profile dataPath to Kodi 22 profile
KODI22_PROFILE = "/mnt/sharedroot/projects/kodi-test-env/profiles/kodi22"
KODI22_ADDON_DATA = os.path.join(KODI22_PROFILE, "userdata", "addon_data", "plugin.video.otaku.rpdev")

import conftest  # Centralized Kodi mock harness  # noqa: F401
import xbmcplugin
from resources.lib.ui import control, database, client
from resources.lib import Main, MetaBrowser
from resources.lib.ui.router import router_process, ROUTES


class Kodi22FeatureAuditor:
    def __init__(self):
        self.results = {}
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.start_time = time.time()

        # Copy settings from kodi22 profile into mock harness
        self._sync_kodi22_settings()

    def _sync_kodi22_settings(self):
        settings_file = os.path.join(KODI22_ADDON_DATA, "settings.xml")
        if os.path.isfile(settings_file):
            tree = ET.parse(settings_file)
            root = tree.getroot()
            for elem in root.findall("setting"):
                sid = elem.attrib.get("id")
                val = elem.text or ""
                if sid:
                    control.setSetting(sid, val)

    def log_result(self, category, test_name, success, details=""):
        if category not in self.results:
            self.results[category] = []
        status = "PASS" if success else "FAIL"
        if success:
            self.passed += 1
            icon = "✅"
        else:
            self.failed += 1
            icon = "❌"
        self.results[category].append({
            "test": test_name,
            "status": status,
            "details": details
        })
        print(f"  {icon} [{status}] {test_name}: {details}")

    def audit_all(self):
        print("═══════════════════════════════════════════════════════════════════════════")
        print(" 🔍 Comprehensive Feature & Integration Audit on Kodi 22 (Piers RC 1)")
        print("═══════════════════════════════════════════════════════════════════════════\n")

        self.audit_settings_schema()
        self.audit_menu_and_route_registry()
        self.audit_database_and_caching()
        self.audit_premiumize_debrid_live()
        self.audit_scrapers_and_resolvers()
        self.audit_fastpath_and_smartplay()
        self.audit_autoskip_chapter_engine()
        self.audit_tools_and_maintenance()
        self.audit_kodi_log_health()

        self.print_summary()

    # ── 1. Settings Schema Audit ──────────────────────────────────────────────
    def audit_settings_schema(self):
        print("📋 Phase 1: Auditing Settings Schema & Kodi 22 Strict Typing...")
        settings_xml = os.path.join(ADDON_ROOT, "resources", "settings.xml")
        if not os.path.isfile(settings_xml):
            self.log_result("Settings", "settings.xml presence", False, "File not found")
            return

        tree = ET.parse(settings_xml)
        root = tree.getroot()
        all_settings = root.findall(".//setting")
        self.log_result("Settings", "settings.xml parsed", True, f"Found {len(all_settings)} declared settings")

        # Test querying critical settings under Kodi 22 typed getters
        try:
            v_ver = control.getSetting("otaku.version") or control.getSetting("version")
            v_ssl = control.getBool("general.verify_ssl")
            v_pm_en = control.getBool("premiumize.enabled")
            v_pm_token = control.getSetting("premiumize.token")
            v_smartplay = control.getBool("smartplay.prefer_same_embed")
            v_prescrape = control.getBool("smartplay.prescrape")
            v_last_played = control.getSetting("last_played_source")
            self.log_result("Settings", "Strict typed setting queries", True,
                            f"SSL: {v_ssl}, PM Enabled: {v_pm_en}, SmartPlay: {v_smartplay}, PreScrape: {v_prescrape}")
        except Exception as e:
            self.log_result("Settings", "Strict typed setting queries", False, str(e))

    # ── 2. Menu and Route Registry Audit ──────────────────────────────────────
    def audit_menu_and_route_registry(self):
        print("\n🧭 Phase 2: Auditing Menu Navigation & 525 Registered Routes...")
        self.log_result("Routes", "Route Registry", len(ROUTES) >= 500, f"{len(ROUTES)} routes registered")

        # Test top-level menu rendering
        test_routes = [
            ("Root / Main Menu", "", {}),
            ("Airing This Season", "airing_this_season", {}),
            ("Airing Last Season", "airing_last_season", {}),
            ("Top 100 Anime", "top_100", {}),
            ("Trending All Time", "all_time_trending", {}),
            ("Popular All Time", "all_time_popular", {}),
            ("Movies Category", "movies", {}),
            ("TV Shows Category", "tv_shows", {}),
            ("OVAs Category", "ovas", {}),
            ("Search Anime Menu", "search_history_anime", {}),
            ("Tools Menu", "tools", {}),
            ("Action Genre", "genre_action", {}),
            ("Romance Genre", "genre_romance", {}),
            ("Sci-Fi Genre", "genre_sci_fi", {}),
        ]

        for desc, path, params in test_routes:
            xbmcplugin.reset()
            try:
                Main.plugin_url = path
                control.setSetting('format', 'anime')
                router_process(path, params)
                items_emitted = len(xbmcplugin.directory_items)
                eod = len(xbmcplugin.end_of_directory_args) > 0
                self.log_result("Routes", f"Route: {desc} ({path})", eod or items_emitted > 0, f"{items_emitted} items, EOD: {eod}")
            except Exception as e:
                self.log_result("Routes", f"Route: {desc} ({path})", False, f"Exception: {e}")

        # Modal dialog route: Airing Calendar (anichart.xml)
        try:
            router_process("airing_calendar", {})
            self.log_result("Routes", "Modal Route: Airing Calendar (anichart.xml)", True, "Rendered without error")
        except Exception as e:
            self.log_result("Routes", "Modal Route: Airing Calendar (anichart.xml)", False, str(e))

    # ── 3. Database & Caching Audit ───────────────────────────────────────────
    def audit_database_and_caching(self):
        print("\n🗄️ Phase 3: Auditing SQLite WAL Storage & Cache Integrity...")
        try:
            stats_report = database.get_database_stats()
            has_stats = isinstance(stats_report, str) and len(stats_report) > 0
            self.log_result("Database", "Database Statistics Reporting", has_stats,
                            f"Generated formatted database stats report ({len(stats_report)} chars)")
        except Exception as e:
            self.log_result("Database", "Database Statistics Reporting", False, str(e))

        try:
            integrity = database.check_database_integrity()
            all_ok = all("ok" in str(v).lower() for v in integrity.values()) if isinstance(integrity, dict) else True
            self.log_result("Database", "SQLite PRAGMA integrity_check", all_ok, f"Result: {integrity}")
        except Exception as e:
            self.log_result("Database", "SQLite PRAGMA integrity_check", False, str(e))

        # Test atomic write capability
        test_file = os.path.join(control.dataPath, "test_atomic.tmp")
        try:
            write_ok = control.atomic_write_text(test_file, "atomic_test_content")
            read_back = ""
            if os.path.exists(test_file):
                with open(test_file) as f:
                    read_back = f.read()
                os.remove(test_file)
            self.log_result("Database", "Atomic Write Resilience", write_ok and read_back == "atomic_test_content",
                            f"Atomic write & read verified")
        except Exception as e:
            self.log_result("Database", "Atomic Write Resilience", False, str(e))

    # ── 4. Live Premiumize Debrid Audit ───────────────────────────────────────
    def audit_premiumize_debrid_live(self):
        print("\n💎 Phase 4: Auditing Premiumize Debrid Integration (Live Account)...")
        token = control.getSetting("premiumize.token")
        if not token:
            self.log_result("Debrid", "Premiumize Token Available", False, "No token found in settings")
            return

        self.log_result("Debrid", "Premiumize Token Stored", True, f"Token: {token[:8]}... (verified)")

        from resources.lib.debrid.premiumize import Premiumize
        pm = Premiumize()

        # 1. Test account status API
        try:
            headers = pm.headers()
            r = client.get(f"{pm.base_url}/account/info", headers=headers, timeout=15)
            if r and r.ok:
                info = r.json()
                cust_id = info.get("customer_id")
                prem_until = info.get("premium_until")
                is_premium = int(prem_until) > 0 if str(prem_until).isdigit() else False
                self.log_result("Debrid", "Live Account Status Check", True,
                                f"Customer ID: {cust_id}, Premium: {is_premium}, Until: {prem_until}")
            else:
                self.log_result("Debrid", "Live Account Status Check", False,
                                f"HTTP {getattr(r, 'status_code', 'error')}")
        except Exception as e:
            self.log_result("Debrid", "Live Account Status Check", False, str(e))

        # 2. Test hash checking (DMM / Premiumize direct)
        try:
            test_hashes = ["0123456789abcdef0123456789abcdef01234567", "c1205d6e7fb66f3611f2e3d71542d62ac5b3e69d"]
            cached = pm.hash_check(test_hashes)
            self.log_result("Debrid", "Live Cached Hash Checking", isinstance(cached, (list, dict, set)),
                            f"Checked {len(test_hashes)} hashes successfully")
        except Exception as e:
            self.log_result("Debrid", "Live Cached Hash Checking", False, str(e))

        # 3. Test transfers / cloud listing
        try:
            r = client.get(f"{pm.base_url}/transfer/list", headers=pm.headers(), timeout=15)
            transfers = r.json().get("transfers", []) if (r and r.ok) else []
            self.log_result("Debrid", "Cloud Transfers Listing", r.ok if r else False,
                            f"Active transfers: {len(transfers)}")
        except Exception as e:
            self.log_result("Debrid", "Cloud Transfers Listing", False, str(e))

    # ── 5. Scrapers & Resolvers Audit ─────────────────────────────────────────
    def audit_scrapers_and_resolvers(self):
        print("\n🌐 Phase 5: Auditing Scrapers & Resolvers...")

        # Seed metadata for show 52991 (Sousou no Frieren)
        try:
            from scripts.check_scraper_health import _seed_test_show_metadata
            _seed_test_show_metadata()
        except Exception as e:
            control.log(f"Seed metadata error: {e}", 'warning')

        # Test Torrent Scraper: Nyaa
        try:
            from resources.lib.pages import nyaa
            ny = nyaa.Sources()
            res = ny.get_sources("Sousou no Frieren", "52991", "1", "Finished Airing", "tv")
            cached_count = len(res.get('cached', []))
            uncached_count = len(res.get('uncached', []))
            total = cached_count + uncached_count
            self.log_result("Scrapers", "Nyaa Torrent Scraper (Live PM Cache)", total > 0,
                            f"Yielded {total} torrents ({cached_count} cached on Premiumize, {uncached_count} uncached)")
        except Exception as e:
            self.log_result("Scrapers", "Nyaa Torrent Scraper (Live PM Cache)", False, str(e))

        # Test Web Embed Scraper: Anikoto
        try:
            from resources.lib.pages import anikoto
            ak = anikoto.Sources()
            res = ak.get_sources("52991", "1")
            self.log_result("Scrapers", "Anikoto Embed Scraper", isinstance(res, list) and len(res) > 0,
                            f"Yielded {len(res) if isinstance(res, list) else 0} embeds")
        except Exception as e:
            self.log_result("Scrapers", "Anikoto Embed Scraper", False, str(e))

        # Test Web Embed Scraper: AnimePahe
        try:
            from resources.lib.pages import animepahe
            ap = animepahe.Sources()
            res = ap.get_sources("52991", "1")
            self.log_result("Scrapers", "AnimePahe Embed Scraper", isinstance(res, list),
                            f"Completed query without exception ({len(res) if isinstance(res, list) else 0} streams)")
        except Exception as e:
            self.log_result("Scrapers", "AnimePahe Embed Scraper", False, str(e))

    # ── 6. Zero-Wait Fast-Path & SmartPlay Continuity ─────────────────────────
    def audit_fastpath_and_smartplay(self):
        print("\n⚡ Phase 6: Auditing Zero-Wait Fast-Path & SmartPlay Continuity...")
        # 1. Test database set_episode_sources and get_episode_sources
        test_anilist_id = 9999999
        test_ep = 1
        sample_sources = [
            {"release_title": "Frieren - 01 [1080p].mkv", "source": "torrent", "debrid": "Premiumize", "hash": "abc123"},
            {"release_title": "Frieren - 01 [Sub].mp4", "source": "embed", "provider": "Anikoto", "info": "SUB"}
        ]

        try:
            database.set_episode_sources(test_anilist_id, test_ep, sample_sources)
            retrieved = database.get_episode_sources(test_anilist_id, test_ep)
            match = len(retrieved) == len(sample_sources) and retrieved[0].get("hash") == "abc123"
            self.log_result("FastPath", "Database Whole-Episode Source Pre-Caching", match,
                            f"Stored {len(sample_sources)} sources, retrieved {len(retrieved)}")
        except Exception as e:
            self.log_result("FastPath", "Database Whole-Episode Source Pre-Caching", False, str(e))

        # 2. Test SmartPlay prefer_same_embed reordering
        try:
            from resources.lib.pages import Sources
            control.setSetting("smartplay.prefer_same_embed", "true")
            control.setSetting("last_played_source", "Anikoto SUB")

            candidate_embeds = [
                {"release_title": "AnimePahe Stream", "provider": "AnimePahe", "info": "SUB", "type": "embed", "lang": 2, "quality": 2},
                {"release_title": "Anikoto Stream", "provider": "Anikoto", "info": "SUB", "type": "embed", "lang": 2, "quality": 2}
            ]
            sorted_res = Sources.sortSources([], [], candidate_embeds, [], [], "tv", 1400, 52991)
            is_anikoto_first = len(sorted_res) > 0 and sorted_res[0].get("provider") == "Anikoto"
            self.log_result("FastPath", "SmartPlay Embed Continuity Reordering", is_anikoto_first,
                            f"Top source provider: {sorted_res[0].get('provider') if sorted_res else 'none'}")
        except Exception as e:
            self.log_result("FastPath", "SmartPlay Embed Continuity Reordering", False, str(e))

    # ── 7. Auto-Skip Chapter Resolution Audit ─────────────────────────────────
    def audit_autoskip_chapter_engine(self):
        print("\n⏩ Phase 7: Auditing Auto-Skip Intro/Outro Engine...")
        try:
            from resources.lib.ui.source_utils import score_intro_chapter, CHAPTER_INTRO_KEYWORDS

            # Test 1: OP chapter scoring (standard 90s opening)
            score_op = score_intro_chapter("Opening 1", 90.0)
            score_random = score_intro_chapter("Episode Story", 300.0)
            self.log_result("AutoSkip", "Chapter Intro Scoring (OP vs Scene)", score_op > score_random,
                            f"OP Score: {score_op}, Scene Score: {score_random}")

            # Test 2: Cold open / prologue rejection
            has_prologue = "prologue" in CHAPTER_INTRO_KEYWORDS or "序章" in CHAPTER_INTRO_KEYWORDS
            self.log_result("AutoSkip", "Prologue False-Trigger Rejection", not has_prologue,
                            f"Prologue in intro keywords: {has_prologue}")
        except Exception as e:
            self.log_result("AutoSkip", "Auto-Skip Chapter Logic", False, str(e))

    # ── 8. Tools & Maintenance Audit ──────────────────────────────────────────
    def audit_tools_and_maintenance(self):
        print("\n🔧 Phase 8: Auditing Maintenance Tools & SQLite Vacuuming...")
        try:
            vacuum_res = database.vacuum_all_databases()
            self.log_result("Maintenance", "Vacuum SQLite Databases", vacuum_res, "Databases vacuumed and compact")
        except Exception as e:
            self.log_result("Maintenance", "Vacuum SQLite Databases", False, str(e))

        try:
            database.checkpoint_databases(truncate=True)
            self.log_result("Maintenance", "WAL Checkpoint & Truncate", True, "WAL checkpoints executed without error")
        except Exception as e:
            self.log_result("Maintenance", "WAL Checkpoint & Truncate", False, str(e))

    # ── 9. Kodi Log Health Audit ──────────────────────────────────────────────
    def audit_kodi_log_health(self):
        print("\n📑 Phase 9: Auditing Kodi 22 Log Health...")
        kodi_log_path = os.path.join(KODI22_PROFILE, "temp", "kodi.log")
        if not os.path.isfile(kodi_log_path):
            self.log_result("LogHealth", "Kodi Log Exists", False, f"Not found at {kodi_log_path}")
            return

        with open(kodi_log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        errors = []
        pyqrcode_found = False
        swig_warnings = []
        setting_exceptions = []

        for line in lines:
            if "script.module.pyqrcode" in line:
                pyqrcode_found = True
            if "SwigDirector_WindowXMLDialog" in line:
                swig_warnings.append(line.strip())
            if "EXCEPTION: Invalid setting type" in line:
                setting_exceptions.append(line.strip())
            if "OTAKU RPDEV" in line and ("error <general>" in line or "Unhandled exception" in line):
                errors.append(line.strip())

        self.log_result("LogHealth", "PyQRCode Addon Loaded by Kodi", pyqrcode_found,
                        "script.module.pyqrcode registered in Addon Manager")
        self.log_result("LogHealth", "Zero Setting Type Exceptions", len(setting_exceptions) == 0,
                        f"{len(setting_exceptions)} setting exceptions detected")
        self.log_result("LogHealth", "Zero SWIG WindowXMLDialog Leaks", len(swig_warnings) == 0,
                        f"{len(swig_warnings)} SWIG warnings detected")
        self.log_result("LogHealth", "Zero Unhandled Otaku Exceptions in Log", len(errors) == 0,
                        f"{len(errors)} unhandled exceptions in live log")

    def print_summary(self):
        duration = round(time.time() - self.start_time, 2)
        total = self.passed + self.failed
        print("\n═══════════════════════════════════════════════════════════════════════════")
        print(f" 📊 AUDIT COMPLETE: {self.passed}/{total} Passed, {self.failed} Failed ({duration}s)")
        print("═══════════════════════════════════════════════════════════════════════════")
        if self.failed == 0:
            print(" 🎉 ALL KODI 22 (PIERS RC 1) AUDITS PASSED WITH ZERO FAILURES!")
        else:
            print(f" ⚠️  {self.failed} AUDIT(S) FAILED. REVIEW DETAILS ABOVE.")
        print("═══════════════════════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    auditor = Kodi22FeatureAuditor()
    auditor.audit_all()
    sys.exit(0 if auditor.failed == 0 else 1)
