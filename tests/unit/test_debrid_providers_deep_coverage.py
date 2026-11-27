"""Deep unit tests covering Premiumize, AllDebrid, DebridLink, and TorBox methods."""
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, patch

from resources.lib.debrid.all_debrid import AllDebrid
from resources.lib.debrid.debrid_link import DebridLink
from resources.lib.debrid.premiumize import Premiumize
from resources.lib.debrid.torbox import TorBox
from resources.lib.ui import control


def _mock_resp(payload, ok=True, status_code=200):
    r = MagicMock()
    r.ok = ok
    r.status_code = status_code
    r.headers = {}
    r.json.return_value = payload
    return r


class TestPremiumizeDeepCoverage(unittest.TestCase):
    """Cover folder CRUD, storage GC, direct download, cloud & uncached resolution."""

    def test_premiumize_folder_and_item_operations(self):
        pm = Premiumize()
        pm.token = 'pm_tok'
        payloads = {
            'folder/search': {'content': [{'id': 'f1', 'name': 'Anime'}]},
            'folder/list': {'folder_id': 'root_99', 'content': [{'id': 'i1', 'name': 'Show - 01.mkv', 'type': 'file', 'link': 'https://pm/ep1.mkv'}]},
            'folder/create': {'status': 'success', 'id': 'new_f'},
            'folder/rename': {'status': 'success'},
            'item/rename': {'status': 'success'},
            'folder/delete': {'status': 'success'},
            'item/delete': {'status': 'success'},
            'folder/paste': {'status': 'success'},
            'item/details': {'id': 'i1', 'name': 'ep1.mkv'},
            'cache/check': {'response': [True]},
            'transfer/directdl': {'status': 'success', 'location': 'https://pm/dl.mkv', 'content': [{'path': 'Show - 01.mkv', 'size': 1000, 'link': 'https://pm/s1.mkv'}]},
            'transfer/create': {'status': 'success', 'id': 'tr1'},
            'transfer/list': {'transfers': [{'id': 'tr1', 'status': 'finished', 'created_at': 100, 'size': 1024 ** 3}]},
            'transfer/delete': {'status': 'success'},
            'account/info': {'space_used': 20 * (1024 ** 3)},
        }

        def _req(url, **kwargs):
            for key, val in payloads.items():
                if key in url:
                    return _mock_resp(val)
            return _mock_resp({})

        with patch('resources.lib.debrid.premiumize.client.get', side_effect=_req), \
             patch('resources.lib.debrid.premiumize.client.post', side_effect=_req), \
             patch('resources.lib.ui.source_utils.is_file_ext_valid', return_value=True):
            self.assertEqual(len(pm.search_folder('Anime')), 1)
            self.assertEqual(pm.get_root_folder_id(), 'root_99')
            self.assertEqual(pm.item_details('i1')['id'], 'i1')
            self.assertEqual(pm.create_folder('F')['id'], 'new_f')
            self.assertTrue(pm.rename_folder('new_f', 'Renamed'))
            self.assertTrue(pm.rename_item('i1', 'ep01.mkv'))
            self.assertTrue(pm.delete_folder('new_f'))
            self.assertTrue(pm.delete_item('i1'))
            self.assertTrue(pm.move_items(['i1'], 'f1'))
            self.assertEqual(pm.hash_check(['abc']), {'status': 'success', 'response': [True]})
            pm.threshold = 5
            pm.addtocloud = True
            self.assertEqual(pm.resolve_hoster('magnet:?xt=1'), 'https://pm/dl.mkv')
            self.assertEqual(pm.resolve_single_magnet('abc', 'magnet:?xt=1', '01', False), 'https://pm/s1.mkv')
            self.assertEqual(pm.resolve_cloud({'torrent_type': 'file', 'hash': 'h1'}, False), 'h1')
            self.assertEqual(pm.resolve_cloud({'torrent_type': 'folder', 'id': 'f1', 'episode': '1'}, False), 'https://pm/ep1.mkv')

    def test_premiumize_resolve_uncached_source_paths(self):
        pm = Premiumize()
        with patch.object(pm, 'addMagnet', return_value={'id': 'tr1'}), \
             patch.object(pm, 'transfer_list', return_value=[{'id': 'tr1', 'status': 'finished', 'file_id': 'f1', 'folder_id': None}]), \
             patch('resources.lib.debrid.premiumize.control.notify'):
            # Background queue exits cleanly after notify
            self.assertIsNone(pm.resolve_uncached_source({'magnet': 'm1', 'episode_re': '01'}, True, False, False))

        with patch.object(pm, 'addMagnet', return_value={'id': 'tr1'}), \
             patch.object(pm, 'transfer_list', return_value=[{'id': 'tr1', 'status': 'finished', 'file_id': 'f1', 'folder_id': None}]), \
             patch.object(pm, 'get_storage_info', return_value={'space_used': 0}), \
             patch.object(pm, 'direct_download', return_value={'content': [{'path': 'Show - 01.mkv', 'size': 1000, 'link': 'https://pm/fin.mkv'}]}), \
             patch('resources.lib.ui.source_utils.is_file_ext_valid', return_value=True), \
             patch('resources.lib.debrid.premiumize.control.ok_dialog'):
            link = pm.resolve_uncached_source({'magnet': 'm1', 'episode_re': '01'}, False, False, False)
            self.assertEqual(link, 'https://pm/fin.mkv')


