# -*- coding: utf-8 -*-
"""Track C unit tests: Kodi 22 'Piers' Native API Integrations (NF-16, NF-15, HDR, Deep Links)."""

import json
import os
import time
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest
import xbmc
import xbmcgui

import service
from resources.lib import WatchlistIntegration
from resources.lib.routes import playback as playback_routes
from resources.lib.subtitles import meta as sub_meta
from resources.lib.ui import control, player as player_mod, source_utils
from resources.lib.windows import anichart, source_select
from tests.kodi_profile import KodiProfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANICHART_XML = os.path.join(
    REPO_ROOT, 'plugin.video.otaku.rpdev', 'resources', 'skins', 'Default', '1080i', 'anichart.xml'
)
DEFAULT_PY = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev', 'default.py')


# ─── 1. NF-16 Standby & CEC Background Throttling ───────────────────────────

def test_nf16_standby_kodi22_string_and_int_cec_codes(monkeypatch):
    control.setBool('general.standby_throttling', True)
    with KodiProfile('22'):
        assert control.get_cec_adapter_names() == ['HDMI-CEC Adapter 0']

        # Explicit ON must NOT fall back to screensaver even if screensaver is active
        monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda: 'on')
        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda cond: True)
        assert control.get_device_power_status() == 'on'
        assert control.is_device_in_standby() is False

        # String standby states
        for st in ('standby', 'suspend', 'sleep', 'off', 'in_transition_to_standby'):
            monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda s=st: s)
            assert control.is_device_in_standby() is True

        # Integer CEC power codes (0=on, 1=standby, 3=in_transition_to_standby)
        monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda: 0)
        assert control.is_device_in_standby() is False
        monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda: 1)
        assert control.is_device_in_standby() is True
        monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda: 3)
        assert control.is_device_in_standby() is True

        # Unknown power status falls back to DPMS/Screensaver
        monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda: 'unknown')
        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda cond: True)
        assert control.is_device_in_standby() is True

        # Disabled setting overrides everything to False
        control.setBool('general.standby_throttling', False)
        monkeypatch.setattr(xbmc, 'getDevicePowerStatus', lambda: 'standby')
        assert control.is_device_in_standby() is False
        control.setBool('general.standby_throttling', True)


def test_nf16_standby_kodi21_fallback_and_service_resume_catchup(monkeypatch):
    control.setBool('general.standby_throttling', True)
    with KodiProfile('21'):
        assert not hasattr(xbmc, 'getDevicePowerStatus')
        assert not hasattr(xbmc, 'getCecAdapterNames')
        assert control.get_cec_adapter_names() == []
        assert control.get_device_power_status() == 'on'

        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda cond: False)
        assert control.is_device_in_standby() is False
        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda cond: True)
        assert control.is_device_in_standby() is True

    # Test service periodic tick transition: active -> standby (logged once) -> standby (silent) -> resumed (drains OAuth/retry)
    metrics = []
    refreshed = []
    replayed = []
    from otaku_service import daemon as svc_daemon, sync as svc_sync
    monkeypatch.setattr(control, 'log_metric', lambda name, **kw: metrics.append((name, kw)))
    monkeypatch.setattr(svc_daemon, 'refresh_apis', lambda: refreshed.append(1))
    monkeypatch.setattr(control, 'enforce_memory_watermark', lambda **kw: {'triggered': False})
    monkeypatch.setattr(control, 'clean_memory', lambda: None)
    monkeypatch.setattr(svc_sync, '_maybe_sync_daily_mappings', lambda: None)
    from resources.lib.WatchlistFlavor import WatchlistFlavor
    monkeypatch.setattr(WatchlistFlavor, 'process_scrobble_retry_queue', classmethod(lambda cls: replayed.append(1) or 1))

    state = {'in_standby': False}
    monkeypatch.setattr(control, 'is_device_in_standby', lambda: True)
    monkeypatch.setattr(control, 'get_device_power_status', lambda: 'standby')
    assert service._run_periodic_maintenance_tick(standby_state=state) == 'throttled'
    assert service._run_periodic_maintenance_tick(standby_state=state) == 'throttled'
    # Only ONE standby_throttled metric logged across consecutive standby ticks; zero heavy work
    assert len([m for m in metrics if m[1].get('state') == 'standby_throttled']) == 1
    assert refreshed == [] and replayed == []

    # Transition back to active -> logs resumed and immediately triggers refresh_apis + retry queue drain
    monkeypatch.setattr(control, 'is_device_in_standby', lambda: False)
    monkeypatch.setattr(control, 'get_device_power_status', lambda: 'on')
    assert service._run_periodic_maintenance_tick(standby_state=state) == 'resumed'
    assert len([m for m in metrics if m[1].get('state') == 'resumed']) == 1
    assert len(refreshed) == 1
    assert len(replayed) == 1


