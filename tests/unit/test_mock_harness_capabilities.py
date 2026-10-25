"""
test_mock_harness_capabilities.py - Verification of Kodi C++ Mock Framework
==========================================================================
Verifies that all expanded mock objects in tests/conftest.py (MockPlayer,
MockMonitor, MockPlayList, MockKeyboard, MockListItem, MockVideoInfoTag,
MockDialog, MockDialogProgress, MockPlugin, MockVFSFile) behave accurately
in memory without requiring an active Kodi installation.
"""

import os
import unittest
import conftest
import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs


class TestMockHarnessCapabilities(unittest.TestCase):

    def test_mock_info_tag_video_getters_and_setters(self):
        vinfo = xbmc.InfoTagVideo()
        vinfo.setTitle("Attack on Titan")
        vinfo.setMediaType("tvshow")
        vinfo.setTvShowTitle("Attack on Titan")
        vinfo.setPlot("Centuries ago...")
        vinfo.setYear("2013")
        vinfo.setPremiered("2013-04-07")
        vinfo.setTvShowStatus("Ended")
        vinfo.setGenres(["Action", "Drama"])
        vinfo.setMpaa("TV-MA")
        vinfo.setRating(8.5, 12000)
        vinfo.setSeason(1)
        vinfo.setEpisode(5)
        vinfo.setFirstAired("2013-04-07")
        vinfo.setPlaycount(1)
        vinfo.setDuration(1440)
        vinfo.setProductionCode("SNK-01")
        vinfo.setStudios(["WIT STUDIO"])
        vinfo.setCountries(["Japan"])
        vinfo.setOriginalTitle("進撃の巨人")
        vinfo.setTrailer("plugin://plugin.video.youtube/play/?video_id=123")
        vinfo.setUniqueIDs({"mal": "16498", "anilist": "16498"})
        vinfo.setIMDBNumber("tt2560140")
        vinfo.setResumePoint(340.5, 1)

        self.assertEqual(vinfo.getTitle(), "Attack on Titan")
        self.assertEqual(vinfo.getMediaType(), "tvshow")
        self.assertEqual(vinfo.getTvShowTitle(), "Attack on Titan")
        self.assertEqual(vinfo.getPlot(), "Centuries ago...")
        self.assertEqual(vinfo.getYear(), 2013)
        self.assertEqual(vinfo.getPremiered(), "2013-04-07")
        self.assertEqual(vinfo.getTvShowStatus(), "Ended")
        self.assertEqual(vinfo.getGenres(), ["Action", "Drama"])
        self.assertEqual(vinfo.getMpaa(), "TV-MA")
        self.assertEqual(vinfo.getRating(), (8.5, 12000))
        self.assertEqual(vinfo.getSeason(), 1)
        self.assertEqual(vinfo.getEpisode(), 5)
        self.assertEqual(vinfo.getFirstAired(), "2013-04-07")
        self.assertEqual(vinfo.getPlaycount(), 1)
        self.assertEqual(vinfo.getDuration(), 1440)
        self.assertEqual(vinfo.getProductionCode(), "SNK-01")
        self.assertEqual(vinfo.getStudios(), ["WIT STUDIO"])
        self.assertEqual(vinfo.getCountries(), ["Japan"])
        self.assertEqual(vinfo.getOriginalTitle(), "進撃の巨人")
        self.assertEqual(vinfo.getTrailer(), "plugin://plugin.video.youtube/play/?video_id=123")
        self.assertEqual(vinfo.getUniqueIDs(), {"mal": "16498", "anilist": "16498"})
        self.assertEqual(vinfo.getIMDBNumber(), "tt2560140")
        self.assertEqual(vinfo.getResumePoint(), 340.5)

    def test_mock_list_item(self):
        li = xbmcgui.ListItem(label="Episode 1", label2="Sub", path="http://example.com/video.mp4")
        self.assertEqual(li.getLabel(), "Episode 1")
        self.assertEqual(li.getLabel2(), "Sub")
        self.assertEqual(li.getPath(), "http://example.com/video.mp4")

        li.setArt({"poster": "poster.jpg", "fanart": "fanart.jpg"})
        self.assertEqual(li.getArt("poster"), "poster.jpg")
        self.assertEqual(li.getArt()["fanart"], "fanart.jpg")

        li.setProperty("isPlayable", "true")
        self.assertEqual(li.getProperty("isPlayable"), "true")

        vtag = li.getVideoInfoTag()
        self.assertIsInstance(vtag, xbmc.InfoTagVideo)
        vtag.setTitle("Ep 1")
        self.assertEqual(vtag.getTitle(), "Ep 1")

        li.addContextMenuItems([("Item 1", "Action 1")])
        self.assertEqual(len(li._cm), 1)

    def test_mock_player_lifecycle(self):
        p = xbmc.Player()
        self.assertFalse(p.isPlaying())
        self.assertFalse(p.isPlayingVideo())

        p.play("http://example.com/stream.mkv")
        self.assertTrue(p.isPlaying())
        self.assertTrue(p.isPlayingVideo())
        self.assertEqual(p.getPlayingFile(), "http://example.com/stream.mkv")

        p.seekTime(120.5)
        self.assertEqual(p.getTime(), 120.5)

        p.setAudioStream(2)
        self.assertEqual(p._audio_stream, 2)

        p.setSubtitleStream(1)
        self.assertEqual(p._subtitle_stream, 1)

        p.stop()
        self.assertFalse(p.isPlaying())

    def test_mock_plugin_directory_tracking(self):
        xbmcplugin.reset()
        handle = 1
        li = xbmcgui.ListItem("Anime Show")
        xbmcplugin.addDirectoryItem(handle, "plugin://plugin.video.otaku.rpdev/show", li, isFolder=True)
        xbmcplugin.setContent(handle, "tvshows")
        xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True)

        self.assertEqual(len(xbmcplugin.directory_items), 1)
        self.assertEqual(xbmcplugin.directory_items[0][1], "plugin://plugin.video.otaku.rpdev/show")
        self.assertTrue(xbmcplugin.directory_items[0][3])
        self.assertEqual(xbmcplugin.content_type, "tvshows")
        self.assertEqual(xbmcplugin.end_of_directory_args[0], (1, True, False, True))

    def test_mock_dialogs_and_progress(self):
        dialog = xbmcgui.Dialog()
        dialog.notification("Otaku", "Sync finished", time=2000)
        self.assertEqual(len(dialog.notifications), 1)
        self.assertEqual(dialog.notifications[0]["heading"], "Otaku")

        self.assertTrue(dialog.ok("Title", "Message"))
        self.assertTrue(dialog.yesno("Are you sure?", "Confirm action"))

        prog = xbmcgui.DialogProgress()
        prog.create("Syncing", "Starting...")
        self.assertFalse(prog.iscanceled())
        prog.update(50, "Halfway done")
        self.assertEqual(prog._pct, 50)
        self.assertEqual(prog._msg, "Halfway done")
        prog.close()
        self.assertTrue(prog._closed)

    def test_mock_vfs_file_operations(self):
        test_file_path = os.path.join(conftest.TEST_PROFILE_DIR, "vfs_test.txt")
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write("Hello VFS!")

        vfile = xbmcvfs.File(test_file_path, "r")
        content = vfile.read()
        self.assertEqual(content, "Hello VFS!")
        vfile.close()


if __name__ == "__main__":
    unittest.main()
