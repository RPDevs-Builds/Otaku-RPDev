"""High-coverage unit tests for embed_extractor.py and context.otaku.rpdev/addon.xml visibility rules."""
# -*- coding: utf-8 -*-

import base64
import json
import os
import re
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, embed_extractor
from resources.lib.ui.pyaes import AESModeOfOperationCBC, Encrypter


def _eval_kodi_visible(expr: str, ctx: dict) -> bool:
    """Evaluate Kodi GUI boolean <visible> expressions supporting +, |, !, [...] grouping & String.* predicates."""
    expr = expr.strip()

    # Recursive descent parser for Kodi boolean syntax: OR (|), AND (+), unary (!), [...] groups
    tokens = []
    pos = 0
    while pos < len(expr):
        ch = expr[pos]
        if ch.isspace():
            pos += 1
        elif ch in ('+', '|', '!', '[', ']'):
            tokens.append(ch)
            pos += 1
        else:
            start = pos
            depth = 0
            while pos < len(expr):
                c = expr[pos]
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth = max(0, depth - 1)
                elif depth == 0 and (c in ('+', '|', '[', ']') or c.isspace()):
                    break
                pos += 1
            tokens.append(expr[start:pos])

    idx = [0]

    def _eval_atom(tok: str) -> bool:
        def _resolve_arg(arg_expr: str) -> str:
            a = arg_expr.strip()
            if a.startswith('Window(home).Property(') and a.endswith(')'):
                prop = a[len('Window(home).Property('):-1]
                return str(ctx.get('window_props', {}).get(prop, ''))
            if a.startswith('ListItem.Property(') and a.endswith(')'):
                prop = a[len('ListItem.Property('):-1]
                return str(ctx.get('item_props', {}).get(prop, ''))
            if a.startswith('ListItem.UniqueID(') and a.endswith(')'):
                uid = a[len('ListItem.UniqueID('):-1]
                return str(ctx.get('unique_ids', {}).get(uid, ''))
            if a == 'ListItem.Path':
                return str(ctx.get('path', ''))
            if a == 'ListItem.DBTYPE':
                return str(ctx.get('dbtype', ''))
            if a == 'ListItem.folderpath':
                return str(ctx.get('folderpath', ''))
            return a

        if tok.startswith('String.IsEqual(') and tok.endswith(')'):
            inner = tok[len('String.IsEqual('):-1]
            left, right = inner.rsplit(',', 1)
            return _resolve_arg(left).lower() == _resolve_arg(right).lower()
        if tok.startswith('String.StartsWith(') and tok.endswith(')'):
            inner = tok[len('String.StartsWith('):-1]
            left, right = inner.rsplit(',', 1)
            return _resolve_arg(left).startswith(_resolve_arg(right))
        if tok.startswith('String.Contains(') and tok.endswith(')'):
            inner = tok[len('String.Contains('):-1]
            left, right = inner.rsplit(',', 1)
            return _resolve_arg(right) in _resolve_arg(left)
        if tok.startswith('String.IsEmpty(') and tok.endswith(')'):
            inner = tok[len('String.IsEmpty('):-1]
            return _resolve_arg(inner) == ''
        if tok == 'Player.HasMedia':
            return bool(ctx.get('has_media', False))
        if tok == 'Player.HasVideo':
            return bool(ctx.get('has_video', False))
        raise AssertionError(f"Unsupported Kodi visibility predicate: {tok}")

    def _parse_or() -> bool:
        val = _parse_and()
        while idx[0] < len(tokens) and tokens[idx[0]] == '|':
            idx[0] += 1
            rhs = _parse_and()
            val = val or rhs
        return val

    def _parse_and() -> bool:
        val = _parse_unary()
        while idx[0] < len(tokens) and tokens[idx[0]] == '+':
            idx[0] += 1
            rhs = _parse_unary()
            val = val and rhs
        return val

    def _parse_unary() -> bool:
        if idx[0] < len(tokens) and tokens[idx[0]] == '!':
            idx[0] += 1
            return not _parse_unary()
        if idx[0] < len(tokens) and tokens[idx[0]] == '[':
            idx[0] += 1
            val = _parse_or()
            assert idx[0] < len(tokens) and tokens[idx[0]] == ']'
            idx[0] += 1
            return val
        tok = tokens[idx[0]]
        idx[0] += 1
        return _eval_atom(tok)

    return _parse_or()