# ─── 2. NF-15 AniChart Inline Trailer Previews ──────────────────────────────

def test_nf15_anichart_xml_has_no_defaultcontrol_and_valid_preview_controls():
    root = ET.parse(ANICHART_XML).getroot()
    # R-12/C-02 invariant: NO <defaultcontrol> element
    assert root.find('defaultcontrol') is None
    ids = {el.attrib.get('id') for el in root.iter('control') if 'id' in el.attrib}
    assert {'1000', '2050', '2051', '2052'}.issubset(ids)


def test_nf15_anichart_inline_trailer_kodi22_and_kodi21_fallback(monkeypatch):
    items = [
        {'release_title': 'Frieren', 'mal_id': 52991, 'trailer_url': 'https://cdn.example.com/frieren_pv.mp4'},
        {'release_title': 'Dandadan', 'mal_id': 57334, 'trailer_url': 'https://youtu.be/dQw4w9WgXcQ'},
    ]
    control.setBool('interface.anichart.inline_trailers', True)

    # Kodi 21: ControlVideoWindow absent -> clean no-op
    with KodiProfile('21'):
        assert not hasattr(xbmcgui, 'ControlVideoWindow')
        assert anichart._supports_inline_trailers() is False
        win21 = anichart.Anichart('anichart.xml', control.ADDON_PATH, anime_items=items)
        assert win21._start_inline_trailer(position=0) is False

    # Kodi 22: ControlVideoWindow present
    with KodiProfile('22'):
        assert anichart._supports_inline_trailers() is True

        # YouTube URL gated on System.HasAddon(plugin.video.youtube)
        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda c: False)
        assert anichart._resolve_preview_trailer_url(items[1]) == ''
        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda c: 'plugin.video.youtube' in c)
        assert anichart._resolve_preview_trailer_url(items[1]) == 'plugin://plugin.video.youtube/play/?video_id=dQw4w9WgXcQ'

        # Skip preview when user playback is already active
        playing_player = MagicMock()
        playing_player.isPlaying.return_value = True
        monkeypatch.setattr(xbmc, 'Player', lambda: playing_player)
        win_busy = anichart.Anichart('anichart.xml', control.ADDON_PATH, anime_items=items)
        assert win_busy._start_inline_trailer(position=0) is False
        playing_player.play.assert_not_called()

        # Normal preview start -> windowed=True, muted, otaku.preview_mode='true', suppresses scrobbler, restores mute on close
        idle_state = {'playing': False}
        play_calls = []
        stop_calls = []
        rpc_calls = []

        class _FakePlayer:
            def isPlaying(self):
                return idle_state['playing']

            def play(self, url, listitem=None, windowed=False):
                play_calls.append((url, windowed))
                idle_state['playing'] = True

            def stop(self):
                stop_calls.append(1)
                idle_state['playing'] = False

        monkeypatch.setattr(xbmc, 'Player', _FakePlayer)
        monkeypatch.setattr(xbmc, 'getCondVisibility', lambda c: False)
        monkeypatch.setattr(control, 'jsonrpc', lambda q: rpc_calls.append(q) or {})

        win22 = anichart.Anichart('anichart.xml', control.ADDON_PATH, anime_items=items)
        assert win22._start_inline_trailer(position=0) is True
        assert play_calls == [('https://cdn.example.com/frieren_pv.mp4', True)]
        assert control.getGlobalProp('otaku.preview_mode') == 'true'
        assert any(q.get('method') == 'Application.SetMute' and q['params']['mute'] is True for q in rpc_calls)

        # WatchlistPlayer callbacks are suppressed while preview_mode == 'true'
        wp = player_mod.WatchlistPlayer.__new__(player_mod.WatchlistPlayer)
        wp._playback_stopped = False
        wp.onPlayBackStopped()
        assert wp._playback_stopped is False

        # Close stops preview, clears preview_mode, restores mute=False, and sets _win_closed after super().close()
        win22.close()
        assert len(stop_calls) == 1
        assert control.getGlobalProp('otaku.preview_mode') == ''
        assert any(q.get('method') == 'Application.SetMute' and q['params']['mute'] is False for q in rpc_calls)
        assert win22._win_closed is True

        # Setting disabled -> no-op even on Kodi 22
        control.setBool('interface.anichart.inline_trailers', False)
        assert anichart._supports_inline_trailers() is False
        control.setBool('interface.anichart.inline_trailers', True)


