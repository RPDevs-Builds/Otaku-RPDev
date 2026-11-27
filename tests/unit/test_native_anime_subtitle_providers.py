# -*- coding: utf-8 -*-
"""Track B unit tests: Native Anime Subtitle Providers (Jimaku & AnimeTosho)."""

import gzip
import importlib.util
import json
import lzma
import os
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from resources.lib import subtitles
from resources.lib.subtitles import archive, download, search
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.subtitles.services import ALL_SERVICES
from resources.lib.subtitles.services.animetosho import AnimetoshoSubtitleService
from resources.lib.subtitles.services.jimaku import JimakuService
from resources.lib.ui import client, control, domains

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUB_ADDON_XML = os.path.join(REPO_ROOT, 'service.subtitles.otaku.rpdev', 'addon.xml')
SUB_SERVICE_PY = os.path.join(REPO_ROOT, 'service.subtitles.otaku.rpdev', 'service.py')

SAMPLE_ASS = (
    "[Script Info]\n"
    "Title: Frieren Ep 01\n"
    "ScriptType: v4.00+\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:05.00,0:00:08.50,Default,,0,0,0,,{\\pos(320,240)\\an8}[sighs] FRIEREN: The journey begins.\\N(applause)\n"
    "Dialogue: 0,0:00:10.00,0:00:13.00,Default,,0,0,0,,{\\fad(200,200)}Hello, Himmel.\n"
)


def _resp(status=200, json_data=None, content=b'', headers=None, text=None):
    if text is None and json_data is not None:
        text = json.dumps(json_data)
    elif text is None:
        text = ''
    return SimpleNamespace(
        status_code=status,
        text=text,
        content=content,
        headers=headers or {},
        json=lambda default=None: json_data if json_data is not None else default,
    )


# ─── 1. JimakuService Tests (Happy + Negative/Edge) ──────────────────────────

def test_jimaku_empty_apikey_makes_zero_network_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(client, 'get', lambda *a, **k: calls.append((a, k)))
    meta = VideoMeta(tvshow='Frieren', episode='1', languages=['Japanese'], preferred_lang='ja', anilist_id='154587')
    assert JimakuService.search(meta, {'subtitles.jimaku.apikey': ''}) == []
    assert JimakuService.search(meta, {}) == []
    assert calls == []


def test_jimaku_non_japanese_language_makes_zero_network_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(client, 'get', lambda *a, **k: calls.append((a, k)))
    meta = VideoMeta(tvshow='Frieren', episode='1', languages=['English'], preferred_lang='en', anilist_id='154587')
    assert JimakuService.search(meta, {'subtitles.jimaku.apikey': 'secret-key'}) == []
    assert calls == []


def test_jimaku_anilist_mal_kitsu_resolution_chain(monkeypatch):
    calls = []

    def _fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params or {}), dict(headers or {}), timeout))
        if url.endswith('/entries/search'):
            if params and params.get('anilist_id') == '154587':
                return _resp(200, json_data=[])
            if params and params.get('mal_id') == '52991':
                return _resp(200, json_data=[{'id': 4201, 'name': 'Sousou no Frieren'}])
        if url.endswith('/entries/4201/files'):
            return _resp(
                200,
                json_data=[
                    {'name': '[SubsPlease] Sousou no Frieren - 01.ja.ass', 'url': 'https://jimaku.cc/dl/1.ass'},
                    {'name': 'readme.txt', 'url': 'https://jimaku.cc/dl/readme.txt'},
                ],
            )
        return _resp(404)

    monkeypatch.setattr(client, 'get', _fake_get)
    meta = VideoMeta(
        tvshow='Sousou no Frieren',
        season='1',
        episode='1',
        languages=['Japanese'],
        preferred_lang='ja',
        mal_id='52991',
        anilist_id='154587',
    )
    results = JimakuService.search(meta, {'subtitles.jimaku.apikey': 'tok_123', 'subtitles.timeout': 10})
    assert len(results) == 1
    assert results[0].service_name == 'jimaku'
    assert results[0].lang_code == 'ja'
    assert results[0].release_group == 'SubsPlease'
    assert results[0].subtitle_format == 'ass'
    assert results[0].auto_identified is True
    assert results[0].is_anime_native is True
    # Auth header sent without Bearer prefix, float timeout enforced
    assert calls[0][2]['Authorization'] == 'tok_123'
    assert isinstance(calls[0][3], float)
    # Tried anilist_id first, fell back to mal_id, then fetched files?episode=1
    assert calls[0][1] == {'anilist_id': '154587'}
    assert calls[1][1] == {'mal_id': '52991'}
    assert calls[2][1] == {'episode': '1'}