class TestAllDebridDeepCoverage(unittest.TestCase):
    """Cover AllDebrid auth, status, hoster, magnet CRUD, history & uncached paths."""

    def test_all_debrid_methods_and_resolution(self):
        ad = AllDebrid()
        ad.token = 'ad_tok'
        ad.autodelete = True

        def _req(url, **kwargs):
            if '/user/links' in url or '/user/history' in url:
                return _mock_resp({'data': {'links': ['https://ad/saved.mkv']}})
            if '/user' in url:
                return _mock_resp({'status': 'success', 'data': {'user': {'username': 'u1', 'isPremium': True}}})
            if '/pin/check' in url:
                return _mock_resp({'status': 'success', 'data': {'activated': True, 'apikey': 'ad_new'}})
            if '/magnet/upload' in url:
                return _mock_resp({'data': {'magnets': [{'id': 'm1'}]}})
            if '/link/unlock' in url:
                return _mock_resp({'data': {'link': 'https://ad/unlocked.mkv'}})
            if '/link/infos' in url:
                return _mock_resp({'data': {'infos': [{'link': 'https://ad/info.mkv'}]}})
            if '/magnet/files' in url:
                return _mock_resp({'data': {'magnets': [{'id': 'm1', 'files': [{'n': 'Show - 01.mkv', 'l': 'https://ad/l1'}]}]}})
            if '/magnet/status' in url:
                return _mock_resp({'data': {'magnets': {
                    'id': 'm1', 'status': 'Ready', 'statusCode': 4, 'seeders': 5, 'downloaded': 10, 'size': 10, 'downloadSpeed': 100,
                    'files': [{'n': 'Show - 01.mkv', 'l': 'https://ad/l1', 's': 100}],
                    'links': [{'link': 'https://ad/l1', 'filename': 'Show - 01.mkv'}],
                }}})
            if '/user/links' in url or '/user/history' in url:
                return _mock_resp({'data': {'links': ['https://ad/saved.mkv']}})
            if '/magnet/delete' in url:
                return _mock_resp({'status': 'success'})
            return _mock_resp({})

        with patch('resources.lib.debrid.all_debrid.client.get', side_effect=_req), \
             patch('resources.lib.ui.source_utils.is_file_ext_valid', return_value=True), \
             patch('resources.lib.debrid.all_debrid.control.ok_dialog'):
            ad.status()
            self.assertEqual(control.getSetting('alldebrid.auth.status'), 'Premium')
            self.assertTrue(ad.auth_loop(pin='1234', check='chk'))
            self.assertEqual(ad.resolve_hoster('https://ad/l1'), 'https://ad/unlocked.mkv')
            self.assertEqual(ad.resolve_single_magnet('h1', 'm1', '01', False), 'https://ad/unlocked.mkv')
            self.assertEqual(ad.list_saved_links()['links'], ['https://ad/saved.mkv'])
            self.assertEqual(ad.list_history()['links'], ['https://ad/saved.mkv'])
            self.assertEqual(len(ad.link_info('https://ad/l1')), 1)
            tid, st, _info = ad.get_torrent_status('m1')
            self.assertEqual((tid, st), ('m1', 'Ready'))
            self.assertIsNone(ad.resolve_cloud({'hash': [{'link': 'https://ad/l1', 'filename': 'Show - 01.mkv'}], 'episode': '01'}, False))
            self.assertEqual(ad.resolve_uncached_source({'magnet': 'm1', 'episode_re': '01'}, False, False, False), 'https://ad/unlocked.mkv')


