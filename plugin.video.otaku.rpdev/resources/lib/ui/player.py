"""player.py - Otaku Playback & Playlist Manager
================================================
Manages video playback lifecycle, skip-time processing,
audio/subtitle preferences, watchlist updates, and playlist building.

Architecture
------------
WatchlistPlayer  - Main player class: playback monitoring, skip times, watchlist
PlayerDialogs    - Skip intro / skip outro / playing-next dialog display
Monitor          - Playback error detection with grace period
"""

import time
import threading
import xbmc
import xbmcgui
import pickle
import service
import json

from resources.lib.ui import control, database, source_utils
from resources.lib.endpoints import aniskip, anime_skip
from resources.lib import indexers

playList = control.playList
player = xbmc.Player


# ═══════════════════════════════════════════════════════════════════════════
#  WatchlistPlayer - Playback Lifecycle & Skip Times
# ═══════════════════════════════════════════════════════════════════════════

class WatchlistPlayer(player):
    def __init__(self):
        super(WatchlistPlayer, self).__init__()
        self.player = xbmc.Player()
        self.vtag = None
        self.episode = None
        self.mal_id = None
        self._watchlist_update = None
        self.current_time = 0
        self.updated = False
        self.media_type = None
        self.update_percent = control.getInt('watchlist.update.percent')
        self.resume = None
        self.path = ''
        self.context = False
        self._monitor = None
        self._skip_processed = False

        self.total_time = None
        self.delay_time = control.getInt('skipintro.delay')
        self.skipintro_aniskip_enable = control.getBool('skipintro.aniskip.enable')
        self.skipintro_aniskip_auto = control.getBool('skipintro.aniskip.auto')
        self.skipoutro_aniskip_enable = control.getBool('skipoutro.aniskip.enable')
        self.skipoutro_aniskip_auto = control.getBool('skipoutro.aniskip.auto')

        self.skipintro_aniskip = False
        self.skipoutro_aniskip = False
        self.skipintro_start = control.getInt('skipintro.delay')
        self.skipintro_end = self.skipintro_start + control.getInt('skipintro.duration') * 60
        self.skipoutro_start = 0
        self.skipoutro_end = 0
        self.skipintro_offset = control.getInt('skipintro.aniskip.offset')
        self.skipoutro_offset = control.getInt('skipoutro.aniskip.offset')

        self.preferred_audio = control.getInt('general.audio')
        self.preferred_subtitle_setting = control.getInt('general.subtitles')
        self.preferred_subtitle_type = control.getInt('subtitles.types')
        self.preferred_subtitle_keyword = control.getInt('subtitles.keywords')

        self.ffprobe_chapters = []

    def handle_player(self, mal_id, watchlist_update, episode, resume, path, type, provider, context, ffprobe_chapters=None):
        self.mal_id = mal_id
        self._watchlist_update = watchlist_update
        self.episode = episode
        self.episodes = database.get_episode_list(self.mal_id)
        self.resume = resume
        self.path = path
        self.type = type
        self.provider = provider
        self.context = context
        self.ffprobe_chapters = list(ffprobe_chapters) if ffprobe_chapters else []
        if self.ffprobe_chapters:
            control.log(
                'ffprobe chapters (%d): %s' % (len(self.ffprobe_chapters), [c.get('title') for c in self.ffprobe_chapters]),
                'info',
            )

        # Process skip times asynchronously to not block playback
        if not self._skip_processed:
            self._async_process_skip_times()

        # Continue with playback initialization
        self.keepAlive()

    def _async_process_skip_times(self):
        """Process skip times in background to avoid blocking playback"""
        def _process():
            try:
                self.process_embed('aniwave')
                self.process_embed('hianime')
                self.process_embed('animekai')
                self.process_embed('anikoto')
                self.process_aniskip()
                self.process_animeskip()
                self._skip_processed = True
            except Exception as e:
                control.log(f'Error processing skip times: {e}', 'error')

        import threading
        threading.Thread(target=_process, daemon=True).start()

    # ── Playback Callbacks ────────────────────────────────────────────────

    def onPlayBackStopped(self):
        control.closeAllDialogs()
        playList.clear()
        if self.context and self.path:
            if 10 < self.getWatchedPercent() < 90:
                query = {
                    'jsonrpc': '2.0',
                    'method': 'Files.SetFileDetails',
                    'params': {
                        'file': self.path,
                        'media': 'video',
                        'resume': {
                            'position': self.current_time,
                            'total': self.total_time
                        }
                    },
                    'id': 1
                }
                control.jsonrpc(query)
        control.clean_memory()

    def onPlayBackEnded(self):
        control.closeAllDialogs()
        control.clean_memory()

    def onPlayBackError(self):
        control.closeAllDialogs()
        playList.clear()
        control.clean_memory()

    # ── Playlist Building ─────────────────────────────────────────────────

    def build_playlist(self):
        if not control.getBool('playlist.unaired'):
            from resources.lib.AnimeSchedule import get_anime_schedule
            airing_anime = get_anime_schedule(self.mal_id)

            if airing_anime and airing_anime.get('current_episode'):
                episode_count = airing_anime['current_episode']
                self.episodes = self.episodes[:episode_count]

        video_data = indexers.process_episodes(self.episodes, '') if self.episodes else []
        playlist = control.bulk_dir_list(video_data, True)[self.episode:]

        for i, item in enumerate(playlist):
            url, listitem = item[0], item[1]

            # Calculate the actual episode number based on playlist position
            actual_episode_number = self.episode + i + 1
            payload = f"{self.mal_id}/{actual_episode_number}"

            # Add context menu with correct episode number
            context_menu = [
                ('Playback Options', f'RunPlugin(plugin://{control.ADDON_ID}/playback_options/{payload})'),
                ('Marked as Watched [COLOR blue]WatchList[/COLOR]', f'RunPlugin(plugin://{control.ADDON_ID}/marked_as_watched/{payload})')
            ]
            listitem.addContextMenuItems(context_menu)

            control.playList.add(url=url, listitem=listitem)

    def getWatchedPercent(self):
        return (self.current_time / self.total_time) * 100 if self.total_time != 0 else 0

    def _update_watched_progress(self):
        """Update local SQLite eps_watched and remote watchlist trackers once threshold is reached."""
        if self.updated:
            return
        self.updated = True
        try:
            show_meta = database.get_show(self.mal_id)
            if show_meta and show_meta.get('kodi_meta'):
                kodi_meta = database.loads(show_meta['kodi_meta'])
                current_watched = int(kodi_meta.get('eps_watched') or 0) if str(kodi_meta.get('eps_watched') or 0).isdigit() else 0
                if int(self.episode or 1) > current_watched:
                    kodi_meta['eps_watched'] = int(self.episode or 1)
                    database.update_kodi_meta(self.mal_id, kodi_meta)
        except Exception as e:
            control.log(f'Failed to update local eps_watched: {e}', 'warning')

        try:
            from resources.lib import Main
            Main.save_to_watch_history(self.mal_id, self.episode)
        except Exception as e:
            control.log(f'Failed to update watch history on watched percent: {e}', 'warning')

        if self._watchlist_update:
            any_completed = self._watchlist_update(self.mal_id, self.episode)
            if any_completed:
                xbmc.sleep(3000)
                service.sync_watchlist(True)

    def onWatchedPercent(self):
        while self.isPlaying() and not self.updated:
            self.current_time = self.getTime()
            watched_percentage = (self.current_time / self.total_time) * 100 if self.total_time != 0 else 0

            if watched_percentage > self.update_percent:
                self._update_watched_progress()
                break
            xbmc.sleep(5000)

    def keepAlive(self):
        # Monitor the Playback with optimized wait
        self._monitor = Monitor()
        for i in range(40):  # Increased attempts but shorter waits
            if self._monitor.playbackerror:
                del self._monitor
                return control.log('playbackerror', 'warning')
            if self.isPlayingVideo() and self.getTotalTime() != 0:
                break
            self._monitor.waitForAbort(0.5)  # Check every 0.5 seconds

        # Check if the player is playing a video
        if not self.isPlayingVideo():
            if self._monitor:
                del self._monitor
            control.log('Failed to start video playback', 'warning')
            return

        # Grab the seek time if available
        if self.resume:
            self.seekTime(self.resume)

        # Grab the video tags
        self.vtag = self.getVideoInfoTag()
        self.media_type = self.vtag.getMediaType()
        self.total_time = int(self.getTotalTime())

        # Continue with the rest of the method after playback is confirmed
        unique_ids = database.get_unique_ids(self.mal_id, 'mal_id')

        # Trakt scrobbling support
        if control.getBool('trakt.enabled'):
            control.clearGlobalProp('script.trakt.ids')
            control.setGlobalProp('script.trakt.ids', json.dumps(unique_ids))

        # Always record current show & episode in watch history
        previous_last_watched = control.getSetting('addon.last_watched')
        current_mal_id = str(self.mal_id)
        try:
            from resources.lib import Main
            Main.save_to_watch_history(self.mal_id, self.episode)
        except Exception as e:
            control.log(f'Failed to save watch history: {e}', 'warning')

        if previous_last_watched != current_mal_id:
            control.setSetting('addon.last_watched', current_mal_id)
            control.log(f'Last watched changed from {previous_last_watched} to {current_mal_id}')
            # Defer refresh to avoid blocking playback
            control.setGlobalProp('otaku.menu.needs_refresh', 'true')
        else:
            control.log(f'Last watched show unchanged ({current_mal_id}) - updated episode {self.episode} in watch history')

        # Continue with audio/subtitle setup which is needed immediately
        if self.type not in ['embed', 'direct']:
            self.setup_audio_and_subtitles()
        elif self.provider in ['aniwave', 'hianime', 'anikoto']:
            self.setup_audio_and_subtitles()

        # Handle different media types
        if self.episodes:
            # Handle playlist building if needed
            if self.media_type == 'episode' and playList.size() == 1:
                self.build_playlist()

            # Wait for embed / AniSkip / AnimeSkip, then ffprobe chapters as last fallback
            timeout = 30
            while not self._skip_processed and timeout > 0:
                xbmc.sleep(100)
                timeout -= 1
            self.process_ffprobe_chapter_skips()

            # Unified playback monitoring loop: handles intro skip, watched %, and outro/playing next concurrently
            self._run_unified_episode_monitor()
        else:
            self.onWatchedPercent()

        # Continue monitoring until playback finishes
        while self.isPlaying():
            self.current_time = int(self.getTime())
            xbmc.sleep(5000)

        # Cleanup
        if self._monitor:
            del self._monitor

    # ── Skip Intro / Outro / Playing Next ──────────────────────────────

    def _run_unified_episode_monitor(self):
        """Unified monitoring loop for intro skip, watched percent, and outro/playing next."""
        intro_enabled = control.getBool('smartplay.skipintrodialog') or self.skipintro_aniskip_auto
        intro_start = self.skipintro_start if self.skipintro_aniskip else (control.getInt('skipintro.delay') or 1)
        intro_end = self.skipintro_end if self.skipintro_aniskip else intro_start + (control.getInt('skipintro.duration') * 60)
        intro_handled = not intro_enabled

        playnext_enabled = control.getBool('smartplay.playingnextdialog')
        playnext_time = control.getInt('playingnext.time') if playnext_enabled else 0
        outro_enabled = (playnext_time > 0) or self.skipoutro_aniskip_auto or (self.skipoutro_aniskip and self.skipoutro_start > 0)
        outro_handled = not outro_enabled
        prescrape_triggered = False

        while self.isPlaying() and not (intro_handled and self.updated and outro_handled):
            self.current_time = int(self.getTime())
            if self.total_time <= 0:
                self.total_time = int(self.getTotalTime())

            # 1. Intro Skip check
            if not intro_handled:
                if self.current_time > intro_end:
                    intro_handled = True
                elif self.current_time > intro_start:
                    if self.skipintro_aniskip_auto and self.skipintro_aniskip:
                        self.seekTime(intro_end)
                        control.log(f'Auto-skipped intro: {intro_start}-{intro_end}')
                    else:
                        PlayerDialogs().show_skip_intro(self.skipintro_aniskip, intro_end)
                    intro_handled = True

            # 2. Watched Percentage check & 70% Background Pre-Scraping
            if self.total_time > 0:
                watched_percentage = (self.current_time / self.total_time) * 100
                if not self.updated and watched_percentage > self.update_percent:
                    self._update_watched_progress()

                if not prescrape_triggered and watched_percentage >= 70:
                    prescrape_triggered = True
                    self._trigger_background_prescrape()

            # 3. Outro Skip & Playing Next check
            if not outro_handled and self.total_time > 0:
                time_remaining = self.total_time - self.current_time
                if self.skipoutro_aniskip_auto and self.skipoutro_aniskip and self.current_time >= self.skipoutro_start and self.skipoutro_start > 0:
                    if self.skipoutro_end > 0:
                        self.seekTime(self.skipoutro_end)
                        control.log(f'Auto-skipped outro: {self.skipoutro_start}-{self.skipoutro_end}')
                    outro_handled = True
                elif self._should_show_dialog(time_remaining, playnext_time):
                    if control.getBool('smartplay.binge_mode', default=False):
                        try:
                            cur_ep = int(self.episode)
                            next_ep_str = f"Episode {cur_ep + 1}"
                        except (ValueError, TypeError):
                            next_ep_str = "Next Episode"
                        control.notify(control.ADDON_NAME, f"Up Next: {next_ep_str}...", sound=False)
                        if self.skipoutro_aniskip and self.skipoutro_end > 0:
                            self.seekTime(self.skipoutro_end)
                        outro_handled = True
                    else:
                        if self.skipoutro_aniskip and not self.skipoutro_aniskip_auto:
                            PlayerDialogs().display_dialog(True, self.skipoutro_end)
                        elif not self.skipoutro_aniskip and playnext_time > 0:
                            PlayerDialogs().display_dialog(False, 0)
                        outro_handled = True

            xbmc.sleep(2000)

    def _trigger_background_prescrape(self):
        """Pre-warm scraper cache for the next episode in background at ~70% playback"""
        try:
            if not self.mal_id or getattr(self, 'media_type', None) == 'movie':
                return
            try:
                current_ep = int(self.episode)
            except (ValueError, TypeError):
                return
            next_ep = current_ep + 1

            episode_data = database.get_episode(self.mal_id)
            season = episode_data.get('season') if episode_data else None

            # If a cached season pack already covers next_ep, no background scraping is needed
            cached_pack = database.get_season_pack(self.mal_id, season)
            if cached_pack and source_utils.season_pack_covers_episode(cached_pack, next_ep):
                control.log(f"Player: Pre-scrape bypassed — cached season pack covers ep {next_ep}", level='info')
                return

            def prescrape_worker():
                try:
                    control.log(f"Player: Background pre-scraping ep {next_ep} for {self.mal_id}", level='info')
                    from resources.lib import MetaBrowser
                    MetaBrowser.get_sources(self.mal_id, next_ep, 'show', rescrape=False, source_select=False, silent=True)
                except Exception as e:
                    control.log(f"Player: Pre-scrape background task error: {e}", level='warning')

            t = threading.Thread(target=prescrape_worker, name="Otaku-PreScrapeThread")
            t.daemon = True
            t.start()
        except Exception as e:
            control.log(f"Player: Failed to launch pre-scrape: {e}", level='warning')

    def _should_show_dialog(self, time_remaining, playnext_time):
        """Determine if we should show a dialog - simplified"""
        if self.skipoutro_aniskip and not self.skipoutro_aniskip_auto:
            return self.current_time >= self.skipoutro_start and self.skipoutro_start > 0
        elif not self.skipoutro_aniskip and playnext_time > 0:
            return time_remaining <= playnext_time
        return False

    # ── Audio & Subtitle Setup ────────────────────────────────────────

    def setup_audio_and_subtitles(self):
        """Handle audio and subtitle setup"""
        # This contains your existing audio/subtitle setup code from keepAlive
        if not control.getBool('general.kodi_language'):
            query = {
                'jsonrpc': '2.0',
                "method": "Player.GetProperties",
                "params": {
                    "playerid": 1,
                    "properties": ["subtitles", "audiostreams"]
                },
                "id": 1
            }

            audios = ['jpn', 'eng']

            subtitles = [
                "none", "eng", "jpn", "spa", "fre", "ger",
                "ita", "dut", "rus", "por", "kor", "chi",
                "ara", "hin", "tur", "pol", "swe", "nor",
                "dan", "fin"
            ]

            types = [
                "isdefault", "isforced", "isimpaired"
            ]

            keywords = {
                1: 'dialogue',
                2: ['signs', 'songs'],
                3: control.getSetting('subtitles.customkeyword')
            }

            response = control.jsonrpc(query)

            if 'result' in response:
                player_properties = response['result']
                audio_streams = player_properties.get('audiostreams', [])
                subtitle_streams = player_properties.get('subtitles', [])
            else:
                audio_streams = []
                subtitle_streams = []

            preferred_audio_streams = audios[self.preferred_audio]
            preferred_subtitle_lang = subtitles[self.preferred_subtitle_setting]
            preffeded_subtitle_type = types[self.preferred_subtitle_type]
            preffeded_subtitle_keyword = keywords[self.preferred_subtitle_keyword]

            # Set preferred audio stream
            for stream in audio_streams:
                if stream['language'] == preferred_audio_streams:
                    self.setAudioStream(stream['index'])
                    break
            else:
                # If no preferred audio stream is found, set to the default audio stream
                for stream in audio_streams:
                    if stream.get('isdefault', False):
                        self.setAudioStream(stream['index'])
                        break
                else:
                    # If no default audio stream is found, set to the first available audio stream
                    if audio_streams:
                        self.setAudioStream(audio_streams[0]['index'])

            # Set preferred subtitle stream
            subtitle_int = None

            # Lowercase preferred keyword(s) like sub_name_lower
            if isinstance(preffeded_subtitle_keyword, list):
                preffeded_subtitle_keyword = [kw.lower() for kw in preffeded_subtitle_keyword if isinstance(kw, str)]
            elif isinstance(preffeded_subtitle_keyword, str):
                preffeded_subtitle_keyword = preffeded_subtitle_keyword.lower()

            # Type and Keyword filtering
            if control.getBool('general.subtitles.keyword') or control.getBool('general.subtitles.type'):
                for index, sub in enumerate(subtitle_streams):

                    # Check for type match
                    if control.getBool('general.subtitles.type'):
                        if sub['language'] == preferred_subtitle_lang:
                            if sub[preffeded_subtitle_type]:
                                subtitle_int = index
                                break

                    # Check for keyword match
                    if control.getBool('general.subtitles.keyword'):
                        if sub['language'] == preferred_subtitle_lang:
                            sub_name_lower = sub['name'].lower()
                            if isinstance(preffeded_subtitle_keyword, list):
                                if any(kw in sub_name_lower for kw in preffeded_subtitle_keyword):
                                    subtitle_int = index
                                    break
                            elif preffeded_subtitle_keyword and preffeded_subtitle_keyword in sub_name_lower:
                                subtitle_int = index
                                break

                # fallback to first of preferred language if no type or keyword match
                if subtitle_int is None:
                    for index, sub in enumerate(subtitle_streams):
                        if sub['language'] == preferred_subtitle_lang:
                            subtitle_int = index
                            break
            else:
                # No type filter or keyword filter, just check for preferred language
                for index, sub in enumerate(subtitle_streams):
                    if sub['language'] == preferred_subtitle_lang:
                        subtitle_int = index
                        break

            if subtitle_int is None:
                # default-subtitle fallback
                for index, sub in enumerate(subtitle_streams):
                    if sub.get('isdefault', False):
                        subtitle_int = index
                        break
                else:
                    # If no default subtitle stream is found, set to the first available subtitle stream
                    subtitle_int = 0

            if subtitle_int is not None:
                self.setSubtitleStream(subtitle_int)

            # Enable and Disable Subtitles based on audio streams
            if len(audio_streams) == 1:
                single_lang = audio_streams[0].get('language', '')
                if single_lang != "jpn":
                    if control.getBool('general.dubsubtitles'):
                        if preferred_subtitle_lang == "none":
                            self.showSubtitles(False)
                        else:
                            self.showSubtitles(True)
                    else:
                        self.showSubtitles(False)
                elif single_lang != "eng":
                    if preferred_subtitle_lang == "none":
                        self.showSubtitles(False)
                    else:
                        self.showSubtitles(True)

            if len(audio_streams) > 1:
                if preferred_audio_streams == "eng":
                    if control.getBool('general.dubsubtitles'):
                        if preferred_subtitle_lang == "none":
                            self.showSubtitles(False)
                        else:
                            self.showSubtitles(True)
                    else:
                        self.showSubtitles(False)

                if preferred_audio_streams == "jpn":
                    if preferred_subtitle_lang == "none":
                        self.showSubtitles(False)
                    else:
                        self.showSubtitles(True)

    # ── Skip Time Processing (AniSkip / AnimeSkip / Embed / FFprobe chapters) ─

    def process_ffprobe_chapter_skips(self):
        """
        Last-resort intro/outro windows from ffprobe chapter titles + timestamps.
        Runs only after embed / AniSkip / AnimeSkip; does not override them.
        """
        if not control.getBool('ffprobe.chapters.enable'):
            return
        if not self.ffprobe_chapters or not self.total_time:
            return

        total = float(self.total_time)
        # Allow small clock slop vs container duration
        max_end = total + 5.0

        if self.skipintro_aniskip_enable and not self.skipintro_aniskip:
            intro_cap = max(600.0, total * 0.25)
            for ch in sorted(self.ffprobe_chapters, key=lambda c: float(c.get('start', 0) or 0)):
                title = ch.get('title') or ''
                if not source_utils.chapter_title_matches_intro(title):
                    continue
                start = float(ch.get('start', 0)) + self.skipintro_offset
                end = float(ch.get('end', 0)) + self.skipintro_offset
                duration = end - start
                if (
                    0 <= start < end <= max_end
                    and duration >= 4.0
                    and duration <= 360.0
                    and start <= intro_cap
                ):
                    self.skipintro_start = int(start)
                    self.skipintro_end = int(end)
                    self.skipintro_aniskip = True
                    control.log(
                        'ffprobe chapter intro fallback [%s] %s-%ss'
                        % (title, self.skipintro_start, self.skipintro_end),
                        'info',
                    )
                    break

        if self.skipoutro_aniskip_enable and not self.skipoutro_aniskip:
            preview_only_markers = (
                'next episode',
                'next time',
                '次回予告',
                'episode preview',
                'web preview',
            )
            outro_candidates = []
            for ch in sorted(self.ffprobe_chapters, key=lambda c: float(c.get('start', 0) or 0)):
                title = ch.get('title') or ''
                if not source_utils.chapter_title_matches_outro(title):
                    continue
                st = float(ch.get('start', 0) or 0)
                if st < total * 0.45:
                    continue
                tlow = title.lower()
                if any(m in tlow for m in preview_only_markers) and not any(
                    k in tlow for k in ('ending', 'credit', 'nced', 'エンディング')
                ):
                    continue
                outro_candidates.append(ch)

            if outro_candidates:
                outro_ch = outro_candidates[0]
                title = outro_ch.get('title') or ''
                start = float(outro_ch.get('start', 0)) + self.skipoutro_offset
                end = float(outro_ch.get('end', 0)) + self.skipoutro_offset
                duration = end - start
                if (
                    start < end <= max_end
                    and duration >= 4.0
                    and duration <= 600.0
                    and start >= total * 0.4
                ):
                    self.skipoutro_start = int(start)
                    self.skipoutro_end = int(end)
                    self.skipoutro_aniskip = True
                    control.log(
                        'ffprobe chapter outro fallback [%s] %s-%ss'
                        % (title, self.skipoutro_start, self.skipoutro_end),
                        'info',
                    )

    def process_aniskip(self):
        if self.skipintro_aniskip_enable and not self.skipintro_aniskip:
            skipintro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'op')
            if skipintro_aniskip_res:
                skip_times = skipintro_aniskip_res['results'][0]['interval']
                self.skipintro_start = int(skip_times['startTime']) + self.skipintro_offset
                self.skipintro_end = int(skip_times['endTime']) + self.skipintro_offset
                self.skipintro_aniskip = True

        if self.skipoutro_aniskip_enable and not self.skipoutro_aniskip:
            skipoutro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'ed')
            if skipoutro_aniskip_res:
                skip_times = skipoutro_aniskip_res['results'][0]['interval']
                self.skipoutro_start = int(skip_times['startTime']) + self.skipoutro_offset
                self.skipoutro_end = int(skip_times['endTime']) + self.skipoutro_offset
                self.skipoutro_aniskip = True

    def process_animeskip(self):
        show_meta = database.get_show_meta(self.mal_id)
        if not show_meta or not show_meta.get('meta_ids'):
            return
        anilist_id = database.loads(show_meta['meta_ids']).get('anilist_id')

        if (self.skipintro_aniskip_enable and not self.skipintro_aniskip) or (self.skipoutro_aniskip_enable and not self.skipoutro_aniskip):
            skip_times = anime_skip.get_time_stamps(anime_skip.get_episode_ids(str(anilist_id), int(self.episode)))
            intro_start = None
            intro_end = None
            outro_start = None
            outro_end = None
            if skip_times:
                for skip in skip_times:
                    if self.skipintro_aniskip_enable and not self.skipintro_aniskip:
                        if intro_start is None and skip['type']['name'] in ['Intro', 'New Intro', 'Branding']:
                            intro_start = int(skip['at'])
                        elif intro_end is None and intro_start is not None and skip['type']['name'] in ['Canon']:
                            intro_end = int(skip['at'])
                    if self.skipoutro_aniskip_enable and not self.skipoutro_aniskip:
                        if outro_start is None and skip['type']['name'] in ['Credits', 'New Credits']:
                            outro_start = int(skip['at'])
                        elif outro_end is None and outro_start is not None and skip['type']['name'] in ['Canon', 'Preview']:
                            outro_end = int(skip['at'])

            if intro_start is not None and intro_end is not None:
                self.skipintro_start = intro_start + self.skipintro_offset
                self.skipintro_end = intro_end + self.skipintro_offset
                self.skipintro_aniskip = True
            if outro_start is not None and outro_end is not None:
                self.skipoutro_start = int(outro_start) + self.skipoutro_offset
                self.skipoutro_end = int(outro_end) + self.skipoutro_offset
                self.skipoutro_aniskip = True

    def process_embed(self, embed):
        if self.skipintro_aniskip_enable and not self.skipintro_aniskip:
            embed_skipintro_start = control.getInt(f'{embed}.skipintro.start')
            if embed_skipintro_start != -1:
                self.skipintro_start = embed_skipintro_start + self.skipintro_offset
                self.skipintro_end = control.getInt(f'{embed}.skipintro.end') + self.skipintro_offset
                self.skipintro_aniskip = True
        if self.skipoutro_aniskip_enable and not self.skipoutro_aniskip:
            embed_skipoutro_start = control.getInt(f'{embed}.skipoutro.start')
            if embed_skipoutro_start != -1:
                self.skipoutro_start = embed_skipoutro_start + self.skipoutro_offset
                self.skipoutro_end = control.getInt(f'{embed}.skipoutro.end') + self.skipoutro_offset
                self.skipoutro_aniskip = True


