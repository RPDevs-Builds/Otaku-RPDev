# -*- coding: utf-8 -*-
"""Release-Group Sorting, Filtering & Series Playback Profile Multi-Select Unit Tests."""

import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest

from resources.lib.pages import Sources
from resources.lib.routes import tools as tools_routes
from resources.lib.ui import control, database, settings_manager, source_utils
from resources.lib.ui.database_sync import SyncDatabase
from resources.lib.windows import series_profile, source_select
from tests.kodi_profile import KodiProfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTEXT_ADDON_XML = os.path.join(REPO_ROOT, 'context.otaku.rpdev', 'addon.xml')
SETTINGS_XML = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev', 'resources', 'settings.xml')


@pytest.fixture(autouse=True)
def _restore_release_group_settings():
    yield
    control.setSetting('general.release_group.preferred', '')
    control.setSetting('general.release_group.excluded', '')
    control.setInt('general.release_group.tiebreak', 0)


# ─── 1. Deterministic Release-Group Extraction & 40-Group Catalog ────────────

@pytest.mark.parametrize(
    'title,expected',
    [
        ('[SubsPlease] Sousou no Frieren - 01 (1080p) [A1B2C3D4].mkv', 'SubsPlease'),
        ('[Judas] Jujutsu Kaisen - S02E05 [1080p][HEVC x265 10bit][Multi-Subs].mkv', 'Judas'),
        ('[Erai-raws] Dandadan - 04 [1080p][Multiple Subtitle].mkv', 'Erai-raws'),
        ('[EMBER] Solo Leveling - 01 (1080p) [Dual-Audio].mkv', 'EMBER'),
        ('[CRUCiBLE] Dungeon Meshi - 12 [1080p].mkv', 'CRUCiBLE'),
        ('[Yameii] Kusuriya no Hitorigoto - 08 [WEB-DL 1080p].mkv', 'Yameii'),
        ('[ToonsHub] Sakamoto Days - 01 [1080p].mkv', 'ToonsHub'),
        ('[Anime Time] Bleach TYBW - 01 [1080p][HEVC].mkv', 'Anime Time'),
        ('[BD][Judas] Fullmetal Alchemist Brotherhood - 01 [1080p][HEVC].mkv', 'Judas'),
        ('[1080p][Dual-Audio][SubsPlease] Frieren - 02.mkv', 'SubsPlease'),
        ('Sousou.no.Frieren.S01E01.1080p.WEB-DL.H.264-VARYG.mkv', 'VARYG'),
        ('Dandadan.S01E03.1080p.CR.WEB-DL.AAC2.0.H264-ToonsHub [DEADBEEF].mkv', 'ToonsHub'),
    ],
)
def test_extract_release_group_happy(title, expected):
    assert source_utils.extract_release_group(title) == expected
    assert source_utils.normalize_release_group(expected) == expected.lower()


@pytest.mark.parametrize(
    'title',
    [
        '',
        None,
        '   ',
        '[1080p] Sousou no Frieren - 01.mkv',
        '[HEVC] [10bit] [Dual-Audio] Show - 02.mkv',
        '[A1B2C3D4] Show - 03 [720p].mkv',
        '[Multi-Sub][Batch][BD] Complete Series.mkv',
        '[BDMV] Cowboy Bebop Complete Box [1080p].mkv',
        '[JP-EN] Naruto Shippuden - 01.mkv',
        '[WEB-DL] Show - 01 (1080p) [1234ABCD].mkv',
        'Show - 01 [1080p].mkv',
        'Re:Zero - Starting Life in Another World - 01.mkv',
        'Attack on Titan - The Final Season - Part 2 - 12.mkv',
        'Show.Name.S01E01.1080p.WEB-DL.mkv',
        'Show.Name.S01E01.1080p.Dual-Audio.mkv',
        '[1080p HEVC 10bit] Plain Title.mkv',
        'Plain Title Without Any Group Tag.mkv',
    ],
)
def test_extract_release_group_negative_and_edge_cases(title):
    assert source_utils.extract_release_group(title) == ''