def test_jimaku_fuzzy_title_rejects_derivatives(monkeypatch):
    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith('/entries/search'):
            return _resp(200, json_data=[{'id': 999, 'name': 'Re:Monster', 'english_name': 'Re:Monster'}])
        raise AssertionError('Should not fetch files for derivative entry')

    monkeypatch.setattr(client, 'get', _fake_get)
    meta = VideoMeta(tvshow='Monster', episode='1', languages=['Japanese'], preferred_lang='ja')
    assert JimakuService.search(meta, {'subtitles.jimaku.apikey': 'tok_123'}) == []


def test_jimaku_429_capped_retry_and_abort_handling(monkeypatch):
    waits = []
    monkeypatch.setattr(control.monitor, 'waitForAbort', lambda s: waits.append(s) or False)
    attempt = {'n': 0}

    def _fake_get(url, params=None, headers=None, timeout=None):
        attempt['n'] += 1
        if attempt['n'] == 1:
            return _resp(429, headers={'Retry-After': '99'})
        if url.endswith('/entries/search'):
            return _resp(200, json_data=[{'id': 77, 'name': 'Frieren'}])
        return _resp(200, json_data=[{'name': 'Frieren.01.srt', 'url': 'https://jimaku.cc/f/1.srt'}])

    monkeypatch.setattr(client, 'get', _fake_get)
    meta = VideoMeta(tvshow='Frieren', episode='1', languages=['ja'], preferred_lang='ja', kitsu_id='46474')
    res = JimakuService.search(meta, {'subtitles.jimaku.apikey': 'tok'})
    assert len(res) == 1
    assert len(waits) == 1 and waits[0] <= 3.0

    # If abort triggers during backoff, stop immediately without retry
    calls_abort = []
    monkeypatch.setattr(control.monitor, 'waitForAbort', lambda s: True)
    monkeypatch.setattr(client, 'get', lambda *a, **k: calls_abort.append(1) or _resp(429, headers={'Retry-After': '2'}))
    assert JimakuService.search(meta, {'subtitles.jimaku.apikey': 'tok'}) == []
    assert len(calls_abort) == 1


def test_jimaku_download_rejects_html_and_scopes_auth_header(monkeypatch):
    seen_headers = []

    def _fake_get(url, params=None, headers=None, timeout=None):
        seen_headers.append((url, dict(headers or {})))
        if 'bad-html' in url:
            return _resp(200, content=b'<!DOCTYPE html><html><body>Cloudflare</body></html>')
        return _resp(200, content=SAMPLE_ASS.encode('utf-8'))

    monkeypatch.setattr(client, 'get', _fake_get)
    r_html = SubtitleResult('jimaku', 'Jimaku', 'ep1.ass', 'Japanese', 'ja', download_url='https://jimaku.cc/bad-html')
    assert JimakuService.download(r_html, {'subtitles.jimaku.apikey': 'k1'}) is None
    assert seen_headers[-1][1].get('Authorization') == 'k1'

    # External CDN host should NOT receive Jimaku API key
    r_cdn = SubtitleResult('jimaku', 'Jimaku', 'ep1.ass', 'Japanese', 'ja', download_url='https://cdn.example.net/ep1.ass')
    data = JimakuService.download(r_cdn, {'subtitles.jimaku.apikey': 'k1'})
    assert data is not None and b'[Events]' in data
    assert 'Authorization' not in seen_headers[-1][1]


# ─── 2. AnimetoshoSubtitleService Tests (Happy + Negative/Edge) ──────────────