class TestDebridLinkDeepCoverage(unittest.TestCase):
    """Cover DebridLink auth_loop, status, refreshToken, add/delete, resolve_single_magnet & uncached."""

    def test_debrid_link_auth_status_and_magnet_flows(self):
        dl = DebridLink()
        dl.ClientID = 'cid'
        dl.DeviceCode = 'dev1'
        dl.refresh = 'ref1'
        dl.autodelete = True

        def _post(url, **kwargs):
            if '/oauth/token' in url:
                return _mock_resp({'access_token': 'dl_acc', 'refresh_token': 'dl_ref', 'expires_in': 3600})
            if '/seedbox/add' in url:
                return _mock_resp({'value': {
                    'id': 'dl1',
                    'downloadPercent': 100.0,
                    'files': [{'name': 'Show - 01.mkv', 'size': 500000, 'downloadUrl': 'https://dl/ep1.mkv'}],
                }})
            return _mock_resp({})

        def _get(url, **kwargs):
            if '/account/infos' in url:
                return _mock_resp({'value': {'pseudo': 'dl_user', 'premiumLeft': 86400}})
            if '/infos' in url:
                return _mock_resp({'value': {
                    'id': 'dl1', 'downloadPercent': 100.0, 'name': 'Show',
                    'files': [{'name': 'Show - 01.mkv', 'size': 500000, 'downloadUrl': 'https://dl/ep1.mkv'}],
                }})
            return _mock_resp({})

        with patch('resources.lib.debrid.debrid_link.client.post', side_effect=_post), \
             patch('resources.lib.debrid.debrid_link.client.get', side_effect=_get), \
             patch('resources.lib.debrid.debrid_link.client.delete', return_value=_mock_resp({'success': True})), \
             patch('resources.lib.debrid.debrid_link.control.ok_dialog'), \
             patch('resources.lib.debrid.debrid_link.control.notify'):
            self.assertTrue(dl.auth_loop())
            dl.status()
            self.assertEqual(control.getSetting('debridlink.auth.status'), 'Premium')
            dl.refreshToken()
            self.assertEqual(dl.token, 'dl_acc')
            self.assertEqual(dl.resolve_single_magnet('h1', 'magnet:?xt=1', '01', False), 'https://dl/ep1.mkv')
            tid, st, _info = dl.get_torrent_status('magnet:?xt=1')
            self.assertEqual((tid, st), ('dl1', True))
            self.assertIsNone(dl.resolve_uncached_source({'magnet': 'm1', 'episode_re': '01'}, True, False, False))
            self.assertEqual(dl.resolve_uncached_source({'magnet': 'm1', 'episode_re': '01'}, False, False, False), 'https://dl/ep1.mkv')


class TestTorBoxDeepCoverage(unittest.TestCase):
    """Cover TorBox refresh, hash_check, single magnet, hoster, cloud & uncached paths."""

    def test_torbox_methods(self):
        tb = TorBox()
        tb.token = 'tb_tok'
        tb.autodelete = True

        def _get(url, **kwargs):
            if 'checkcached' in url:
                return _mock_resp({'data': {'abc': {'name': 'Show'}}})
            if 'mylist' in url:
                return _mock_resp({'data': {
                    'id': 77, 'download_state': 'completed', 'progress': 1.0, 'peers': 4, 'download_speed': 50,
                    'files': [{'id': 9, 'name': 'Show - 01.mkv'}],
                }})
            if 'requestdl' in url:
                return _mock_resp({'data': 'https://tb/stream.mkv'})
            return _mock_resp({})

        def _post(url, **kwargs):
            if 'createtorrent' in url:
                return _mock_resp({'data': {'torrent_id': 77}})
            return _mock_resp({'data': True})

        with patch('resources.lib.debrid.torbox.client.get', side_effect=_get), \
             patch('resources.lib.debrid.torbox.client.post', side_effect=_post), \
             patch('resources.lib.ui.source_utils.is_file_ext_valid', return_value=True), \
             patch('resources.lib.debrid.torbox.control.ok_dialog'), \
             patch('resources.lib.debrid.torbox.control.notify'):
            self.assertTrue('abc' in tb.hash_check(['abc']))
            self.assertEqual(tb.resolve_single_magnet('abc', 'magnet:?xt=1', '01', False, filename='Show - 01.mkv'), 'https://tb/stream.mkv')
            cloud_picked = tb.resolve_cloud({'id': 77, 'episode': '01', 'hash': [{'short_name': 'Show - 01.mkv', 'id': 9}]}, False)
            self.assertEqual(cloud_picked['folder_id'], 77)
            self.assertEqual(tb.resolve_hoster(cloud_picked), 'https://tb/stream.mkv')
            self.assertEqual(tb.resolve_uncached_source({'magnet': 'm1', 'episode_re': '01'}, False, False, False), 'https://tb/stream.mkv')


if __name__ == '__main__':
    unittest.main()