def test_preconfigured_catalog_and_csv_helpers():
    assert len(source_utils.PRECONFIGURED_RELEASE_GROUPS) == 40
    for grp in ('SubsPlease', 'EMBER', 'Yameii', 'Erai-raws', 'ToonsHub', 'ASW', 'Anime Time', 'Judas', 'VARYG', 'YuiSubs'):
        assert grp in source_utils.PRECONFIGURED_RELEASE_GROUPS

    assert source_utils.parse_release_groups('SubsPlease, [Erai-raws]; subsplease, EMBER, ') == [
        'SubsPlease', 'Erai-raws', 'EMBER',
    ]
    assert source_utils.format_release_groups_csv(['SubsPlease', 'subsplease', 'EMBER']) == 'SubsPlease, EMBER'
    assert source_utils.parse_excluded_groups('Judas, EMBER; [Erai-raws], ,') == {'judas', 'ember', 'erai-raws'}
    assert source_utils.parse_release_groups('') == []
    assert source_utils.parse_release_group_set(None) == set()


# ─── 2. SQLite Schema Migration & Multi-Group CRUD ───────────────────────────

def test_schema_migration_1016_to_1017_preserves_existing_rows(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            'CREATE TABLE series_overrides ('
            'mal_id INTEGER PRIMARY KEY, audio_lang TEXT, sub_lang TEXT, sub_mode TEXT, '
            'preferred_provider TEXT, intro_offset_s INTEGER DEFAULT 0, outro_offset_s INTEGER DEFAULT 0, '
            'episode_offset INTEGER DEFAULT 0, sub_offset_ms INTEGER DEFAULT 0, '
            'skip_filler_mode TEXT DEFAULT "default", updated_at INTEGER NOT NULL)'
        )
        conn.execute(
            'INSERT INTO series_overrides (mal_id, audio_lang, sub_offset_ms, updated_at) '
            'VALUES (52991, "jpn", 250, 1700000000)'
        )
        conn.commit()
    finally:
        conn.close()

    assert SyncDatabase.SCHEMA_VERSION == '1.0.17'
    SyncDatabase._ensure_column_migrations()

    row = database.get_series_override(52991)
    assert row is not None
    assert row['audio_lang'] == 'jpn'
    assert row['sub_offset_ms'] == 250
    assert row['preferred_group'] == ''
    assert row['excluded_groups'] == ''

    # Multi-group pinning appends cleanly without clobbering existing groups or offsets
    assert database.pin_series_release_group(52991, 'SubsPlease') is True
    assert database.pin_series_release_group(52991, 'Erai-raws') is True
    updated = database.get_series_override(52991)
    assert updated['preferred_group'] == 'SubsPlease, Erai-raws'
    assert updated['audio_lang'] == 'jpn'

    # Unpinning one group preserves the other
    assert database.unpin_series_release_group(52991, 'SubsPlease') is True
    assert database.get_series_override(52991)['preferred_group'] == 'Erai-raws'

    # Unrelated set_series_override preserves preferred_group
    assert database.set_series_override(52991, audio_lang='eng', sub_offset_ms=500) is True
    assert database.get_series_override(52991)['preferred_group'] == 'Erai-raws'