def test_animetosho_eid_inline_attachments_and_xz_download_pipeline(tmp_path, monkeypatch):
    xz_payload = lzma.compress(SAMPLE_ASS.encode('utf-8'))
    feed_entries = [
        {
            'id': 88001,
            'title': '[SubsPlease] Sousou no Frieren - 01 (1080p) [A1B2C3D4].mkv',
            'seeders': 120,
            'attachments': [
                {
                    'filename': 'Sousou_no_Frieren_01_eng.ass.xz',
                    'url': 'https://storage.animetosho.org/attach/88001/eng.ass.xz',
                    'language': 'eng',
                },
                {
                    'filename': 'Sousou_no_Frieren_01_signs.ass.xz',
                    'url': 'https://storage.animetosho.org/attach/88001/signs.ass.xz',
                    'language': 'eng',
                },
            ],
        }
    ]
    requested_urls = []

    def _fake_get(url, timeout=None, **kwargs):
        requested_urls.append(url)
        if 'feed.animetosho.org/json' in url:
            return _resp(200, json_data=feed_entries)
        if url.endswith('eng.ass.xz'):
            return _resp(200, content=xz_payload)
        return _resp(404)

    monkeypatch.setattr(client, 'get', _fake_get)
    meta = VideoMeta(
        tvshow='Sousou no Frieren',
        season='1',
        episode='1',
        languages=['English'],
        preferred_lang='en',
        anidb_ep_id='271001',
        release_group='SubsPlease',
    )
    results = AnimetoshoSubtitleService.search(meta, {'subtitles.timeout': 10})
    assert len(results) == 2
    assert len(requested_urls) == 1  # Zero extra detail fetches when inline attachments exist
    assert 'eid=271001' in requested_urls[0]

    # Score: Full Dialogue .ass outranks Signs-only .ass
    full_sub = next(r for r in results if not r.is_signs_only)
    signs_sub = next(r for r in results if r.is_signs_only)
    assert search.score_result(full_sub, meta, {}) > search.score_result(signs_sub, meta, {})
    assert full_sub.match_reason == 'Release Group'
    assert full_sub.sync is True

    # Download pipeline decompresses .xz, strips .xz suffix before Kodi 22 cue validation, writes .ass
    out_path = download.download_and_prepare_subtitle(full_sub, meta, {'subtitles.strip_sdh_tags': True}, dest_dir=str(tmp_path))
    assert out_path is not None
    assert out_path.endswith('.ass')
    assert not out_path.endswith('.xz')
    with open(out_path, 'r', encoding='utf-8') as fp:
        written = fp.read()
    assert '[Script Info]' in written
    assert '{\\pos(320,240)\\an8}' in written
    assert '{\\fad(200,200)}' in written
    assert '[sighs]' not in written
    assert '(applause)' not in written
    assert 'FRIEREN:' not in written


def test_animetosho_detail_fetch_strictly_bounded_to_max_two(monkeypatch):
    # 10 entries with NO inline attachments -> must issue at most 2 detail fetches (total 3 GETs)
    entries = [{'id': 1000 + i, 'title': f'[SubsPlease] Frieren - 01 (1080p) v{i}.mkv', 'seeders': 10 - i} for i in range(10)]
    urls = []

    def _fake_get(url, timeout=None, **kwargs):
        urls.append(url)
        if 'show=torrent' in url:
            return _resp(200, json_data={'id': 1000, 'files': [{'attachments': []}]})
        return _resp(200, json_data=entries)

    monkeypatch.setattr(client, 'get', _fake_get)
    meta = VideoMeta(tvshow='Frieren', season='1', episode='1', languages=['English'], preferred_lang='en', anidb_ep_id='999')
    AnimetoshoSubtitleService.search(meta, {'subtitles.timeout': 10})
    detail_calls = [u for u in urls if 'show=torrent' in u]
    assert len(detail_calls) == 2


def test_animetosho_corrupt_xz_and_html_rejected(tmp_path, monkeypatch):
    # Corrupt XZ bytes -> ValueError in archive -> download_and_prepare_subtitle returns None cleanly
    corrupt_xz = b'\xfd7zXZ\x00not_valid_lzma_stream'
    with pytest.raises(ValueError):
        archive.extract_subtitle_from_archive(corrupt_xz, filename='ep1.ass.xz')

    # HTML error response rejected in AnimetoshoSubtitleService.download
    monkeypatch.setattr(client, 'get', lambda *a, **k: _resp(200, content=b'<html>502 Bad Gateway</html>'))
    res = SubtitleResult('animetosho', 'AnimeTosho', 'ep1.ass.xz', 'English', 'en', download_url='https://storage.animetosho.org/a/1.ass.xz')
    assert AnimetoshoSubtitleService.download(res, {}) is None

    # Also test GZIP decompression stays clean
    gz_ass = gzip.compress(SAMPLE_ASS.encode('utf-8'))
    raw_out, inner_name = archive.extract_subtitle_from_archive(gz_ass, filename='ep1.ass.gz')
    assert b'[Events]' in raw_out and inner_name == 'ep1.ass'


# ─── 3. Registry, Circuit Breaker, SDH Strip & Service Pass-Through ──────────