def _mock_http(url='https://cdn.example/video', text='', status_code=200, headers=None):
    r = MagicMock()
    r.url = url
    r.text = text
    r.status_code = status_code
    r.headers = headers or {}
    r.ok = (200 <= status_code < 400)
    r.json.return_value = control.loads_json(text, default={}) if text else {}
    return r


def _ext(name):
    return getattr(embed_extractor, name)


class TestEmbedExtractorDeepCoverage(unittest.TestCase):
    """Exercise all embed_extractor extractors, packers, AES helpers & checks."""

    def test_extractors_direct_and_packed(self):
        # yourupload, mp4upload, lulu, kwik, mixdrop, filemoon, embedrise, streamwish, voe
        yu = _ext('__extract_yourupload')("https://yourupload.com/embed/1", "jwplayerOptions = { file: 'https://cdn/yu.mp4' }")
        self.assertIn("https://cdn/yu.mp4|User-Agent=", yu)

        mp4 = _ext('__extract_mp4upload')("https://mp4upload.com/e/1", 'player.src("https://cdn/mp4.mp4")')
        self.assertIn("https://cdn/mp4.mp4|", mp4)

        lulu = _ext('__extract_lulu')("https://lulustream.com/e/1", 'sources: [{file: "https://cdn/lulu.m3u8"}]')
        self.assertIn("https://cdn/lulu.m3u8|", lulu)

        kwik = _ext('__extract_kwik')("https://kwik.cx/e/1", "const source = 'https://cdn/kwik.m3u8'")
        self.assertIn("https://cdn/kwik.m3u8|", kwik)

        er = _ext('__extract_embedrise')("https://embedrise.com/v/1", '<source src="//cdn/er.mp4">')
        self.assertIn("https://cdn/er.mp4|", er)

        sw = _ext('__extract_streamwish')("https://streamwish.com/e/1", 'sources: [{file: "https://cdn/sw.m3u8"}]')
        self.assertEqual(sw, "https://cdn/sw.m3u8")

        # Mixdrop / Filemoon rely on __get_packed_data
        with patch('resources.lib.ui.embed_extractor.__get_packed_data', side_effect=[
            'MDCore.wurl = "//cdn/mixdrop.mp4"',
            'sources: [{ file: "//cdn/filemoon.m3u8"}]',
        ]):
            self.assertIn("https://cdn/mixdrop.mp4|", _ext('__extract_mixdrop')("https://mixdrop.co/e/1", ""))
            self.assertIn("https://cdn/filemoon.m3u8|", _ext('__extract_filemoon')("https://filemoon.sx/e/1", ""))

        # VOE supports reversed base64 wc0 JSON, mp4 JSON & hls JSON
        voe_b64 = base64.b64encode(json.dumps({'file': 'https://cdn/voe_wc0.m3u8'})[::-1].encode()).decode()
        self.assertIn("https://cdn/voe_wc0.m3u8|", _ext('__extract_voe')("https://voe.sx/e/1", f"let wc0 = '{voe_b64}'"))
        self.assertIn("https://cdn/voe.mp4|", _ext('__extract_voe')("https://voe.sx/e/1", '"mp4": "https://cdn/voe.mp4"'))
        self.assertIn("https://cdn/voe.m3u8|", _ext('__extract_voe')("https://voe.sx/e/1", '"hls": "https://cdn/voe.m3u8"'))

        # Streamtape concatenation with substring(N)
        st_html = """document.getElementById('botlink').innerHTML = "//stape.com/" + 'xxxgood?id=1'.substring(3);"""
        st_out = _ext('__extract_streamtape')("https://streamtape.com/e/1", st_html)
        self.assertIn("https://stape.com/good?id=1&stream=1|", st_out)

    def test_extractors_network_backed_and_helpers(self):
        # ok.ru
        with patch('resources.lib.ui.embed_extractor.client.post', return_value=_mock_http(text=json.dumps({'hlsManifestUrl': 'https://ok/hls.m3u8'}))):
            self.assertEqual(_ext('__extract_okru')("https://ok.ru/videoembed/12345", ""), "https://ok/hls.m3u8")

        # fusevideo
        fuse_b64 = base64.b64encode(b'{"url":"https://cdn/fuse.m3u8"}').decode()
        fuse_js = f'var n = atob("{fuse_b64}")'
        with patch('resources.lib.ui.embed_extractor.client.get', return_value=_mock_http(text=fuse_js)):
            self.assertIn("https://cdn/fuse.m3u8|", _ext('__extract_fusevideo')("https://fusevideo.net/e/1", '<script src="https://fusevideo.net/js/p.js"></script>'))

        # dood
        dood_html = "dsplayer.hotkeys('x', '/pass_md5/abc/def'); function makePlay(){return '?token=xyz'}"
        with patch('resources.lib.ui.embed_extractor.client.get', return_value=_mock_http(text="https://dood.cdn/video/")):
            dood_out = _ext('__extract_dood')("https://dood.li/e/123abc", dood_html)
            self.assertIn("https://dood.cdn/video/", dood_out)
            self.assertIn("?token=xyz", dood_out)

        # goload AES encrypt/decrypt flow
        keys = ['37911490979715163134003223491201', '54674138327930866480207815084989']
        iv = control.bin('3134003223491201')
        enc_param = Encrypter(AESModeOfOperationCBC(control.bin(keys[0]), iv))
        p_ct = base64.b64encode(enc_param.feed('xyz_id') + enc_param.feed()).decode()
        enc_resp = Encrypter(AESModeOfOperationCBC(control.bin(keys[1]), iv))
        r_ct = base64.b64encode(enc_resp.feed(json.dumps({'source': [{'file': 'https://cdn/gogo.m3u8'}]})) + enc_resp.feed()).decode()
        with patch('resources.lib.ui.embed_extractor.client.get', return_value=_mock_http(text=json.dumps({'data': r_ct}))):
            g_out = _ext('__extract_goload')("https://goload.io/streaming.php?id=abc123", f'crypto-js.js data-value="{p_ct}"')
            self.assertIn("https://cdn/gogo.m3u8|", g_out)

        # megacloud & megaplay extractors
        with patch('resources.lib.ui.megacloud_extractor.extract_megacloud_sources', return_value={'sources': [{'file': 'https://mc/hls.m3u8'}]}), \
             patch('resources.lib.ui.megaplay_extractor.extract_megaplay_sources', return_value={'sources': [{'file': 'https://mp/hls.m3u8'}]}):
            self.assertIn("https://mc/hls.m3u8|", _ext('__extract_megacloud')("https://megacloud.tv/embed-2/abc", ""))
            self.assertIn("https://mp/hls.m3u8|", _ext('__extract_megaplay')("https://megaplay.buzz/e/1", ""))

        # __check_video, __check_video_list, __ignore_extractor, __relative_url, _code_to_kodi, normalize_sub_lang, load_video_from_url
        with patch('resources.lib.ui.embed_extractor.client.get', side_effect=[
            _mock_http(url='https://cdn/final.mp4', status_code=200),
            _mock_http(url='https://cdn/bad.mp4', status_code=404),
            _mock_http(url='https://cdn/ok.mp4', status_code=200),
        ]):
            vlist = _ext('__check_video_list')("https://ref/", [('1080p', 'https://cdn/v1.mp4', 'tag1'), ('720p', 'https://cdn/v2.mp4', 'tag2')], add_referer=True, ignore_cookie=True)
            self.assertEqual(len(vlist), 1)
            self.assertEqual(_ext('__check_video')('https://cdn/ok.mp4'), 'https://cdn/ok.mp4')

        self.assertIsNone(_ext('__ignore_extractor')('u', 'c'))
        self.assertEqual(_ext('__relative_url')('https://ex.com/a/b', '//cdn.com/c'), 'http://cdn.com/c')
        self.assertEqual(embed_extractor._code_to_kodi('ja'), 'jpn')
        self.assertEqual(embed_extractor.normalize_sub_lang('English'), 'eng')
        self.assertIsNone(embed_extractor.load_video_from_url('https://unknown.invalid/video'))

        # Packed JS unpacking with jsunpack fallback
        packed_html = "eval(function(p,a,c,k,e,d){return p}('test',10,1,'test'.split('|'),0,{}))</script>"
        with patch('resources.lib.ui.embed_extractor.jsunpack.detect', return_value=True), \
             patch('resources.lib.ui.embed_extractor.jsunpack.unpack', return_value='var x = 1;'):
            self.assertEqual(_ext('__get_packed_data')(packed_html), 'var x = 1;')