# ─── 3. HDR Badge Surfacing (Kodi 21 & Kodi 22) ─────────────────────────────

@pytest.mark.parametrize(
    'title,expected_type,expected_badge',
    [
        ('[EMBER] Frieren - 01 [2160p][DV][HEVC].mkv', 'dolbyvision', 'DV'),
        ('Show.S01E01.2160p.DoVi.WEB-DL.mkv', 'dolbyvision', 'DV'),
        ('Movie.2024.Dolby.Vision.Remux.mkv', 'dolbyvision', 'DV'),
        ('[Judas] Movie [2160p][HDR10+][10bit].mkv', 'hdr10', 'HDR10'),
        ('[Judas] Movie [2160p][HDR10][10bit].mkv', 'hdr10', 'HDR10'),
        ('Show.S01E01.2160p.HLG.WEB-DL.mkv', 'hlg', 'HLG'),
        ('Show.S01E01.DVDRip.480p.DivX.avi', '', ''),
        ('Show.S01E01.DVD.720p.mkv', '', ''),
        ('Show.S01E01.HDRip.1080p.mkv', '', ''),
        ('', '', ''),
    ],
)
def test_detect_hdr_type_and_format_badge(title, expected_type, expected_badge):
    assert source_utils.detect_hdr_type(title) == expected_type
    assert source_utils.format_hdr_badge(expected_type) == expected_badge


@pytest.mark.parametrize('kodi_ver', ['21', '22'])
def test_set_videotags_hdr_kodi21_and_kodi22_never_parses_display_title(kodi_ver):
    with KodiProfile(kodi_ver):
        # 1. Generic anime display title with 'DV' / 'HDR' words MUST NOT trigger HDR detection
        li_plain = xbmcgui.ListItem(label='Plain')
        control.set_videotags(li_plain, {'title': 'DV Chronicles HDR Special', 'mediatype': 'episode'})
        assert li_plain.getProperty('hdr_type') == ''
        assert li_plain.getProperty('hdr_badge') == ''

        # 2. Explicit release_title with DV sets properties on both 21 & 22 and calls setHdrType on 22
        li_dv = xbmcgui.ListItem(label='DV Show')
        vinfo_dv = li_dv.getVideoInfoTag()
        control.set_videotags(
            li_dv,
            {'title': 'Episode 1', 'release_title': '[EMBER] Show - 01 [2160p][DV].mkv', 'mediatype': 'episode'},
        )
        assert li_dv.getProperty('hdr_type') == 'dolbyvision'
        assert li_dv.getProperty('hdr_badge') == 'DV'
        assert li_dv.getProperty('VideoResolution.HDRType') == 'dolbyvision'
        if kodi_ver == '22':
            assert vinfo_dv.getHdrType() == 3  # Kodi 22 enum: 3 = Dolby Vision
        else:
            assert not hasattr(vinfo_dv, 'setHdrType')

        # 3. Kodi 22 VideoStreamDetail.getHDRDetail() detection
        if kodi_ver == '22':
            detail = xbmc.VideoStreamDetail(3840, 2160, 'hevc', hdr_detail='hlg')
            assert source_utils.detect_hdr_type('', stream_info=detail) == 'hlg'


def test_source_select_surfaces_hdr_badges():
    sources = [
        {
            'release_title': '[EMBER] Frieren - 01 [2160p][DoVi][HEVC].mkv',
            'type': 'torrent',
            'debrid_provider': 'Real-Debrid',
            'provider': 'nyaa',
            'quality': 4,
            'info': ['HEVC'],
            'size': '4.2 GB',
            'seeders': 40,
            'cached': True,
        },
        {
            'release_title': '[Judas] Frieren - 01 [2160p][HLG].mkv',
            'type': 'torrent',
            'debrid_provider': 'Real-Debrid',
            'provider': 'nyaa',
            'quality': 4,
            'info': ['HEVC'],
            'size': '2.1 GB',
            'seeders': 20,
            'cached': True,
        },
    ]
    with KodiProfile('22', strict_skin_controls=True):
        dlg = source_select.SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs={'mal_id': '52991'}, sources=sources)
        dlg.onInit()
        assert dlg.display_list.getListItem(0).getProperty('hdr_type') == 'dolbyvision'
        assert dlg.display_list.getListItem(0).getProperty('hdr_badge') == 'DV'
        assert 'DV' in dlg.display_list.getListItem(0).getProperty('colored_hdr')
        assert dlg.display_list.getListItem(1).getProperty('hdr_type') == 'hlg'
        assert dlg.display_list.getListItem(1).getProperty('hdr_badge') == 'HLG'


