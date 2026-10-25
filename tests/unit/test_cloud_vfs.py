"""
Unit tests for Debrid Cloud VFS layer, blank directories, and file management.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import tests.conftest  # noqa: F401
from resources.lib.ui import control
from resources.lib.debrid import debrid_cloud


class TestCloudVFS(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix='otaku_cloud_test_')
        control.dataPath = self.tmp_dir

    def test_vfs_folder_creation_and_nesting(self):
        """VFS layer creates and nests blank virtual directories cleanly."""
        res1 = debrid_cloud.create_cloud_folder('realdebrid', 'Anime Classics', 'root')
        self.assertTrue(res1)

        vfs = debrid_cloud._load_vfs()
        folders = vfs.get('realdebrid', {}).get('folders', {})
        self.assertTrue(len(folders) > 0)
        archived_id = list(folders.keys())[0]
        self.assertEqual(folders[archived_id]['name'], 'Anime Classics')

        res2 = debrid_cloud.create_cloud_folder('realdebrid', 'Movies', archived_id)
        self.assertTrue(res2)

        vfs2 = debrid_cloud._load_vfs()
        folders2 = vfs2['realdebrid']['folders']
        subfolder = next(f for f in folders2.values() if f['name'] == 'Movies')
        self.assertEqual(subfolder['parent_id'], archived_id)

    def test_vfs_rename_and_deletion(self):
        """VFS layer renames and deletes folders cleanly."""
        self.assertTrue(debrid_cloud.create_cloud_folder('realdebrid', 'Old Name', 'root'))
        vfs = debrid_cloud._load_vfs()
        folder_id = list(vfs['realdebrid']['folders'].keys())[0]

        self.assertTrue(debrid_cloud.rename_cloud_item('realdebrid', folder_id, 'New Name', item_type='folder'))
        vfs2 = debrid_cloud._load_vfs()
        self.assertEqual(vfs2['realdebrid']['folders'][folder_id]['name'], 'New Name')

        self.assertTrue(debrid_cloud.delete_cloud_item('realdebrid', folder_id, item_type='folder'))
        vfs3 = debrid_cloud._load_vfs()
        self.assertNotIn(folder_id, vfs3['realdebrid']['folders'])

    def test_find_stalled_torrents_realdebrid(self):
        """Identifies error and 0% stalled torrents while preserving completed downloads."""
        mock_torrents = [
            {'id': 't1', 'filename': 'Good.Frieren.S01E01.mkv', 'status': 'downloaded', 'progress': 100},
            {'id': 't2', 'filename': 'Dead.Naruto.mkv', 'status': 'error', 'progress': 0},
            {'id': 't3', 'filename': 'Unselected.Bleach.mkv', 'status': 'waiting_files_selection', 'progress': 0},
            {'id': 't4', 'filename': 'Active.OnePiece.mkv', 'status': 'downloading', 'progress': 45},
        ]
        with patch('resources.lib.debrid.real_debrid.RealDebrid.list_torrents', return_value=mock_torrents):
            stalled = debrid_cloud.find_stalled_torrents('realdebrid')
            stalled_ids = [t['id'] for t in stalled]
            self.assertEqual(stalled_ids, ['t2', 't3'])

    def test_find_stalled_torrents_torbox(self):
        """Identifies failed and stalled TorBox transfers."""
        mock_torrents = [
            {'id': 'tb1', 'name': 'Done.Show.mkv', 'download_state': 'completed', 'progress': 1.0},
            {'id': 'tb2', 'name': 'Failed.Show.mkv', 'download_state': 'failed', 'progress': 0.1},
            {'id': 'tb3', 'name': 'Stalled.Show.mkv', 'download_state': 'stalled', 'progress': 0.0},
        ]
        with patch('resources.lib.debrid.torbox.TorBox.list_torrents', return_value=mock_torrents):
            stalled = debrid_cloud.find_stalled_torrents('torbox')
            stalled_ids = [t['id'] for t in stalled]
            self.assertEqual(stalled_ids, ['tb2', 'tb3'])

    def test_purge_stalled_torrents_execution(self):
        """Purge executes provider deletion when user confirms."""
        mock_torrents = [
            {'id': 't_err', 'filename': 'Error.Show.mkv', 'status': 'magnet_error', 'progress': 0}
        ]
        with patch('resources.lib.debrid.real_debrid.RealDebrid.list_torrents', return_value=mock_torrents), \
             patch('resources.lib.debrid.real_debrid.RealDebrid.deleteTorrent', return_value=True) as mock_delete, \
             patch.object(control, 'yesno_dialog', return_value=True), \
             patch.object(control, 'notify') as mock_notify:

            purged_count = debrid_cloud.purge_stalled_torrents('realdebrid')
            self.assertEqual(purged_count, 1)
            mock_delete.assert_called_once_with('t_err')
            self.assertTrue(mock_notify.called)


if __name__ == '__main__':
    unittest.main()
