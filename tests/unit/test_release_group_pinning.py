# -*- coding: utf-8 -*-
"""Track A unit tests: Per-Series Release-Group Pinning & Exclusion."""

import importlib.util
import json
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

from resources.lib.pages import Sources
from resources.lib.routes import tools as tools_routes
from resources.lib.ui import control, database, settings_manager, source_utils
from resources.lib.ui.database_sync import SyncDatabase
from resources.lib.windows import series_profile, source_select
from tests.kodi_profile import KodiProfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTEXT_ADDON_XML = os.path.join(REPO_ROOT, 'context.otaku.rpdev', 'addon.xml')
CONTEXT_DEFAULT_PY = os.path.join(REPO_ROOT, 'context.otaku.rpdev', 'default.py')


# ─── 1. Deterministic Release-Group Extraction (Happy + Negative/Edge) ───────

@pytest.mark.parametrize(
    'title,expected',
    [
        ('[SubsPlease] Sousou no Frieren - 01 (1080p) [A1B2C3D4].mkv', 'SubsPlease'),
        ('[Judas] Jujutsu Kaisen - S02E05 [1080p][HEVC x265 10bit][Multi-Subs].mkv', 'Judas'),
        ('[Erai-raws] Dandadan - 04 [1080p][Multiple Subtitle].mkv', 'Erai-raws'),
        ('[EMBER] Solo Leveling - 01 (1080p) [Dual-Audio].mkv', 'EMBER'),
        ('[CRUCiBLE] Dungeon Meshi - 12 [1080p].mkv', 'CRUCiBLE'),
        ('[Yameii] Kusuriya no Hitorigoto - 08 [WEB-DL 1080p].mkv', 'Yameii'),
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


def test_normalize_and_parse_excluded_groups_edge_cases():
    assert source_utils.normalize_release_group('  [SubsPlease]  ') == 'subsplease'
    assert source_utils.normalize_release_group('(Erai-raws)') == 'erai-raws'
    assert source_utils.normalize_release_group('') == ''
    assert source_utils.normalize_release_group(None) == ''
    assert source_utils.parse_excluded_groups('Judas, EMBER; [Erai-raws], ,') == {'judas', 'ember', 'erai-raws'}
    assert source_utils.parse_excluded_groups('') == set()
    assert source_utils.parse_excluded_groups(None) == set()


# ─── 2. SQLite Schema Migration (1.0.16 -> 1.0.17) & Non-Clobbering CRUD ─────

def test_schema_migration_1016_to_1017_preserves_existing_rows(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    # Build legacy v1.0.16 series_overrides table WITHOUT preferred_group / excluded_groups
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

    # Pinning a group preserves audio_lang & sub_offset_ms
    assert database.pin_series_release_group(52991, 'SubsPlease') is True
    updated = database.get_series_override(52991)
    assert updated['preferred_group'] == 'SubsPlease'
    assert updated['audio_lang'] == 'jpn'
    assert updated['sub_offset_ms'] == 250

    # Updating unrelated field with preferred_group=None does NOT clobber pinned group
    assert database.set_series_override(52991, audio_lang='eng', sub_offset_ms=500) is True
    preserved = database.get_series_override(52991)
    assert preserved['preferred_group'] == 'SubsPlease'
    assert preserved['audio_lang'] == 'eng'
    assert preserved['sub_offset_ms'] == 500


def test_pin_and_exclude_mutual_exclusivity_and_invalid_ids(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    # Invalid mal_id rejection
    assert database.pin_series_release_group('', 'SubsPlease') is False
    assert database.pin_series_release_group('abc', 'SubsPlease') is False
    assert database.unpin_series_release_group('notanint') is False
    assert database.exclude_series_release_group('abc', 'Judas') is False
    assert database.exclude_series_release_group(52991, '') is False

    # Pinning clears from excluded_groups; excluding clears matching preferred_group
    assert database.exclude_series_release_group(52991, 'Judas') is True
    assert database.exclude_series_release_group(52991, 'EMBER') is True
    row = database.get_series_override(52991)
    assert source_utils.parse_excluded_groups(row['excluded_groups']) == {'judas', 'ember'}

    assert database.pin_series_release_group(52991, 'Judas') is True
    row = database.get_series_override(52991)
    assert row['preferred_group'] == 'Judas'
    assert source_utils.parse_excluded_groups(row['excluded_groups']) == {'ember'}

    assert database.exclude_series_release_group(52991, 'Judas') is True
    row = database.get_series_override(52991)
    assert row['preferred_group'] == ''
    assert source_utils.parse_excluded_groups(row['excluded_groups']) == {'ember', 'judas'}

    assert database.exclude_series_release_group(52991, 'Judas', remove=True) is True
    row = database.get_series_override(52991)
    assert source_utils.parse_excluded_groups(row['excluded_groups']) == {'ember'}


def test_settings_manager_export_import_preserves_release_groups(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    database.set_series_override(
        52991,
        audio_lang='jpn',
        preferred_group='SubsPlease',
        excluded_groups='Judas, EMBER',
    )

    ok, export_file, _ = settings_manager.export_settings('all', str(tmp_path))
    assert ok is True
    with open(export_file, 'r', encoding='utf-8') as fp:
        exported = json.load(fp)
    assert exported['series_overrides'][0]['preferred_group'] == 'SubsPlease'
    assert exported['series_overrides'][0]['excluded_groups'] == 'Judas, EMBER'

    database.delete_series_override(52991)
    assert database.get_series_override(52991) is None

    ok_imp, _ = settings_manager.import_settings('settings', export_file)
    assert ok_imp is True
    restored = database.get_series_override(52991)
    assert restored is not None
    assert restored['preferred_group'] == 'SubsPlease'
    assert restored['excluded_groups'] == 'Judas, EMBER'


# ─── 3. sortSources() Intra-Tier Pinning & Safe Exclusion ────────────────────

def _make_torrent(title, quality=3, size='1.40 GB', relevance=160, provider='nyaa'):
    return {
        'release_title': title,
        'hash': f'hash_{abs(hash(title)) % 100000}',
        'type': 'torrent',
        'quality': quality,
        'debrid_provider': 'Real-Debrid',
        'provider': provider,
        'size': size,
        'seeders': 50,
        'byte_size': 1500000000,
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


def test_sort_sources_pinned_group_boosts_intra_tier_only(tmp_path, monkeypatch):
    _configure_sort_defaults()
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()
    database.pin_series_release_group(52991, 'Erai-raws')

    t_other_tier0 = _make_torrent('[SubsPlease] Frieren - 01 (1080p).mkv', quality=3, relevance=160)
    t_pinned_tier0 = _make_torrent('[Erai-raws] Frieren - 01 (1080p).mkv', quality=3, relevance=150)
    t_pinned_tier1 = _make_torrent('[Erai-raws] Frieren OVA - 01 (1080p).mkv', quality=4, relevance=110)

    src = Sources.__new__(Sources)
    result = src.sortSources(
        [t_other_tier0, t_pinned_tier0, t_pinned_tier1],
        [],
        [],
        [],
        [],
        'episode',
        24,
        mal_id='52991',
    )
    # Pinned Tier 0 ranks #1, non-pinned Tier 0 stays #2 (not dropped for failover), Tier 1 stays below Tier 0
    assert len(result) == 3
    assert result[0]['release_title'] == t_pinned_tier0['release_title']
    assert result[1]['release_title'] == t_other_tier0['release_title']
    assert result[2]['release_title'] == t_pinned_tier1['release_title']


def test_sort_sources_pinned_derivative_never_outranks_tier0_exact(tmp_path, monkeypatch):
    _configure_sort_defaults()
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()
    database.pin_series_release_group(19, 'Judas')

    t_exact = _make_torrent('[SubsPlease] Monster - 01 (1080p).mkv', quality=3, relevance=160)
    t_pinned_tier1 = _make_torrent('[Judas] Monster Special - 01 (1080p).mkv', quality=3, relevance=115)

    src = Sources.__new__(Sources)
    result = src.sortSources([t_pinned_tier1, t_exact], [], [], [], [], 'episode', 24, mal_id='19')
    assert result[0]['release_title'] == t_exact['release_title']
    assert result[1]['release_title'] == t_pinned_tier1['release_title']


def test_sort_sources_excluded_groups_filters_and_falls_back_when_pool_emptied(tmp_path, monkeypatch):
    _configure_sort_defaults()
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()
    database.exclude_series_release_group(52991, 'Judas')

    t_judas = _make_torrent('[Judas] Frieren - 01 (1080p).mkv', relevance=160)
    t_subs = _make_torrent('[SubsPlease] Frieren - 01 (1080p).mkv', relevance=160)

    src = Sources.__new__(Sources)
    # When alternative exists, Judas is filtered out
    filtered = src.sortSources([t_judas, t_subs], [], [], [], [], 'episode', 24, mal_id='52991')
    assert [s['release_title'] for s in filtered] == [t_subs['release_title']]

    # When ALL candidates are excluded, safely fall back to unfiltered pool (never empty!)
    fallback = src.sortSources([t_judas], [], [], [], [], 'episode', 24, mal_id='52991')
    assert [s['release_title'] for s in fallback] == [t_judas['release_title']]


# ─── 4. SeriesProfileDialog (11 rows, Kodi 22 strict) & SourceSelect Context ─

def test_series_profile_dialog_11_rows_kodi22_strict_and_close_order(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    assert len(series_profile._FIELD_SPECS) == 11
    keys = [s['key'] for s in series_profile._FIELD_SPECS]
    assert 'preferred_group' in keys
    assert 'excluded_groups' in keys

    with KodiProfile('22', strict_skin_controls=True):
        dlg = series_profile.SeriesProfileDialog('series_profile.xml', control.ADDON_PATH, mal_id='52991')
        dlg.onInit()
        assert dlg.list_control.size() == 11

        close_order = []
        orig_close = dlg.close

        def _spy_close():
            close_order.append(('close', dlg._win_closed))
            orig_close()

        monkeypatch.setattr(dlg, 'close', _spy_close)
        monkeypatch.setattr(control, 'select_dialog', lambda *a, **k: 0)
        monkeypatch.setattr(control, 'input_dialog', lambda *a, **k: 'SubsPlease')
        dlg.edit_field(idx=9)  # preferred_group
        assert dlg.values['preferred_group'] == 'SubsPlease'
        assert dlg.list_control.getListItem(9).getProperty('value_badge') == 'SubsPlease'

        monkeypatch.setattr(control, 'input_dialog', lambda *a, **k: 'Judas, EMBER')
        dlg.edit_field(idx=10)  # excluded_groups
        assert dlg.values['excluded_groups'] == 'Judas, EMBER'

        dlg.save_and_close()
        assert close_order == [('close', False)]
        assert dlg._win_closed is True

    saved = database.get_series_override(52991)
    assert saved['preferred_group'] == 'SubsPlease'
    assert saved['excluded_groups'] == 'Judas, EMBER'


def test_source_select_context_pin_and_exclude_in_place_no_reset(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    sources = [
        _make_torrent('[SubsPlease] Frieren - 01 (1080p).mkv'),
        _make_torrent('[Judas] Frieren - 01 (1080p).mkv'),
    ]
    with KodiProfile('22', strict_skin_controls=True):
        dlg = source_select.SourceSelect(
            'source_select.xml',
            control.ADDON_PATH,
            actionArgs={'mal_id': '52991'},
            sources=sources,
        )
        dlg.onInit()
        assert dlg.display_list.size() == 2
        assert dlg.display_list.getListItem(0).getProperty('release_group') == 'SubsPlease'

        reset_spy = MagicMock(side_effect=AssertionError("list_control.reset() must NOT be called on Pin/Exclude"))
        monkeypatch.setattr(dlg.display_list, 'reset', reset_spy)
        dlg.display_list.selectItem(0)

        # Action 117 -> choose index 3 ("Pin Release Group: SubsPlease")
        captured_menus = []

        def _fake_ctx(opts):
            captured_menus.append(list(opts))
            return 3

        monkeypatch.setattr(control, 'context_menu', _fake_ctx)
        action = MagicMock()
        action.getId.return_value = 117
        dlg.onAction(action)

        assert any('Pin Release Group: SubsPlease' in o for o in captured_menus[-1])
        assert database.get_series_override(52991)['preferred_group'] == 'SubsPlease'
        assert dlg.display_list.getListItem(0).getProperty('group_pin_status') == 'pinned'
        reset_spy.assert_not_called()

        # Re-open context menu -> now offers Unpin at index 3 and Exclude at index 4
        monkeypatch.setattr(control, 'context_menu', lambda opts: (captured_menus.append(list(opts)) or 4))
        dlg.onAction(action)
        assert any('Unpin Release Group: SubsPlease' in o for o in captured_menus[-1])
        assert database.get_series_override(52991)['preferred_group'] == ''
        assert 'subsplease' in source_utils.parse_excluded_groups(
            database.get_series_override(52991)['excluded_groups']
        )
        assert dlg.display_list.getListItem(0).getProperty('group_pin_status') == 'excluded'
        reset_spy.assert_not_called()


# ─── 5. Route pin_release_group/*, process_context() & context.otaku.rpdev ──

def test_pin_release_group_route_happy_and_invalid_mal_id(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'malSync.db')
    monkeypatch.setattr(control, 'malSyncDB', db_path)
    database._tables_ready.clear()

    notifies = []
    monkeypatch.setattr(control, 'notify', lambda *a, **k: notifies.append(a))
    monkeypatch.setattr(control, 'exit_code', lambda: None)

    # Invalid mal_id -> clean no-op toast
    tools_routes.PIN_RELEASE_GROUP('invalid/abc', {})
    assert any('No anime MAL ID' in str(n) for n in notifies)

    # Valid mal_id -> custom pin via dialog
    monkeypatch.setattr(control, 'select_dialog', lambda heading, opts: 0)  # Enter Release Group Name...
    monkeypatch.setattr(control, 'input_dialog', lambda *a, **k: 'EMBER')
    tools_routes.PIN_RELEASE_GROUP('52991/', {})
    assert database.get_series_override(52991)['preferred_group'] == 'EMBER'


def test_context_addon_xml_and_default_py_pinreleasegroup(monkeypatch):
    root = ET.parse(CONTEXT_ADDON_XML).getroot()
    # Acyclic DAG invariant: imports ONLY xbmc.python
    imports = [el.attrib.get('addon') for el in root.findall('./requires/import')]
    assert imports == ['xbmc.python']

    items = root.findall('./extension[@point="kodi.context.item"]/menu/item')
    assert len(items) == 19
    pin_item = next((i for i in items if i.attrib.get('args') == 'pinreleasegroup'), None)
    assert pin_item is not None
    vis = pin_item.findtext('visible') or ''
    assert 'Window(home).Property(context.otaku.rpdev.pinreleasegroup)' in vis
    assert 'ListItem.UniqueID(mal_id)' in vis
    assert 'ListItem.Property(mal_id)' in vis

    # process_context() caches context.otaku.rpdev.pinreleasegroup
    control.setBool('context.otaku.pinreleasegroup', False)
    control.process_context()
    assert control.homeWindow.getProperty('context.otaku.rpdev.pinreleasegroup') == 'false'
    control.setBool('context.otaku.pinreleasegroup', True)
    control.process_context()
    assert control.homeWindow.getProperty('context.otaku.rpdev.pinreleasegroup') == 'true'

    # Execute context.otaku.rpdev/default.py for Otaku path, widget item, and non-Otaku videodb://
    spec = importlib.util.spec_from_file_location('ctx_default_track_a', CONTEXT_DEFAULT_PY)
    ctx_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctx_mod)

    executed = []
    monkeypatch.setattr(ctx_mod.xbmc, 'executebuiltin', lambda cmd: executed.append(cmd))

    # 1. Valid Otaku plugin path
    li_ok = MagicMock()
    li_ok.getPath.return_value = 'plugin://plugin.video.otaku.rpdev/animes/52991/'
    li_ok.getProperty.return_value = ''
    monkeypatch.setattr(sys, 'argv', ['default.py', 'pinreleasegroup'])
    monkeypatch.setattr(sys, 'listitem', li_ok, raising=False)
    ctx_mod.main()
    assert executed[-1] == 'RunPlugin(plugin://plugin.video.otaku.rpdev/pin_release_group/52991)'

    # 2. External widget item carrying UniqueID(mal_id) / Property(mal_id)
    executed.clear()
    li_widget = MagicMock()
    li_widget.getPath.return_value = 'videodb://tvshows/titles/99/'
    li_widget.getProperty.side_effect = lambda k: '52991' if k == 'mal_id' else ''
    li_widget.getVideoInfoTag.return_value.getUniqueIDs.return_value = {}
    li_widget.getVideoInfoTag.return_value.getUniqueID.return_value = ''
    li_widget.getVideoInfoTag.return_value.getEpisode.return_value = 1
    monkeypatch.setattr(ctx_mod.xbmc, 'getInfoLabel', lambda lbl: '')
    monkeypatch.setattr(sys, 'listitem', li_widget, raising=False)
    ctx_mod.main()
    assert executed == ['RunPlugin(plugin://plugin.video.otaku.rpdev/pin_release_group/52991)']

    # 3. Non-Otaku videodb:// item with NO mal_id -> clean no-op
    executed.clear()
    li_foreign = MagicMock()
    li_foreign.getPath.return_value = 'videodb://movies/titles/42/'
    li_foreign.getProperty.return_value = ''
    li_foreign.getVideoInfoTag.return_value.getUniqueIDs.return_value = {}
    li_foreign.getVideoInfoTag.return_value.getUniqueID.return_value = ''
    monkeypatch.setattr(ctx_mod.xbmc, 'getInfoLabel', lambda lbl: '')
    monkeypatch.setattr(sys, 'listitem', li_foreign, raising=False)
    ctx_mod.main()
    assert executed == []