# ─── 4. Android TV Deep Links & Stale VIEW Replay Guard ──────────────────────

def test_deeplink_in_no_delay_routes():
    with open(DEFAULT_PY, 'r', encoding='utf-8') as fp:
        src = fp.read()
    assert "'deeplink'" in src


def test_deeplink_next_up_handle_negative_and_positive_plus_replay_guard(monkeypatch):
    control.clearGlobalProp('otaku.last_deeplink_sig')
    control.clearGlobalProp('otaku.last_deeplink_ts')

    executed = []
    next_up_calls = []
    monkeypatch.setattr(control, 'execute', lambda cmd: executed.append(cmd))
    monkeypatch.setattr(control, 'exit_code', lambda: None)
    monkeypatch.setattr(WatchlistIntegration, 'NEXT_UP', lambda p, pr: next_up_calls.append((p, pr)))

    # 1. HANDLE < 0 (Android TV launcher / RunPlugin) -> ActivateWindow(Videos, ..., return)
    monkeypatch.setattr(control, 'HANDLE', -1)
    playback_routes.DEEPLINK('next_up', {})
    assert executed == [f"ActivateWindow(Videos,plugin://{control.ADDON_ID}/next_up,return)"]
    assert next_up_calls == []

    # 2. Immediate stale replay within < 10s -> ignored!
    playback_routes.DEEPLINK('next_up', {})
    assert len(executed) == 1

    # 3. After > 10s elapsed -> allowed; HANDLE >= 0 calls WatchlistIntegration.NEXT_UP directly
    control.setGlobalProp('otaku.last_deeplink_ts', f"{time.time() - 15.0:.3f}")
    monkeypatch.setattr(control, 'HANDLE', 1)
    playback_routes.DEEPLINK('next_up', {})
    assert len(next_up_calls) == 1

    # 4. Backwards NTP clock jump (last_ts in future) MUST NOT block fresh launch
    control.setGlobalProp('otaku.last_deeplink_ts', f"{time.time() + 3600.0:.3f}")
    playback_routes.DEEPLINK('next_up', {})
    assert len(next_up_calls) == 2


def test_deeplink_play_validation_active_playback_guard_and_movie_mode(monkeypatch):
    control.clearGlobalProp('otaku.last_deeplink_sig')
    control.clearGlobalProp('otaku.last_deeplink_ts')
    control.clearGlobalProp('otaku.mal_id')
    sub_meta.clear_active_playback_meta()

    play_calls = []
    movie_calls = []
    monkeypatch.setattr(playback_routes, 'PLAY', lambda p, pr: play_calls.append((p, dict(pr))))
    monkeypatch.setattr(playback_routes, 'PLAY_MOVIE', lambda p, pr: movie_calls.append((p, dict(pr))))
    monkeypatch.setattr(control, 'exit_code', lambda: None)

    fake_player = MagicMock()
    fake_player.isPlayingVideo.return_value = False
    monkeypatch.setattr(xbmc, 'Player', lambda: fake_player)

    # Malformed payloads -> cleanly rejected with zero playback calls
    for bad in ('', 'unknown/123', 'play/', 'play/abc/1', 'play/52991/notanep', 'play/52991'):
        playback_routes.DEEPLINK(bad, {})
    assert play_calls == [] and movie_calls == []

    # Valid episode deep link
    playback_routes.DEEPLINK('play/52991/4', {'source_select': 'true'})
    assert play_calls == [('52991/4', {'source_select': 'true'})]

    # Valid movie deep link (episode omitted when movie=true)
    playback_routes.DEEPLINK('play/32281', {'movie': 'true'})
    assert movie_calls == [('32281/', {'movie': 'true'})]

    # Active playback guard using real Window(10000) otaku.mal_id & otaku.active_sub_meta JSON
    control.clearGlobalProp('otaku.last_deeplink_sig')
    control.clearGlobalProp('otaku.last_deeplink_ts')
    fake_player.isPlayingVideo.return_value = True
    control.setGlobalProp('otaku.mal_id', '52991')
    control.setGlobalProp(sub_meta.ACTIVE_SUB_META_PROP, json.dumps({'mal_id': '52991', 'episode': '4'}))
    playback_routes.DEEPLINK('play/52991/4', {})
    # Rejected because MAL 52991 ep 4 is already actively playing
    assert len(play_calls) == 1

    # Different episode (ep 5) is allowed even while ep 4 is playing
    playback_routes.DEEPLINK('play/52991/5', {})
    assert len(play_calls) == 2

    control.clearGlobalProp('otaku.mal_id')
    sub_meta.clear_active_playback_meta()