# ═══════════════════════════════════════════════════════════════════════════
#  PlayerDialogs - Skip Intro / Outro / Playing Next
# ═══════════════════════════════════════════════════════════════════════════

class PlayerDialogs(xbmc.Player):
    def __init__(self):
        super(PlayerDialogs, self).__init__()
        self.playing_file = self.getPlayingFile()

    def display_dialog(self, skipoutro_aniskip, skipoutro_end):
        if playList.size() == 0 or playList.getposition() == (playList.size() - 1):
            return
        if self.playing_file != self.getPlayingFile() or not self.isPlayingVideo() or not self._is_video_window_open():
            return
        self._show_playing_next(skipoutro_aniskip, skipoutro_end)

    def _show_playing_next(self, skipoutro_aniskip, skipoutro_end):
        from resources.lib.windows.playing_next import PlayingNext
        args = self._get_next_item_args()
        args['skipoutro_end'] = skipoutro_end
        if skipoutro_aniskip:
            dialog_mapping = {
                0: 'skip_outro_default.xml',
                1: 'skip_outro_ah2.xml',
                2: 'skip_outro_auramod.xml',
                3: 'skip_outro_af.xml',
                4: 'skip_outro_af2.xml',
                5: 'skip_outro_az.xml',
                6: 'skip_outro_tb.xml'
            }

            setting_value = control.getInt('general.dialog')
            xml_file = dialog_mapping.get(setting_value)

            # Call PlayingNext with the retrieved XML file
            if xml_file:
                PlayingNext(xml_file, control.ADDON_PATH, actionArgs=args).doModal()
        else:
            dialog_mapping = {
                0: 'playing_next_default.xml',
                1: 'playing_next_ah2.xml',
                2: 'playing_next_auramod.xml',
                3: 'playing_next_af.xml',
                4: 'playing_next_af2.xml',
                5: 'playing_next_az.xml',
                6: 'playing_next_tb.xml'
            }

            setting_value = control.getInt('general.dialog')
            xml_file = dialog_mapping.get(setting_value)

            # Call PlayingNext with the retrieved XML file
            if xml_file:
                PlayingNext(xml_file, control.ADDON_PATH, actionArgs=args).doModal()

    @staticmethod
    def show_skip_intro(skipintro_aniskip, skipintro_end):
        from resources.lib.windows.skip_intro import SkipIntro
        args = {
            'item_type': 'skip_intro',
            'skipintro_aniskip': skipintro_aniskip,
            'skipintro_end': skipintro_end
        }

        dialog_mapping = {
            0: 'skip_intro_default.xml',
            1: 'skip_intro_ah2.xml',
            2: 'skip_intro_auramod.xml',
            3: 'skip_intro_af.xml',
            4: 'skip_intro_af2.xml',
            5: 'skip_intro_az.xml',
            6: 'skip_intro_tb.xml'
        }

        setting_value = control.getInt('general.dialog')
        xml_file = dialog_mapping.get(setting_value)

        # Call SkipIntro with the retrieved XML file
        if xml_file:
            SkipIntro(xml_file, control.ADDON_PATH, actionArgs=args).doModal()

    @staticmethod
    def _get_next_item_args():
        current_position = playList.getposition()
        _next_info = playList[current_position + 1]
        next_info = {
            'item_type': "playing_next",
            'thumb': [_next_info.getArt('thumb')],
            'name': _next_info.getLabel()
        }
        return next_info

    @staticmethod
    def _is_video_window_open():
        return False if xbmcgui.getCurrentWindowId() != 12005 else True


# ═══════════════════════════════════════════════════════════════════════════
#  Monitor - Playback Error Detection
# ═══════════════════════════════════════════════════════════════════════════

class Monitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.playbackerror = False
        self._playback_started = False
        self._created = time.time()

    def onNotification(self, sender, method, data):
        if method == 'Player.OnAVStart':
            self._playback_started = True
            self.playbackerror = False
        elif method == 'Player.OnStop':
            # Ignore OnStop events within 2 seconds of creation — these are
            # leftover from the previous episode's stop (playlist transitions).
            if time.time() - self._created < 2:
                return
            if not self._playback_started:
                self.playbackerror = True
