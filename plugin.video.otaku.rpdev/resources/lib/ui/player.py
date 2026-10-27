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
import service
import json

from resources.lib.ui import control, database, source_utils
from resources.lib.endpoints import aniskip, anime_skip
from resources.lib import indexers

playList = control.playList
player = xbmc.Player


# ── Intelligent Subtitle Track Selection Heuristics ──────────────────────

SIGNS_SUBTITLE_KEYWORDS = ('signs', 'songs', 's&s', 's/s', 's & s', 's_s', 'forced')
DIALOG_SUBTITLE_KEYWORDS = ('dialogue', 'dialog', 'full', 'main', 'complete')

LANGUAGE_SYNONYMS = {
    'eng': {'eng', 'en', 'en-us', 'en-gb', 'en-au', 'en-ca', 'english'},
    'jpn': {'jpn', 'ja', 'ja-jp', 'japanese', 'jap'},
    'spa': {'spa', 'es', 'es-es', 'es-419', 'es-la', 'es-mx', 'spanish', 'español', 'espanol'},
    'fre': {'fre', 'fra', 'fr', 'fr-fr', 'fr-ca', 'french', 'français', 'francais'},
    'ger': {'ger', 'deu', 'de', 'de-de', 'de-at', 'de-ch', 'german', 'deutsch'},
    'ita': {'ita', 'it', 'it-it', 'italian', 'italiano'},
    'dut': {'dut', 'nld', 'nl', 'nl-nl', 'dutch', 'nederlands'},
    'rus': {'rus', 'ru', 'ru-ru', 'russian', 'русский'},
    'por': {'por', 'pt', 'pt-pt', 'pt-br', 'portuguese', 'português', 'portugues'},
    'kor': {'kor', 'ko', 'ko-kr', 'korean', '한국어'},
    'chi': {'chi', 'zho', 'zh', 'zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'chinese', '中文'},
    'ara': {'ara', 'ar', 'arabic', 'العربية'},
    'hin': {'hin', 'hi', 'hindi', 'हिन्दी'},
    'tur': {'tur', 'tr', 'turkish', 'türkçe'},
    'pol': {'pol', 'pl', 'polish', 'polski'},
    'swe': {'swe', 'sv', 'swedish', 'svenska'},
    'nor': {'nor', 'no', 'norwegian', 'norsk'},
    'dan': {'dan', 'da', 'danish', 'dansk'},
    'fin': {'fin', 'fi', 'finnish', 'suomi'},
}


def is_language_match(stream_lang, stream_name, target_lang):
    """
    Check if a stream's language code or name matches the target language.
    Handles Kodi 22 BCP 47 (en, ja, fr), ISO 639-2 (eng, jpn, fra), and full language names.
    """
    if not target_lang:
        return False
    target = target_lang.lower().strip()

    # Find the synonym set for the target
    synonyms = LANGUAGE_SYNONYMS.get(target)
    if not synonyms:
        for k, syns in LANGUAGE_SYNONYMS.items():
            if target in syns:
                synonyms = syns
                break
        else:
            synonyms = {target}

    s_lang = (stream_lang or '').lower().strip()
    s_lang_prefix = s_lang.split('-')[0].split('_')[0] if s_lang else ''

    if s_lang in synonyms or (s_lang_prefix and s_lang_prefix in synonyms):
        return True

    s_name = (stream_name or '').lower().strip()
    if s_name:
        for syn in synonyms:
            if len(syn) > 2 and syn in s_name:
                return True

    return False


def score_subtitle_stream(sub, target_mode='dialog', preferred_lang='eng', custom_keyword='', preferred_type='isdefault'):
    """
    Score a subtitle stream candidate for intelligent selection.

    :param sub: dict containing 'index', 'name', 'language', 'isdefault', 'isforced', 'isimpaired'
    :param target_mode: 'dialog', 'signs', 'custom', or None
    :param preferred_lang: e.g. 'eng', 'jpn'
    :param custom_keyword: string keyword when target_mode == 'custom'
    :param preferred_type: 'isdefault', 'isforced', 'isimpaired'
    :return: integer score
    """
    sub_lang = (sub.get('language') or '').lower()
    sub_name = (sub.get('name') or '').lower()
    is_default = bool(sub.get('isdefault', False))
    is_forced = bool(sub.get('isforced', False))
    is_impaired = bool(sub.get('isimpaired', False))

    score = 0

    # 1. Preferred Language Match (handles Kodi 22 BCP 47 'en', 'ja', 'pt-br', etc.)
    if preferred_lang and is_language_match(sub_lang, sub_name, preferred_lang):
        # Exact BCP 47 tag match receives higher priority (+1200) over generic language family match (+1000)
        if preferred_lang.lower().strip() == sub_lang.strip():
            score += 1200
        else:
            score += 1000
    elif sub_lang:
        # Penalize non-matching languages when preferred_lang is specified
        score -= 200

    has_signs = any(kw in sub_name for kw in SIGNS_SUBTITLE_KEYWORDS) or is_forced
    has_dialog = any(kw in sub_name for kw in DIALOG_SUBTITLE_KEYWORDS)

    # 2. Target Mode Evaluation
    if target_mode == 'dialog':
        if has_signs:
            score -= 500  # Strong penalty: reject Signs & Songs when Full Dialogue is desired
        elif has_dialog:
            score += 200  # Explicitly marked as dialogue / full
        else:
            score += 100  # Clean unmarked track (e.g. "English" or "") is standard dialogue

        if is_impaired:
            score -= 50  # Deprioritize SDH / impaired unless requested

    elif target_mode == 'signs':
        if has_signs:
            score += 200  # Explicit Signs & Songs / Forced track
        elif has_dialog:
            score -= 500  # Reject Full Dialogue when Signs & Songs is desired
        else:
            score -= 100  # Clean track without signs marker is unlikely to be signs-only

    elif target_mode == 'custom':
        custom_kw = (custom_keyword or '').lower().strip()
        if custom_kw and custom_kw in sub_name:
            score += 250
        elif custom_kw:
            score -= 100

    # 3. Type Attribute Modifiers (Tie-Breaker / Minor preference)
    if preferred_type and sub.get(preferred_type, False):
        score += 10

    # 4. Default Container Flag (Tie-Breaker Only)
    if is_default:
        score += 5

    return score


def select_subtitle_stream(subtitle_streams, target_mode='dialog', preferred_lang='eng', custom_keyword='', preferred_type='isdefault'):
    """
    Select the optimal subtitle stream index from available streams.
    Returns the integer index of the selected stream, or None if no streams available.
    """
    if not subtitle_streams:
        return None

    scored = []
    for idx, sub in enumerate(subtitle_streams):
        stream_index = sub.get('index', idx)
        score = score_subtitle_stream(
            sub,
            target_mode=target_mode,
            preferred_lang=preferred_lang,
            custom_keyword=custom_keyword,
            preferred_type=preferred_type
        )
        scored.append((score, stream_index))

    # Sort descending by score; on ties, preserve earlier stream index
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


# ═══════════════════════════════════════════════════════════════════════════
#  WatchlistPlayer - Playback Lifecycle & Skip Times
# ═══════════════════════════════════════════════════════════════════════════

class WatchlistPlayer(player):
    def __init__(self):
        super().__init__()
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
            if getattr(self, 'total_time', 0) > 60 and 0 < getattr(self, 'current_time', 0) < self.total_time:
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
        if self.episodes and self.media_type == 'episode' and playList.size() == 1:
            self.build_playlist()

        if self.media_type != 'movie':
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
        intro_handled = not intro_enabled

        playnext_enabled = control.getBool('smartplay.playingnextdialog')
        playnext_time = control.getInt('playingnext.time') if playnext_enabled else 0
        outro_enabled = (playnext_time > 0) or self.skipoutro_aniskip_auto or (self.skipoutro_aniskip and self.skipoutro_start > 0)
        outro_handled = not outro_enabled
        prescrape_triggered = False

        while self.isPlaying() and not (intro_handled and self.updated and outro_handled):
            # When player is paused, yield to prevent CPU churn and preserve hardware-plane rendering
            if xbmc.getCondVisibility("Player.Paused"):
                xbmc.sleep(1000)
                continue

            self.current_time = int(self.getTime())
            if self.total_time <= 0:
                self.total_time = int(self.getTotalTime())

            intro_start = self.skipintro_start if self.skipintro_aniskip else (control.getInt('skipintro.delay') or 1)
            intro_end = self.skipintro_end if self.skipintro_aniskip else intro_start + (control.getInt('skipintro.duration') * 60)

            # 1. Intro Skip check
            if not intro_handled:
                if self.current_time > intro_end:
                    intro_handled = True
                elif self.current_time >= intro_start:
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

            t = threading.Thread(target=prescrape_worker, name="Otaku-PreScrapeThread", daemon=True)
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

            # Allow Kodi's demuxer a brief window to asynchronously populate stream lists
            audio_streams = []
            subtitle_streams = []
            for attempt in range(10):
                response = control.jsonrpc(query)
                if 'result' in response:
                    player_properties = response['result']
                    audio_streams = player_properties.get('audiostreams', [])
                    subtitle_streams = player_properties.get('subtitles', [])
                    if audio_streams or subtitle_streams:
                        break
                xbmc.sleep(200)

            preferred_audio_streams = audios[self.preferred_audio] if self.preferred_audio < len(audios) else 'jpn'
            preferred_subtitle_lang = subtitles[self.preferred_subtitle_setting] if self.preferred_subtitle_setting < len(subtitles) else 'eng'
            preferred_subtitle_type = types[self.preferred_subtitle_type] if self.preferred_subtitle_type < len(types) else 'isdefault'

            # Set preferred audio stream using multi-format language and name matching
            selected_audio_stream = None
            for stream in audio_streams:
                s_lang = stream.get('language') or ''
                s_name = stream.get('name') or ''
                if is_language_match(s_lang, s_name, preferred_audio_streams):
                    self.setAudioStream(stream['index'])
                    selected_audio_stream = stream
                    control.log(f"Player: Selected audio stream {stream['index']} (lang={s_lang}, name={s_name}) matching '{preferred_audio_streams}'", 'info')
                    break
            else:
                # If no preferred audio stream is found, set to the default audio stream
                for stream in audio_streams:
                    if stream.get('isdefault', False):
                        self.setAudioStream(stream['index'])
                        selected_audio_stream = stream
                        control.log(f"Player: Fallback to default audio stream {stream['index']} (lang={stream.get('language')}, name={stream.get('name')})", 'info')
                        break
                else:
                    # If no default audio stream is found, set to the first available audio stream
                    if audio_streams:
                        self.setAudioStream(audio_streams[0]['index'])
                        selected_audio_stream = audio_streams[0]
                        control.log(f"Player: Fallback to first audio stream {audio_streams[0]['index']} (lang={audio_streams[0].get('language')}, name={audio_streams[0].get('name')})", 'info')

            is_eng_audio = is_language_match(
                selected_audio_stream.get('language') if selected_audio_stream else '',
                selected_audio_stream.get('name') if selected_audio_stream else '',
                'eng'
            )

            # Determine target subtitle mode: 'dialog', 'signs', 'custom', or None
            if control.getBool('general.subtitles.keyword'):
                kw_setting = self.preferred_subtitle_keyword
                if kw_setting == 4:
                    # Option 4: Smart Pair (Dialog for Sub / Signs for Dub)
                    target_mode = 'signs' if is_eng_audio else 'dialog'
                elif kw_setting == 2:
                    # Option 2: Signs & Songs
                    target_mode = 'signs'
                elif kw_setting == 3:
                    # Option 3: Custom Keyword
                    target_mode = 'custom'
                else:
                    # Option 1: Dialog (Forced Full Dialogue everywhere, including English Dub)
                    target_mode = 'dialog'
            else:
                target_mode = None

            custom_keyword = control.getSetting('subtitles.customkeyword') if target_mode == 'custom' else ''
            preferred_type = preferred_subtitle_type if control.getBool('general.subtitles.type') else None

            # Select and apply optimal subtitle stream
            subtitle_int = select_subtitle_stream(
                subtitle_streams=subtitle_streams,
                target_mode=target_mode,
                preferred_lang=preferred_subtitle_lang,
                custom_keyword=custom_keyword,
                preferred_type=preferred_type
            )

            if subtitle_int is not None:
                self.setSubtitleStream(subtitle_int)

            # Enable and Disable Subtitles based on active audio stream
            if preferred_subtitle_lang == "none":
                self.showSubtitles(False)
            elif is_eng_audio:
                # English Dub playing: respect general.dubsubtitles
                if control.getBool('general.dubsubtitles'):
                    self.showSubtitles(True)
                else:
                    self.showSubtitles(False)
            else:
                # Japanese or foreign audio playing: show subtitles
                self.showSubtitles(True)

    # ── Skip Time Processing (AniSkip / AnimeSkip / Embed / FFprobe chapters) ─

    def process_ffprobe_chapter_skips(self):
        """
        Last-resort intro/outro windows from ffprobe chapter titles + timestamps.
        Runs only after embed / AniSkip / AnimeSkip; does not override them.
        """
        if not control.getBool('ffprobe.chapters.enable'):
            return

        # Kodi 22+ Demuxer Chapter Fallback: query Player.GetChapters via JSON-RPC if not pre-probed
        if not self.ffprobe_chapters:
            try:
                res = control.jsonrpc({
                    'jsonrpc': '2.0',
                    'method': 'Player.GetChapters',
                    'params': {'playerid': 1},
                    'id': 1
                })
                if isinstance(res, dict) and 'result' in res:
                    raw_ch = res['result'].get('chapters', [])
                    if raw_ch:
                        parsed = []
                        for ch in raw_ch:
                            ch_title = ch.get('title') or ch.get('name') or ''
                            ch_time = ch.get('time')
                            if isinstance(ch_time, dict):
                                s_time = float(ch_time.get('hours', 0) or 0) * 3600.0 + \
                                         float(ch_time.get('minutes', 0) or 0) * 60.0 + \
                                         float(ch_time.get('seconds', 0) or 0) + \
                                         (float(ch_time.get('milliseconds', 0) or 0) / 1000.0)
                            elif isinstance(ch_time, (int, float)):
                                s_time = float(ch_time)
                            else:
                                s_time = 0.0
                            parsed.append({'title': ch_title, 'start': s_time, 'end': 0.0})
                        parsed.sort(key=lambda x: x['start'])
                        for idx in range(len(parsed)):
                            if idx + 1 < len(parsed):
                                parsed[idx]['end'] = parsed[idx + 1]['start']
                            elif self.total_time:
                                parsed[idx]['end'] = float(self.total_time)
                        self.ffprobe_chapters = parsed
                        control.log(f'Player: Populated {len(self.ffprobe_chapters)} chapter(s) via Kodi Player.GetChapters', 'info')
            except Exception as e:
                control.log(f'Player: Kodi Player.GetChapters lookup failed: {e}', 'debug')

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
                start = max(0.0, float(ch.get('start', 0)) + self.skipintro_offset)
                end = float(ch.get('end', 0)) + self.skipintro_offset
                if end <= start:
                    end = start + 90.0
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
                start = max(0.0, float(outro_ch.get('start', 0)) + self.skipoutro_offset)
                end = float(outro_ch.get('end', 0)) + self.skipoutro_offset
                if end <= start:
                    end = total
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
            if not skipintro_aniskip_res or not skipintro_aniskip_res.get('results'):
                skipintro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'mixed-op')
            if skipintro_aniskip_res and skipintro_aniskip_res.get('results'):
                skip_times = skipintro_aniskip_res['results'][0]['interval']
                self.skipintro_start = max(0, int(skip_times['startTime']) + self.skipintro_offset)
                self.skipintro_end = int(skip_times['endTime']) + self.skipintro_offset
                self.skipintro_aniskip = True

        if self.skipoutro_aniskip_enable and not self.skipoutro_aniskip:
            skipoutro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'ed')
            if not skipoutro_aniskip_res or not skipoutro_aniskip_res.get('results'):
                skipoutro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'mixed-ed')
            if skipoutro_aniskip_res and skipoutro_aniskip_res.get('results'):
                skip_times = skipoutro_aniskip_res['results'][0]['interval']
                self.skipoutro_start = max(0, int(skip_times['startTime']) + self.skipoutro_offset)
                self.skipoutro_end = int(skip_times['endTime']) + self.skipoutro_offset
                self.skipoutro_aniskip = True

    def process_animeskip(self):
        show_meta = database.get_show_meta(self.mal_id)
        anilist_id = None
        if show_meta and show_meta.get('meta_ids'):
            try:
                anilist_id = database.loads(show_meta['meta_ids']).get('anilist_id')
            except Exception:
                anilist_id = None
        if not anilist_id:
            try:
                mappings = database.get_mappings(self.mal_id, 'mal_id')
                anilist_id = mappings.get('anilist_id') if isinstance(mappings, dict) else None
            except Exception:
                anilist_id = None
        if not anilist_id:
            return

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
                self.skipintro_start = max(0, intro_start + self.skipintro_offset)
                self.skipintro_end = intro_end + self.skipintro_offset
                self.skipintro_aniskip = True
            if outro_start is not None and outro_end is not None:
                self.skipoutro_start = max(0, int(outro_start) + self.skipoutro_offset)
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
        super().__init__()
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
