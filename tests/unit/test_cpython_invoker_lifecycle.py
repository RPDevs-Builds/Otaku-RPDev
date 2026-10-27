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

    def test_kodi22_videotags_metadata_extensions(self):
        """Test Kodi 22 InfoTagVideo SeasonPlot, AvailableFanart, bidirectional Year fallback, and strict typing."""
        # Test Year fallback from Premiered (and Premiered fallback from Year)
        li_prem = xbmcgui.ListItem('Fall Show')
        control.set_videotags(li_prem, {'title': 'Fall Show', 'premiered': '2024-10-15'})
        vtag_prem = li_prem.getVideoInfoTag()
        self.assertEqual(vtag_prem.getYear(), 2024)
        self.assertEqual(vtag_prem.getPremiered(), '2024-10-15')

        li_year = xbmcgui.ListItem('Spring Show')
        control.set_videotags(li_year, {'title': 'Spring Show', 'year': '2025'})
        vtag_year = li_year.getVideoInfoTag()
        self.assertEqual(vtag_year.getYear(), 2025)
        self.assertEqual(vtag_year.getPremiered(), '2025-01-01')

        # Test SeasonPlot & AvailableFanart
        li_full = xbmcgui.ListItem('Full Metadata Anime')
        control.set_videotags(li_full, {
            'title': 'Full Show',
            'season_plot': 'Season 2 follows the journey...',
            'available_fanart': ['http://example.com/fanart1.jpg', 'http://example.com/fanart2.jpg'],
            'mpaa': 'TV-14',
            'status': 'Continuing',
            'plot': 'Show plot description',
        })
        vtag_full = li_full.getVideoInfoTag()
        self.assertEqual(vtag_full.getSeasonPlot(), 'Season 2 follows the journey...')
        self.assertEqual(len(vtag_full.getAvailableFanart()), 2)
        self.assertEqual(li_full.getProperty('SeasonPlot'), 'Season 2 follows the journey...')

        # Test strict type coercion with None/unclean fields (must never raise exceptions)
        li_dirty = xbmcgui.ListItem('Dirty Metadata Show')
        control.set_videotags(li_dirty, {
            'title': 12345,  # non-string title
            'plot': None,
            'year': 'invalid_year',
            'rating': None,
            'studio': [None, 'MAPPA', ''],
            'country': None,
            'trailer': None,
        })
        vtag_dirty = li_dirty.getVideoInfoTag()
        self.assertEqual(vtag_dirty.getTitle(), '12345')
        self.assertEqual(vtag_dirty.getStudios(), ['MAPPA'])

    def test_kodi22_power_and_cec_helpers(self):
        """Test Kodi 22 native device power state, CEC adapters, and database name helpers."""
        self.assertEqual(control.get_device_power_status(), 'on')
        self.assertFalse(control.is_device_in_standby())
        self.assertEqual(control.get_cec_adapter_names(), [])

        # Test mock power status
        with patch.object(xbmc, 'getDevicePowerStatus', return_value='standby', create=True):
            self.assertEqual(control.get_device_power_status(), 'standby')
            self.assertTrue(control.is_device_in_standby())

        # Test get_database_name resolution
        db_name = control.get_database_name('video')
        self.assertTrue('MyVideos' in db_name or db_name.endswith('.db'))

    def test_kodi22_bcp47_subtitle_precision(self):
        """Test exact BCP 47 matching bonus in score_subtitle_stream."""
        from resources.lib.ui.player import score_subtitle_stream
        sub_pt_br = {'language': 'pt-br', 'name': 'Portuguese (Brazil)'}
        sub_pt_pt = {'language': 'pt-pt', 'name': 'Portuguese (Portugal)'}

        score_br = score_subtitle_stream(sub_pt_br, target_mode='dialog', preferred_lang='pt-br')
        score_pt = score_subtitle_stream(sub_pt_pt, target_mode='dialog', preferred_lang='pt-br')

        # Exact BCP 47 match must outscore generic family match by +200
        self.assertGreater(score_br, score_pt)
        self.assertEqual(score_br - score_pt, 200)


if __name__ == '__main__':
    unittest.main()