class TestContextAddonXMLVisibilityMatrix(unittest.TestCase):
    """Exhaustively validate all 18 context.otaku.rpdev/addon.xml <visible> expressions."""

    def test_all_18_context_menu_items_visibility_matrix(self):
        addon_xml = os.path.abspath(os.path.join(control.ADDON_PATH, '..', 'context.otaku.rpdev', 'addon.xml'))
        root = ET.parse(addon_xml).getroot()
        items = root.findall('.//extension[@point="kodi.context.item"]/menu/item')
        self.assertEqual(len(items), 18)

        all_enabled_props = {
            f"context.otaku.rpdev.{it.attrib['args']}": 'true'
            for it in items
            if it.attrib['args'] != 'manualsubtitles'
        }

        by_args = {it.attrib['args']: it.find('visible').text for it in items}

        # 1. TVShow inside plugin with all context toggles enabled
        ctx_tv = {
            'window_props': all_enabled_props,
            'path': 'plugin://plugin.video.otaku.rpdev/animes/52991/',
            'dbtype': 'tvshow',
            'folderpath': 'plugin://plugin.video.otaku.rpdev/',
            'has_media': False,
            'has_video': False,
        }
        for arg in ('findrecommendations', 'findrelations', 'getwatchorder', 'viewreviews', 'viewstatistics',
                    'deletefromdatabase', 'watchlist', 'fanartselect', 'clearcache', 'seriesprofile',
                    'inspectmappings'):
            self.assertTrue(_eval_kodi_visible(by_args[arg], ctx_tv), f"{arg} should be visible on tvshow")
        for ep_only in ('markedaswatched', 'markedasunwatched', 'markpreviouswatched', 'rescrape', 'sourceselect', 'logout', 'manualsubtitles'):
            self.assertFalse(_eval_kodi_visible(by_args[ep_only], ctx_tv), f"{ep_only} should NOT be visible on idle tvshow")

        # 2. Library/Widget episode with UniqueID(mal_id) while NOT playing media
        ctx_ep_widget = {
            'window_props': all_enabled_props,
            'path': 'videodb://tvshows/titles/1/1/1',
            'unique_ids': {'mal_id': '52991'},
            'dbtype': 'episode',
            'has_media': False,
            'has_video': False,
        }
        for ep_arg in ('markedaswatched', 'markedasunwatched', 'markpreviouswatched', 'rescrape', 'sourceselect', 'seriesprofile', 'manualsubtitles', 'inspectmappings'):
            self.assertTrue(_eval_kodi_visible(by_args[ep_arg], ctx_ep_widget), f"{ep_arg} should show on episode widget via UniqueID(mal_id)")

        # 3. Negative: When Player.HasMedia is active during video playback, rescrape & watchlist-mark hide cleanly while manualsubtitles shows!
        ctx_playing = {
            'window_props': all_enabled_props,
            'path': 'plugin://plugin.video.otaku.rpdev/play/52991/1',
            'item_props': {'mal_id': '52991'},
            'dbtype': 'episode',
            'has_media': True,
            'has_video': True,
        }
        for hidden_during_play in ('markedaswatched', 'markedasunwatched', 'markpreviouswatched', 'rescrape', 'sourceselect'):
            self.assertFalse(_eval_kodi_visible(by_args[hidden_during_play], ctx_playing))
        self.assertTrue(_eval_kodi_visible(by_args['manualsubtitles'], ctx_playing))

        # 4. Logout item shows strictly inside /watchlist/ folders & disabled toggle hides item
        ctx_wl = {'window_props': all_enabled_props, 'path': 'plugin://plugin.video.otaku.rpdev/watchlist/anilist/', 'folderpath': 'plugin://plugin.video.otaku.rpdev/watchlist/anilist/'}
        self.assertTrue(_eval_kodi_visible(by_args['logout'], ctx_wl))
        ctx_disabled = dict(ctx_tv, window_props={})
        self.assertFalse(_eval_kodi_visible(by_args['seriesprofile'], ctx_disabled))


if __name__ == '__main__':
    unittest.main()
