import unittest
from unittest.mock import patch, MagicMock
import xbmc
import xbmcgui
import xbmcaddon
from resources.lib.ui import control, database


class TestCPythonInvokerLifecycle(unittest.TestCase):

    def test_window_proxy(self):
        """Test _WindowProxy delegates correctly to xbmcgui.Window without holding static SWIG wrappers."""
        win_proxy = control._WindowProxy(10000)
        win_proxy.setProperty('test_key', 'test_val')
        self.assertEqual(win_proxy.getProperty('test_key'), 'test_val')
        self.assertEqual(control.homeWindow.getProperty('test_key'), 'test_val')

        win_proxy.clearProperty('test_key')
        self.assertEqual(win_proxy.getProperty('test_key'), '')

        win_proxy.setProperty('bulk_1', '1')
        win_proxy.setProperty('bulk_2', '2')
        win_proxy.clearProperties()
        self.assertEqual(win_proxy.getProperty('bulk_1'), '')
        self.assertEqual(win_proxy.getProperty('bulk_2'), '')

        # Assert database memory cache uses the proxy rather than leaking a static Window
        self.assertIs(database._window, control.homeWindow)

    def test_playlist_proxy(self):
        """Test _PlayListProxy delegates correctly to xbmc.PlayList without persistent SWIG wrapper leaks."""
        pl_proxy = control._PlayListProxy(xbmc.PLAYLIST_VIDEO)
        pl_proxy.clear()
        self.assertEqual(pl_proxy.size(), 0)
        self.assertEqual(len(pl_proxy), 0)

        item = xbmcgui.ListItem(label='Ep 1')
        pl_proxy.add('http://example.com/stream1.mkv', item)
        self.assertEqual(pl_proxy.size(), 1)
        self.assertEqual(len(pl_proxy), 1)

        first_entry = pl_proxy[0]
        self.assertEqual(first_entry[0], 'http://example.com/stream1.mkv')
        self.assertEqual(first_entry[1].getLabel(), 'Ep 1')

        self.assertEqual(pl_proxy.getposition(), 0)
        self.assertTrue(hasattr(pl_proxy, '_get_pl'))

        # Also verify control.playList matches
        self.assertEqual(control.playList.size(), 1)
        control.playList.clear()
        self.assertEqual(control.playList.size(), 0)

    def test_progress_dialog_proxy(self):
        """Test _ProgressDialogProxy lifecycle, lazy creation, and explicit teardown to None."""
        prog = control._ProgressDialogProxy()
        self.assertIsNone(prog._dialog)

        # Before create, safe defaults
        self.assertFalse(prog.iscanceled())
        prog.update(50, 'halfway')  # should not crash
        prog.close()  # should not crash
        self.assertIsNone(prog._dialog)

        # Create progress dialog
        prog.create('Otaku Sync', 'Syncing watch history...')
        self.assertIsNotNone(prog._dialog)
        self.assertFalse(prog.iscanceled())

        prog.update(75, 'Almost done')
        self.assertEqual(prog._dialog._pct, 75)

        # Close releases underlying SWIG reference
        prog.close()
        self.assertIsNone(prog._dialog)

    def test_settings_and_addon_proxy(self):
        """Test _SettingsProxy and _AddonProxy delegating without holding persistent SWIG objects."""
        addon = control._AddonProxy(control.ADDON_ID)
        self.assertEqual(addon.getAddonInfo('id'), control.ADDON_ID)
        self.assertIsInstance(addon.getLocalizedString(32000), str)

        settings = addon.getSettings()
        self.assertIsInstance(settings, control._SettingsProxy)
        self.assertIsInstance(control.settings.getString('general.source'), str)
        self.assertIsInstance(control.settings.getBool('general.autostart'), bool)
        self.assertIsInstance(control.settings.getInt('general.timeout'), int)
        self.assertIsInstance(control.settings.getNumber('general.timeout'), (int, float))

        # Test list setters/getters
        control.settings.setStringList('test.list', ['a', 'b'])
        self.assertEqual(control.settings.getStringList('test.list'), ['a', 'b'])

    def test_control_cleanup(self):
        """Test control.cleanup explicitly shuts down open dialogs and triggers memory cleanup."""
        control.progressDialog.create('Cleanup Test', 'Working...')
        self.assertIsNotNone(control.progressDialog._dialog)

        with patch('resources.lib.ui.control.clean_memory') as mock_clean:
            control.cleanup()
            self.assertIsNone(control.progressDialog._dialog)
            mock_clean.assert_called_once()

    def test_set_videotags_hdr_migration(self):
        """Test Kodi 22 setHdrType and backward compatible ListItem VideoResolution.HDRType property."""
        li_hdr10 = xbmcgui.ListItem('HDR10 Anime')
        control.set_videotags(li_hdr10, {'title': 'HDR10 Anime', 'hdr_type': 'hdr10'})
        vtag_hdr10 = li_hdr10.getVideoInfoTag()
        self.assertEqual(vtag_hdr10.getHdrType(), 1)
        self.assertEqual(li_hdr10.getProperty('VideoResolution.HDRType'), 'hdr10')

        li_dv = xbmcgui.ListItem('Dolby Vision Anime')
        control.set_videotags(li_dv, {'title': 'DV Anime', 'hdr': 'dolbyvision'})
        vtag_dv = li_dv.getVideoInfoTag()
        self.assertEqual(vtag_dv.getHdrType(), 3)
        self.assertEqual(li_dv.getProperty('VideoResolution.HDRType'), 'dolbyvision')

        li_dv_short = xbmcgui.ListItem('DV Short Anime')
        control.set_videotags(li_dv_short, {'title': 'DV Short Anime', 'hdr_type': 'dv'})
        vtag_dv_short = li_dv_short.getVideoInfoTag()
        self.assertEqual(vtag_dv_short.getHdrType(), 3)
        self.assertEqual(li_dv_short.getProperty('VideoResolution.HDRType'), 'dv')


if __name__ == '__main__':
    unittest.main()