def test_registry_settings_circuit_breaker_and_osd_passthrough(monkeypatch):
    assert 'jimaku' in ALL_SERVICES
    assert 'animetosho' in ALL_SERVICES

    cfg = subtitles.get_subtitles_settings()
    assert 'subtitles.provider.jimaku' in cfg
    assert 'subtitles.jimaku.apikey' in cfg
    assert 'subtitles.provider.animetosho' in cfg

    # Verify label2 renders .ass.xz cleanly as ASS
    r_xz = SubtitleResult(
        'animetosho', 'AnimeTosho', '[SubsPlease] Frieren - 01.ass.xz', 'English', 'en',
        auto_identified=True, match_confidence='exact', match_reason='Release Group', subtitle_format='ass',
    )
    lbl2 = subtitles.format_kodi_listitem_label2(r_xz)
    assert '([B]ASS[/B])' in lbl2
    assert 'AnimeTosho' in lbl2

    # Verify service.subtitles.otaku.rpdev preserves acyclic xbmc.python-only DAG
    root = ET.parse(SUB_ADDON_XML).getroot()
    assert [el.attrib.get('addon') for el in root.findall('./requires/import')] == ['xbmc.python']

    # Verify circuit breaker skips tripped sub_animetosho
    domains.adaptive_circuit_breaker.reset()
    for _ in range(5):
        domains.adaptive_circuit_breaker.record_failure('sub_animetosho', category='subtitle')
    assert domains.adaptive_circuit_breaker.is_tripped('sub_animetosho', category='subtitle') is True
    domains.adaptive_circuit_breaker.reset()


def test_ass_sdh_strip_only_modifies_dialogue_text_field():
    ass_with_brackets_in_style = (
        "[Script Info]\n"
        "Title: [Do Not Strip Header Title]\n"
        "[V4+ Styles]\n"
        "Style: [Default],Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1\n"
        "[Events]\n"
        "Dialogue: 0,0:00:01.00,0:00:04.00,[Default],(Actor),0,0,0,,{\\pos(100,200)}[music] FERN: Wait, Miss Frieren! (gasps)\n"
    )
    cleaned = download.strip_sdh_hearing_impaired_tags(ass_with_brackets_in_style)
    assert "Title: [Do Not Strip Header Title]" in cleaned
    assert "Style: [Default],Arial" in cleaned
    assert "0:00:01.00,0:00:04.00,[Default],(Actor),0,0,0,," in cleaned
    assert "{\\pos(100,200)}" in cleaned
    assert "[music]" not in cleaned
    assert "(gasps)" not in cleaned
    assert "FERN:" not in cleaned
    assert "Wait, Miss Frieren!" in cleaned


def test_subtitle_search_bypasses_global_dns_gate(monkeypatch):
    import socket
    import urllib.error
    from resources.lib.ui import client
    from resources.lib.subtitles import search as sub_search
    from resources.lib.subtitles.models import SubtitleResult

    client.clear_connectivity_gate()
    try:
        # Simulate two distinct subtitle hosts failing DNS inside bypass_connectivity_gate()
        with client.bypass_connectivity_gate():
            gate = client._connectivity_gate
            # Direct request() path checks bypass_dns_gate before recording failure
            monkeypatch.setattr(
                client.urllib.request,
                'build_opener',
                lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError(socket.gaierror(-2, 'Name or service not known'))),
            )
            client.get('https://dead-sub-a.example/api', timeout=1)
            client.get('https://dead-sub-b.example/api', timeout=1)
            assert client.is_connectivity_gate_tripped() is False
            assert gate._recent_host_failures == {}

        # Verify search_all_services wraps provider calls in bypass_connectivity_gate()
        saw_bypass = []

        class _ProbeSvc:
            service_name = 'probe_svc'
            display_name = 'Probe'

            @classmethod
            def search(cls, meta, settings):
                saw_bypass.append(bool(getattr(client._tls_req_state, 'bypass_dns_gate', False)))
                return [
                    SubtitleResult(
                        service_name='probe_svc',
                        display_name='Probe',
                        name='Bleach - 55.ass',
                        lang='English',
                        lang_code='en',
                        download_url='https://example.invalid/55.ass',
                    )
                ]

        monkeypatch.setattr(sub_search, 'ALL_SERVICES', {'probe_svc': _ProbeSvc})
        meta = VideoMeta(title='Bleach', tvshow='Bleach', season='1', episode='55', is_tvshow=True, preferred_lang='en', languages=['English'])
        res = sub_search.search_all_services(meta, {'subtitles.provider.probe_svc': True, 'subtitles.timeout': 5})
        assert saw_bypass == [True]
        assert len(res) == 1
    finally:
        client.clear_connectivity_gate()