def test_multi_group_mutual_exclusivity_and_invalid_ids(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    assert database.pin_series_release_group('', 'SubsPlease') is False
    assert database.pin_series_release_group('abc', 'SubsPlease') is False
    assert database.unpin_series_release_group('notanint') is False
    assert database.exclude_series_release_group('abc', 'Judas') is False
    assert database.exclude_series_release_group(52991, '') is False

    assert database.exclude_series_release_group(52991, 'Judas') is True
    assert database.exclude_series_release_group(52991, 'EMBER') is True
    assert database.pin_series_release_group(52991, 'SubsPlease') is True
    assert database.pin_series_release_group(52991, 'Judas') is True
    row = database.get_series_override(52991)
    assert source_utils.parse_release_group_set(row['preferred_group']) == {'subsplease', 'judas'}
    assert source_utils.parse_release_group_set(row['excluded_groups']) == {'ember'}

    # Excluding Judas strips only Judas from preferred_group while keeping SubsPlease
    assert database.exclude_series_release_group(52991, 'Judas') is True
    row = database.get_series_override(52991)
    assert row['preferred_group'] == 'SubsPlease'
    assert source_utils.parse_release_group_set(row['excluded_groups']) == {'ember', 'judas'}


def test_settings_manager_export_import_preserves_multi_release_groups(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    database.set_series_override(
        52991,
        audio_lang='jpn',
        preferred_group='SubsPlease, Erai-raws',
        excluded_groups='Judas, EMBER',
    )

    ok, export_file, _ = settings_manager.export_settings('all', str(tmp_path))
    assert ok is True
    with open(export_file, 'r', encoding='utf-8') as fp:
        exported = json.load(fp)
    assert exported['series_overrides'][0]['preferred_group'] == 'SubsPlease, Erai-raws'
    assert exported['series_overrides'][0]['excluded_groups'] == 'Judas, EMBER'

    database.delete_series_override(52991)
    ok_imp, _ = settings_manager.import_settings('settings', export_file)
    assert ok_imp is True
    restored = database.get_series_override(52991)
    assert restored['preferred_group'] == 'SubsPlease, Erai-raws'
    assert restored['excluded_groups'] == 'Judas, EMBER'


# ─── 3. sortSources(): Multi-Group Tie-Break + Global Sort & Filter ──────────

def _make_torrent(title, quality=3, size='1.40 GB', byte_size=1500000000, relevance=160, provider='nyaa'):
    return {
        'release_title': title,
        'hash': f'hash_{abs(hash(title)) % 100000}',
        'type': 'torrent',
        'quality': quality,
        'debrid_provider': 'Real-Debrid',
        'provider': provider,
        'size': size,
        'seeders': 50,
        'byte_size': byte_size,
        'info': ['1080p', 'SUB'],
        'lang': 0,
        'cached': True,
        'relevance': relevance,
    }


def _configure_sort_defaults():
    control.setInt('general.minResolution', 0)
    control.setInt('general.maxResolution', 4)
    control.setInt('general.fileFilter', 0)
    control.setInt('general.source', 0)
    control.setBool('general.release_title_filter.enabled', False)
    control.setSetting('general.release_group.preferred', '')
    control.setSetting('general.release_group.excluded', '')
    control.setInt('general.release_group.tiebreak', 0)


def test_sort_sources_global_defaults_empty_and_strict_tiebreak_vs_equal_boost(tmp_path, monkeypatch):
    _configure_sort_defaults()
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    # Global preferred: SubsPlease (first), Erai-raws (second)
    # Erai-raws is 4K (larger/higher res), SubsPlease is 1080p, ToonsHub is non-preferred 4K
    t_toons_4k = _make_torrent('[ToonsHub] Frieren - 01 [2160p].mkv', quality=4, byte_size=3 * 10**9, relevance=160)
    t_erai_4k = _make_torrent('[Erai-raws] Frieren - 01 [2160p].mkv', quality=4, byte_size=28 * 10**8, relevance=155)
    t_subs_1080 = _make_torrent('[SubsPlease] Frieren - 01 [1080p].mkv', quality=3, byte_size=14 * 10**8, relevance=150)
    t_subs_tier1 = _make_torrent('[SubsPlease] Frieren OVA - 01 [1080p].mkv', quality=4, byte_size=20 * 10**8, relevance=110)

    control.setSetting('general.release_group.preferred', 'SubsPlease, Erai-raws')

    # Mode 0 (Equal Boost): both preferred Tier 0 groups beat ToonsHub 4K, and Erai-raws 4K beats SubsPlease 1080p by quality
    control.setInt('general.release_group.tiebreak', 0)
    res_eq = Sources.__new__(Sources).sortSources([t_toons_4k, t_subs_1080, t_erai_4k, t_subs_tier1], [], [], [], [], 'episode', 24)
    assert [r['release_title'] for r in res_eq] == [
        t_erai_4k['release_title'],
        t_subs_1080['release_title'],
        t_toons_4k['release_title'],
        t_subs_tier1['release_title'],
    ]

    # Mode 1 (Strict Selection Order): SubsPlease (idx 0) ranks strictly ahead of Erai-raws (idx 1), still inside Tier 0
    control.setInt('general.release_group.tiebreak', 1)
    res_ord = Sources.__new__(Sources).sortSources([t_toons_4k, t_subs_1080, t_erai_4k, t_subs_tier1], [], [], [], [], 'episode', 24)
    assert [r['release_title'] for r in res_ord] == [
        t_subs_1080['release_title'],
        t_erai_4k['release_title'],
        t_toons_4k['release_title'],
        t_subs_tier1['release_title'],
    ]


def test_sort_sources_per_series_preferred_overrides_global_exclusion_and_safe_fallback(tmp_path, monkeypatch):
    _configure_sort_defaults()
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    control.setSetting('general.release_group.excluded', 'Judas, EMBER')
    database.pin_series_release_group(52991, 'Judas')

    t_judas = _make_torrent('[Judas] Frieren - 01 (1080p).mkv', relevance=160)
    t_ember = _make_torrent('[EMBER] Frieren - 01 (1080p).mkv', relevance=160)
    t_subs = _make_torrent('[SubsPlease] Frieren - 01 (1080p).mkv', relevance=160)

    ranked = Sources.__new__(Sources).sortSources([t_ember, t_subs, t_judas], [], [], [], [], 'episode', 24, mal_id='52991')
    # Global exclusion drops EMBER, while per-series pin overrides global exclusion for Judas and ranks it #1
    assert [r['release_title'] for r in ranked] == [t_judas['release_title'], t_subs['release_title']]

    # When ALL candidates are excluded and not series-pinned, safely fall back to unfiltered pool
    control.setSetting('general.release_group.excluded', 'SubsPlease')
    fallback = Sources.__new__(Sources).sortSources([t_subs], [], [], [], [], 'episode', 24)
    assert [r['release_title'] for r in fallback] == [t_subs['release_title']]


# ─── 4. SeriesProfileDialog Multi-Select & Badge Truncation ──────────────────

def test_series_profile_dialog_multiselect_custom_and_mutual_exclusivity(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    assert len(series_profile._FIELD_SPECS) == 11
    assert series_profile._FIELD_SPECS[9]['kind'] == 'release_groups'
    assert series_profile._FIELD_SPECS[10]['kind'] == 'release_groups'

    with KodiProfile('22', strict_skin_controls=True):
        dlg = series_profile.SeriesProfileDialog('series_profile.xml', control.ADDON_PATH, mal_id='52991')
        dlg.onInit()
        assert dlg.list_control.size() == 11

        # 1. Multi-select 3 preferred groups (indices 0, 1, 2 -> SubsPlease, EMBER, Yameii) -> badge truncates cleanly
        monkeypatch.setattr(control, 'select_dialog', lambda *a, **k: 0)
        monkeypatch.setattr(control, 'multiselect_dialog', lambda heading, labels, preselect=None: [0, 1, 2])
        dlg.edit_field(idx=9)
        assert dlg.values['preferred_group'] == 'SubsPlease, EMBER, Yameii'
        assert dlg.list_control.getListItem(9).getProperty('value_badge') == 'SubsPlease, EMBER (+1 more)'

        # 2. Add custom release group via input dialog ("Add Custom Release Group(s)...")
        monkeypatch.setattr(control, 'select_dialog', lambda *a, **k: 1)
        monkeypatch.setattr(control, 'input_dialog', lambda *a, **k: 'SubsPlease, EMBER, CustomGroup')
        dlg.edit_field(idx=9)
        assert dlg.values['preferred_group'] == 'SubsPlease, EMBER, CustomGroup'

        # 3. Exclude EMBER via multi-select -> automatically strips EMBER from preferred_group and updates both rows
        monkeypatch.setattr(control, 'select_dialog', lambda *a, **k: 0)
        ember_idx = next(
            i for i, (g, _l) in enumerate(series_profile._build_release_group_choices(''))
            if g == 'EMBER'
        )
        monkeypatch.setattr(control, 'multiselect_dialog', lambda heading, labels, preselect=None: [ember_idx])
        dlg.edit_field(idx=10)
        assert dlg.values['excluded_groups'] == 'EMBER'
        assert dlg.values['preferred_group'] == 'SubsPlease, CustomGroup'
        assert dlg.list_control.getListItem(9).getProperty('value_badge') == 'SubsPlease, CustomGroup'

        dlg.save_and_close()
        assert dlg._win_closed is True

    saved = database.get_series_override(52991)
    assert saved['preferred_group'] == 'SubsPlease, CustomGroup'
    assert saved['excluded_groups'] == 'EMBER'


# ─── 5. Settings > Sort & Filter Route & Context Menu Cleanup ────────────────

def test_select_release_groups_route_and_context_seriesprofile_toggle(monkeypatch):
    _configure_sort_defaults()
    notifies = []
    monkeypatch.setattr(control, 'notify', lambda *a, **k: notifies.append(a))
    monkeypatch.setattr(control, 'exit_code', lambda: None)

    monkeypatch.setattr(control, 'select_dialog', lambda *a, **k: 0)
    monkeypatch.setattr(control, 'multiselect_dialog', lambda heading, labels, preselect=None: [0, 3])  # SubsPlease, Erai-raws
    tools_routes.SELECT_RELEASE_GROUPS('preferred', {})
    assert control.getSetting('general.release_group.preferred') == 'SubsPlease, Erai-raws'

    # Selecting SubsPlease in excluded removes it from global preferred automatically
    monkeypatch.setattr(control, 'multiselect_dialog', lambda heading, labels, preselect=None: [0])
    tools_routes.SELECT_RELEASE_GROUPS('excluded', {})
    assert control.getSetting('general.release_group.excluded') == 'SubsPlease'
    assert control.getSetting('general.release_group.preferred') == 'Erai-raws'

    # Context menu cleanup: 18 items, pinreleasegroup removed, seriesprofile toggled by setting
    root = ET.parse(CONTEXT_ADDON_XML).getroot()
    assert [el.attrib.get('addon') for el in root.findall('./requires/import')] == ['xbmc.python']
    items = root.findall('./extension[@point="kodi.context.item"]/menu/item')
    assert len(items) == 18
    args = [i.attrib.get('args') for i in items]
    assert 'pinreleasegroup' not in args
    assert 'seriesprofile' in args

    with open(SETTINGS_XML, 'r', encoding='utf-8') as fp:
        settings_text = fp.read()
    assert 'context.otaku.pinreleasegroup' not in settings_text
    assert 'context.otaku.seriesprofile' in settings_text
    assert 'general.release_group.preferred' in settings_text
    assert 'general.release_group.excluded' in settings_text
    assert 'general.release_group.tiebreak' in settings_text

    control.setBool('context.otaku.seriesprofile', False)
    control.process_context()
    assert control.homeWindow.getProperty('context.otaku.rpdev.seriesprofile') == 'false'
    control.setBool('context.otaku.seriesprofile', True)
    control.process_context()
    assert control.homeWindow.getProperty('context.otaku.rpdev.seriesprofile') == 'true'


def test_source_select_context_multi_pin_and_unpin_in_place(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()
    database.pin_series_release_group(52991, 'Erai-raws')

    sources = [
        _make_torrent('[SubsPlease] Frieren - 01 (1080p).mkv'),
        _make_torrent('[Erai-raws] Frieren - 01 (1080p).mkv'),
    ]
    with KodiProfile('22', strict_skin_controls=True):
        dlg = source_select.SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs={'mal_id': '52991'}, sources=sources)
        dlg.onInit()
        reset_spy = MagicMock(side_effect=AssertionError("list_control.reset() must NOT be called"))
        monkeypatch.setattr(dlg.display_list, 'reset', reset_spy)
        dlg.display_list.selectItem(0)

        monkeypatch.setattr(control, 'context_menu', lambda opts: 3)  # Pin Release Group: SubsPlease
        action = MagicMock()
        action.getId.return_value = 117
        dlg.onAction(action)
        assert database.get_series_override(52991)['preferred_group'] == 'Erai-raws, SubsPlease'

        # Unpinning SubsPlease removes ONLY SubsPlease, keeping Erai-raws
        dlg.onAction(action)
        assert database.get_series_override(52991)['preferred_group'] == 'Erai-raws'
        reset_spy.assert_not_called()