def test_animetosho_aid_falls_back_to_title_query_for_long_running_anime(monkeypatch):
    seen_urls = []

    def fake_get(url, params=None, headers=None, timeout=15):
        seen_urls.append(url)
        if 'aid=2369' in url:
            # Recent episode (366) only — no ep 55
            return _resp(200, json_data=[{
                'id': 9001,
                'title': '[Group] Bleach - 366 [1080p].mkv',
                'seeders': 20,
                'attachments': [{'url': 'https://animetosho.org/sub/366.ass.xz', 'filename': 'ep366.ass.xz'}],
            }])
        if 'q=Bleach+55' in url or 'q=Bleach%2055' in url:
            return _resp(200, json_data=[{
                'id': 9002,
                'title': '[Yameii] Bleach - 55 [1080p].mkv',
                'seeders': 15,
                'attachments': [{'url': 'https://animetosho.org/sub/55.ass.xz', 'filename': 'Bleach - 55.eng.ass.xz'}],
            }])
        return _resp(200, json_data=[])

    monkeypatch.setattr(client, 'get', fake_get)
    meta = VideoMeta(
        title='Bleach',
        tvshow='Bleach',
        season='1',
        episode='55',
        is_tvshow=True,
        anidb_id='2369',
        preferred_lang='en',
        languages=['English'],
    )
    results = AnimetoshoSubtitleService.search(meta, {'subtitles.timeout': 10})
    assert any('aid=2369' in u for u in seen_urls)
    assert any('q=Bleach' in u for u in seen_urls)
    assert len(results) == 1
    assert '55' in results[0].name


def test_opensubtitles_and_subdl_fallback_for_long_running_s1_ep_gt_20(monkeypatch):
    from resources.lib.subtitles.services import opensubtitles, subdl

    os_calls = []

    def fake_os_get(url, params=None, headers=None, timeout=15):
        os_calls.append(dict(params or {}))
        if 'season_number' in (params or {}):
            return _resp(200, json_data={'data': []})
        return _resp(200, json_data={
            'data': [{
                'attributes': {
                    'language': 'en',
                    'ratings': 8.0,
                    'feature_details': {'season_number': 3, 'episode_number': 14},
                    'files': [{'file_id': 111, 'file_name': 'Bleach.S03E14.55.srt'}],
                }
            }]
        })

    monkeypatch.setattr(opensubtitles.client, 'get', fake_os_get)
    meta = VideoMeta(
        title='Bleach',
        tvshow='Bleach',
        season='1',
        episode='55',
        imdb_id='tt0434665',
        is_tvshow=True,
        preferred_lang='en',
        languages=['English'],
    )
    os_res = opensubtitles.OpenSubtitlesService.search(meta, {'subtitles.timeout': 10})
    assert len(os_calls) == 2
    assert os_calls[0].get('season_number') == '1'
    assert 'season_number' not in os_calls[1]
    assert len(os_res) == 1

    subdl_calls = []

    def fake_subdl_get(url, params=None, headers=None, timeout=15):
        subdl_calls.append(dict(params or {}))
        if 'season' in (params or {}):
            return _resp(200, json_data={'subtitles': []})
        return _resp(200, json_data={
            'subtitles': [{
                'release_name': 'Bleach.055.srt',
                'url': '/subtitle/123.zip',
                'language': 'en',
                'season': 3,
                'episode': 14,
            }]
        })

    monkeypatch.setattr(subdl.client, 'get', fake_subdl_get)
    subdl_res = subdl.SubDLService.search(meta, {'subtitles.subdl.apikey': 'test-key', 'subtitles.timeout': 10})
    assert len(subdl_calls) == 2
    assert subdl_calls[0].get('season') == '1'
    assert 'season' not in subdl_calls[1]
    assert len(subdl_res) == 1


def test_manual_search_trailing_episode_and_preserves_anime_ids(monkeypatch):
    from resources.lib.subtitles import meta as sub_meta

    p1 = sub_meta.parse_manual_search_query('Bleach 55')
    assert p1 == {'title': 'Bleach', 'season': '', 'episode': '55', 'year': ''}

    p2 = sub_meta.parse_manual_search_query('Spirited Away 2001')
    assert p2 == {'title': 'Spirited Away', 'season': '', 'episode': '', 'year': '2001'}

    base = VideoMeta(
        title='Bleach',
        tvshow='Bleach',
        season='1',
        episode='55',
        imdb_id='tt0434665',
        mal_id='269',
        anidb_id='2369',
        preferred_group='Yameii',
        is_tvshow=True,
        preferred_lang='en',
        languages=['English'],
    )
    monkeypatch.setattr(sub_meta, 'get_meta_from_player', lambda **kw: base)
    manual_meta = sub_meta.get_meta_for_manual_search('Bleach 55')
    assert manual_meta.title == 'Bleach'
    assert manual_meta.episode == '55'
    assert manual_meta.anidb_id == '2369'
    assert manual_meta.imdb_id == 'tt0434665'
    assert manual_meta.preferred_group == 'Yameii'
