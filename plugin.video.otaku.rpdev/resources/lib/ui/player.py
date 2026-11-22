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
from resources.lib.endpoints import aniskip, anime_skip, introdb
from resources.lib import indexers
from resources.lib.pages import EMBED_SKIP_PREFIXES

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

    # Try Kodi C++ native ISO 639-2 language normalization (PR #497)
    if s_lang:
        try:
            import xbmc
            if hasattr(xbmc, 'convertLanguage') and hasattr(xbmc, 'ISO_639_2'):
                c_target = str(xbmc.convertLanguage(target, xbmc.ISO_639_2) or '').lower().strip()
                c_stream = str(xbmc.convertLanguage(s_lang, xbmc.ISO_639_2) or '').lower().strip()
                if c_target and c_stream and c_target == c_stream:
                    return True
        except Exception:
            pass

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

    # 3b. External Subtitle Preference (C-11): prefer addon-downloaded .vtt/.srt over in-manifest HLS streams on ties
    is_external = bool(sub.get('isexternal', False)) or 'temporarysubs' in sub_name or '(external)' in sub_name
    if is_external:
        score += 25

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
    if scored[0][0] < 0:
        return None
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
        self.animeskip_enable = control.getBool('animeskip.enable', True)
        self.animeskip_apikey = control.getSetting('animeskip.apikey') or 'OyThx3MHD7dKuaNOk9c6N2LeR4fOmiRw'
        self.introdb_enable = control.getBool('introdb.enable', True)
        self.skipintro_animeskip_enable = control.getBool('skipintro.animeskip.enable', True)
        self.skipoutro_animeskip_enable = control.getBool('skipoutro.animeskip.enable', True)
        self.skipintro_introdb_enable = control.getBool('skipintro.introdb.enable', True)
        self.skipoutro_introdb_enable = control.getBool('skipoutro.introdb.enable', True)

        self.skipintro_aniskip = False
        self.skipoutro_aniskip = False
        self.skipintro_from_chapters = False
        self.skipoutro_from_chapters = False
        self.skipintro_start = control.getInt('skipintro.delay')
        self.skipintro_end = self.skipintro_start + control.getInt('skipintro.duration')
        self.skipoutro_start = 0
        self.skipoutro_end = 0
        self.skipintro_offset = control.getInt('skipintro.aniskip.offset')
        self.skipoutro_offset = control.getInt('skipoutro.aniskip.offset')

        self.preferred_audio = control.getInt('general.audio')
        self.preferred_subtitle_setting = control.getInt('general.subtitles')
        self.preferred_subtitle_type = control.getInt('subtitles.types')
        self.preferred_subtitle_keyword = control.getInt('subtitles.keywords')

        self.ffprobe_chapters = []
        self._playback_stopped = False
        self._playback_ended = False
        self._user_stopped_or_errored = False
        self.episodes = []
        self.type = ''
        self.provider = ''
        self.mal_id = ''
        self.episode = 0

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

        # NF-06 / NF-03: Apply per-series override profile if configured
        self.series_override = database.get_series_override(self.mal_id) if self.mal_id else None
        if isinstance(self.series_override, dict):
            ov_audio = (self.series_override.get('audio_lang') or '').lower()
            if ov_audio in ('jpn', 'ja', 'japanese', 'sub'):
                self.preferred_audio = 0
            elif ov_audio in ('eng', 'en', 'english', 'dub'):
                self.preferred_audio = 1
            ov_sub = (self.series_override.get('sub_lang') or '').lower()
            _sub_idx_map = {'none': 0, 'eng': 1, 'en': 1, 'jpn': 2, 'ja': 2, 'spa': 3, 'es': 3, 'fre': 4, 'fr': 4, 'ger': 5, 'de': 5}
            if ov_sub in _sub_idx_map:
                self.preferred_subtitle_setting = _sub_idx_map[ov_sub]
            ov_mode = (self.series_override.get('sub_mode') or '').lower()
            if ov_mode == 'dialog':
                self.preferred_subtitle_keyword = 1
            elif ov_mode == 'signs':
                self.preferred_subtitle_keyword = 2
            elif ov_mode == 'smart':
                self.preferred_subtitle_keyword = 4
            if self.series_override.get('intro_offset_s') is not None:
                self.skipintro_offset = int(self.series_override.get('intro_offset_s') or 0)
            if self.series_override.get('outro_offset_s') is not None:
                self.skipoutro_offset = int(self.series_override.get('outro_offset_s') or 0)

        # Process skip times asynchronously to not block playback
        if not self._skip_processed:
            self._async_process_skip_times()

        # Continue with playback initialization
        self.keepAlive()

    def _async_process_skip_times(self):
        """Process skip times in background to avoid blocking playback"""
        def _process():
            try:
                if self.provider in EMBED_SKIP_PREFIXES:
                    self.process_embed(self.provider)
                self.process_aniskip()
                if self.animeskip_enable:
                    self.process_animeskip()
                if self.introdb_enable:
                    self.process_introdb()
                self._skip_processed = True
            except Exception as e:
                control.log(f'Error processing skip times: {e}', 'error')

        import threading
        threading.Thread(target=_process, daemon=True).start()

    # ── Playback Callbacks ────────────────────────────────────────────────

    @staticmethod
    def _clear_preresolved_properties():
        """Clear Zero-Wait pre-resolved stream window properties."""
        for prop in (
            'otaku.preResolved_url',
            'otaku.preResolved_malId',
            'otaku.preResolved_episode',
            'otaku.preResolved_data',
        ):
            control.playerWindow.clearProperty(prop)

    def _resolve_resume_target_file(self):
        """Return a safe non-HTTP(S) file path for Files.SetFileDetails (prevents EOF CCurlFile::Stat HTTP 22 errors)."""
        target_file = self.path or ''
        if not target_file:
            try:
                target_file = self.getPlayingFile()
            except Exception:
                target_file = ''
        if not target_file:
            return ''
        if str(target_file).lower().startswith(('http://', 'https://')):
            mal_id = getattr(self, 'mal_id', None)
            ep = getattr(self, 'episode', None)
            if mal_id and ep is not None and str(ep) != '':
                return f"plugin://{control.ADDON_ID}/play/{mal_id}/{ep}"
            return ''
        return str(target_file)

    def onPlayBackStopped(self):
        self._playback_stopped = True
        self._user_stopped_or_errored = True
        self._clear_preresolved_properties()
        control.closeAllDialogs()
        playList.clear()
        try:
            from resources.lib.ui import embed_extractor
            embed_extractor.del_subs()
        except Exception:
            pass
        target_file = self._resolve_resume_target_file()

        if target_file and (getattr(self, 'total_time', 0) or 0) > 60:
            watched_pct = self.getWatchedPercent()
            if 10 < watched_pct < 90 and 0 < (getattr(self, 'current_time', 0) or 0) < self.total_time:
                query = {
                    'jsonrpc': '2.0',
                    'method': 'Files.SetFileDetails',
                    'params': {
                        'file': target_file,
                        'media': 'video',
                        'resume': {
                            'position': self.current_time,
                            'total': self.total_time
                        }
                    },
                    'id': 1
                }
                control.jsonrpc(query)
            elif watched_pct >= 90:
                # Clear bookmark when episode is finished so Kodi does not prompt resume on replay
                query = {
                    'jsonrpc': '2.0',
                    'method': 'Files.SetFileDetails',
                    'params': {
                        'file': target_file,
                        'media': 'video',
                        'resume': {
                            'position': 0,
                            'total': self.total_time
                        }
                    },
                    'id': 1
                }
                control.jsonrpc(query)
        try:
            from resources.lib import subtitles
            subtitles.clear_active_playback_meta()
        except Exception:
            pass
        control.clean_memory()

    def onPlayBackEnded(self):
        self._playback_stopped = True
        self._playback_ended = True
        control.closeAllDialogs()
        # Only purge temp subs when no next playlist episode is queued; during Zero-Wait
        # transitions, the incoming episode writes its own temp subs concurrently and
        # purges stale ones before writing.
        has_next_item = playList.size() > 1 and (playList.getposition() < 0 or playList.getposition() < playList.size() - 1)
        if not has_next_item:
            try:
                from resources.lib.ui import embed_extractor
                embed_extractor.del_subs()
            except Exception:
                pass
            try:
                from resources.lib import subtitles
                subtitles.clear_active_playback_meta()
            except Exception:
                pass
        target_file = self._resolve_resume_target_file()
        if target_file and (getattr(self, 'total_time', 0) or 0) > 60:
            query = {
                'jsonrpc': '2.0',
                'method': 'Files.SetFileDetails',
                'params': {
                    'file': target_file,
                    'media': 'video',
                    'resume': {
                        'position': 0,
                        'total': self.total_time
                    }
                },
                'id': 1
            }
            control.jsonrpc(query)
        control.clean_memory()

    def onPlayBackError(self):
        self._playback_stopped = True
        self._user_stopped_or_errored = True
        self._clear_preresolved_properties()
        control.closeAllDialogs()
        playList.clear()
        try:
            from resources.lib.ui import embed_extractor
            embed_extractor.del_subs()
        except Exception:
            pass
        try:
            from resources.lib import subtitles
            subtitles.clear_active_playback_meta()
        except Exception:
            pass
        control.clean_memory()

    # ── Playlist Building ─────────────────────────────────────────────────

    def build_playlist(self):
        def _ep_num(ep):
            try:
                return int(ep.get('number') or 0)
            except (ValueError, TypeError, AttributeError):
                return 0

        sorted_episodes = sorted(self.episodes or [], key=_ep_num)
        if not control.getBool('playlist.unaired'):
            from resources.lib.AnimeSchedule import get_anime_schedule
            airing_anime = get_anime_schedule(self.mal_id)

            if airing_anime and airing_anime.get('current_episode'):
                episode_count = int(airing_anime['current_episode'])
                sorted_episodes = [ep for ep in sorted_episodes if _ep_num(ep) <= episode_count]

        try:
            current_ep = int(self.episode or 0)
        except (ValueError, TypeError):
            current_ep = 0

        upcoming_episodes = [ep for ep in sorted_episodes if _ep_num(ep) > current_ep]

        # NF-03: Binge Auto-Skip Filler Episodes (per-series override or global smartplay.skip_filler)
        ov_skip_filler = ''
        if isinstance(getattr(self, 'series_override', None), dict):
            ov_skip_filler = (self.series_override.get('skip_filler_mode') or '').lower()
        should_skip_filler = (
            True if ov_skip_filler in ('skip', 'true', 'on', 'enabled')
            else (False if ov_skip_filler in ('off', 'false', 'disabled', 'keep') else control.getBool('smartplay.skip_filler', default=False))
        )
        if should_skip_filler and upcoming_episodes:
            non_filler = [
                ep for ep in upcoming_episodes
                if 'filler' not in str(ep.get('filler') or '').lower()
            ]
            if non_filler:
                skipped_cnt = len(upcoming_episodes) - len(non_filler)
                if skipped_cnt > 0:
                    control.log(f"Player: Binge auto-skip excluded {skipped_cnt} filler episode(s) from playlist", 'info')
                upcoming_episodes = non_filler

        video_data = indexers.process_episodes(upcoming_episodes, '') if upcoming_episodes else []
        playlist = control.bulk_dir_list(video_data, True)

        for i, item in enumerate(playlist):
            url, listitem = item[0], item[1]

            # Calculate the actual episode number from the sorted upcoming episode
            actual_episode_number = _ep_num(upcoming_episodes[i]) if i < len(upcoming_episodes) else (current_ep + i + 1)
            payload = f"{self.mal_id}/{actual_episode_number}"

            # Add context menu with correct episode number
            context_menu = [
                ('Playback Options', f'RunPlugin(plugin://{control.ADDON_ID}/playback_options/{payload})'),
                ('Marked as Watched [COLOR blue]WatchList[/COLOR]', f'RunPlugin(plugin://{control.ADDON_ID}/marked_as_watched/{payload})')
            ]
            listitem.addContextMenuItems(context_menu)

            control.playList.add(url=url, listitem=listitem)

        # Tier-2 finale UX: when on the last episode of a finished season, queue Episode 1 of direct sequel
        if not upcoming_episodes and control.getBool('smartplay.continue_sequel', default=True):
            try:
                seq = database.get_sequel_mal_id(self.mal_id)
                seq_mid = seq.get('mal_id') if isinstance(seq, dict) else None
                if seq_mid and str(seq_mid) != str(self.mal_id):
                    seq_title = (seq.get('mal_title') or f"Anime {seq_mid}").strip()
                    pic = str(seq.get('mal_picture') or '').strip()
                    if pic and not pic.startswith(('http://', 'https://')):
                        pic = f"https://cdn.myanimelist.net/images/anime/{pic}"
                    is_movie = str(seq.get('anime_media_type') or '').upper() == 'MOVIE'
                    seq_url_path = f"play_movie/{seq_mid}/" if is_movie else f"play/{seq_mid}/1"
                    seq_item = {
                        'url': seq_url_path,
                        'name': f"Sequel: {seq_title} - Episode 1" if not is_movie else f"Sequel: {seq_title}",
                        'isfolder': False,
                        'isplayable': True,
                        'cm': [],
                        'image': {'icon': pic, 'thumb': pic, 'poster': pic} if pic else {},
                        'info': {
                            'title': seq_title,
                            'tvshowtitle': seq_title,
                            'episode': 1,
                            'mediatype': 'movie' if is_movie else 'episode',
                            'UniqueIDs': {'mal_id': str(seq_mid), 'mal': str(seq_mid)},
                        },
                    }
                    seq_built = control.bulk_dir_list([seq_item], True)
                    for s_url, s_li in seq_built or ():
                        control.playList.add(url=s_url, listitem=s_li)
            except Exception as e:
                control.log(f"Player: build_playlist sequel lookup failed: {e}", 'debug')

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

        if callable(self._watchlist_update):
            any_completed = self._watchlist_update(self.mal_id, self.episode)
            if any_completed:
                if not control.monitor.waitForAbort(3):
                    service.sync_watchlist(True)

    def onWatchedPercent(self):
        while self.isPlaying() and not self.updated:
            try:
                self.current_time = self.getTime()
            except RuntimeError:
                break
            watched_percentage = (self.current_time / self.total_time) * 100 if self.total_time else 0

            if watched_percentage > self.update_percent:
                self._update_watched_progress()
                break
            if control.monitor.waitForAbort(5):
                break

    def keepAlive(self):
        # Monitor the Playback with optimized wait
        self._monitor = Monitor()
        for i in range(40):  # Increased attempts but shorter waits
            if self._monitor.playbackerror:
                del self._monitor
                return control.log('playbackerror', 'warning')
            if self.isPlayingVideo() and self.getTotalTime() != 0:
                break
            if self._monitor.waitForAbort(0.5):  # Check every 0.5 seconds
                break

        # Check if the player is playing a video
        if not self.isPlayingVideo():
            if self._monitor:
                del self._monitor
            control.log('Failed to start video playback', 'warning')
            return

        # Video playback confirmed active; clear any stale stop flag from earlier transitions
        self._playback_stopped = False

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

        # Track consecutive autoplay count for "Still Watching?" binge safeguard
        consecutive_str = control.playerWindow.getProperty('otaku.consecutive_autoplay')
        if not consecutive_str or playList.size() <= 1:
            control.playerWindow.setProperty('otaku.consecutive_autoplay', '1')
        else:
            try:
                cur_count = int(consecutive_str)
            except ValueError:
                cur_count = 0
            control.playerWindow.setProperty('otaku.consecutive_autoplay', str(cur_count + 1))

        if previous_last_watched != current_mal_id:
            control.setSetting('addon.last_watched', current_mal_id)
            control.log(f'Last watched changed from {previous_last_watched} to {current_mal_id}')
            # Defer refresh to avoid blocking playback
            control.setGlobalProp('otaku.menu.needs_refresh', 'true')
        else:
            control.log(f'Last watched show unchanged ({current_mal_id}) - updated episode {self.episode} in watch history')

        # Publish rich active-playback metadata for auto-download & Kodi OSD Subtitle Download service
        try:
            from resources.lib import subtitles as _subs_mod
            _active_video_info = {
                'title': self.vtag.getTitle() if self.vtag else '',
                'tvshowtitle': self.vtag.getTVShowTitle() if self.vtag else '',
                'originaltitle': self.vtag.getOriginalTitle() if self.vtag else '',
                'season': self.vtag.getSeason() if self.vtag else '',
                'episode': self.episode or (self.vtag.getEpisode() if self.vtag else ''),
                'year': self.vtag.getYear() if self.vtag else '',
                'UniqueIDs': unique_ids or {},
            }
            _subs_mod.publish_active_playback_meta(_active_video_info, mal_id=str(self.mal_id or ''))
        except Exception as e:
            control.log(f'Player: Failed publishing active subtitle meta: {e}', 'debug')

        # Continue with audio/subtitle setup which is needed immediately
        if self.type not in ['embed', 'direct']:
            self.setup_audio_and_subtitles()
        elif self.provider in EMBED_SKIP_PREFIXES:
            self.setup_audio_and_subtitles()
        else:
            # Even for embed/direct streams, verify subtitles exist; auto-download if none attached
            self._ensure_subtitles_available()

        # Handle different media types
        if self.episodes and self.media_type == 'episode' and playList.size() == 1:
            self.build_playlist()

        if self.media_type != 'movie':
            # Demuxer Chapter Fallback Chain:
            # 1. Direct query of native Kodi 22 demuxer chapters (Player.GetChapters), decoupled from ffprobe
            if not self.ffprobe_chapters:
                self.query_demuxer_chapters()

            if self.ffprobe_chapters:
                self.process_ffprobe_chapter_skips()

            # 2. Only wait for external skip APIs if intro or outro has not yet been resolved by AniSkip
            if not (self.skipintro_aniskip and self.skipoutro_aniskip) or self.skipintro_from_chapters or self.skipoutro_from_chapters:
                timeout = 30
                while not self._skip_processed and timeout > 0:
                    if self._playback_stopped or not self.isPlaying() or (self._monitor and self._monitor.abortRequested()):
                        break
                    xbmc.sleep(100)
                    timeout -= 1
                if not (self.skipintro_aniskip or self.skipoutro_aniskip):
                    self.process_ffprobe_chapter_skips()

            # Unified playback monitoring loop: handles intro skip, watched %, and outro/playing next concurrently
            self._run_unified_episode_monitor()
        else:
            self.onWatchedPercent()

        # Continue monitoring until playback finishes (responsive 200ms slices)
        while not self._playback_stopped and self.isPlaying():
            try:
                self.current_time = int(self.getTime())
            except RuntimeError:
                break
            for _ in range(25):  # 25 x 200ms = 5000ms max, checks stop/abort every 200ms
                if self._playback_stopped or not self.isPlaying() or (self._monitor and self._monitor.abortRequested()):
                    break
                xbmc.sleep(200)

        # Cleanup
        if self._monitor:
            del self._monitor

        # Clear pre-resolved stream properties only on explicit stop/error or single-item playback.
        # Do NOT require _playback_ended here: Kodi's isPlaying() flips False on natural EOF
        # before the async onPlayBackEnded() callback is dispatched.
        if getattr(self, '_user_stopped_or_errored', False) or playList.size() <= 1:
            self._clear_preresolved_properties()

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

        while not self._playback_stopped and self.isPlaying() and not (intro_handled and self.updated and outro_handled):
            # When player is paused, yield to prevent CPU churn and preserve hardware-plane rendering
            if xbmc.getCondVisibility("Player.Paused"):
                for _ in range(5):
                    if self._playback_stopped or not self.isPlaying() or (self._monitor and self._monitor.abortRequested()):
                        break
                    xbmc.sleep(200)
                continue

            try:
                self.current_time = int(self.getTime())
                if (self.total_time or 0) <= 0:
                    self.total_time = int(self.getTotalTime())
            except RuntimeError:
                break

            intro_start = self.skipintro_start if self.skipintro_aniskip else (control.getInt('skipintro.delay') or 1)
            intro_end = self.skipintro_end if self.skipintro_aniskip else intro_start + control.getInt('skipintro.duration')

            # 1. Intro Skip check
            if not intro_handled:
                if self.current_time > intro_end:
                    intro_handled = True
                elif self.current_time >= intro_start:
                    if self.skipintro_aniskip_auto and self.skipintro_aniskip:
                        self.seekTime(intro_end)
                        control.log(f'Auto-skipped intro: {intro_start}-{intro_end}', 'info')
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
                        control.log(f'Auto-skipped outro: {self.skipoutro_start}-{self.skipoutro_end}', 'info')
                    outro_handled = True
                elif self._should_show_dialog(time_remaining, playnext_time):
                    if not self._check_still_watching():
                        break
                    if control.getBool('smartplay.binge_mode', default=False):
                        try:
                            cur_ep = int(self.episode)
                            next_ep_str = f"Episode {cur_ep + 1}"
                        except (ValueError, TypeError):
                            next_ep_str = "Next Episode"
                        control.notify(control.ADDON_NAME, f"Up Next: {next_ep_str}...", sound=False)
                        if self.skipoutro_aniskip and self.skipoutro_end > 0:
                            self.seekTime(self.skipoutro_end)
                            control.log(f'Auto-skipped outro (binge mode): {self.skipoutro_start}-{self.skipoutro_end}', 'info')
                        outro_handled = True
                    else:
                        if self.skipoutro_aniskip and not self.skipoutro_aniskip_auto:
                            PlayerDialogs().display_dialog(True, self.skipoutro_end)
                        elif not self.skipoutro_aniskip and playnext_time > 0:
                            PlayerDialogs().display_dialog(False, 0)
                        outro_handled = True

            for _ in range(10):  # 10 x 200ms = 2000ms, responsive check every 200ms
                if self._playback_stopped or not self.isPlaying() or (self._monitor and self._monitor.abortRequested()):
                    break
                xbmc.sleep(200)

    def _trigger_background_prescrape(self):
        """Pre-warm scraper cache for the next episode in background at ~70% playback"""
        try:
            if not control.getBool('smartplay.prescrape', default=True):
                return
            if not self.mal_id or getattr(self, 'media_type', None) == 'movie':
                return
            try:
                current_ep = int(self.episode)
            except (ValueError, TypeError):
                return
            next_ep = current_ep + 1

            # Skip pre-scraping when playing a movie or the final episode of a series
            if self.episodes and next_ep > len(self.episodes):
                return
            if not self.episodes and playList.size() <= 1:
                show_row = database.get_show(self.mal_id)
                if show_row and isinstance(show_row, dict):
                    kodi_meta = database.loads(show_row.get('kodi_meta'))
                    if isinstance(kodi_meta, dict):
                        if str(kodi_meta.get('mediatype') or '').lower() == 'movie':
                            return
                        try:
                            total_eps = int(kodi_meta.get('episodes') or 0)
                        except (ValueError, TypeError):
                            total_eps = 0
                        if total_eps > 0 and next_ep > total_eps:
                            return

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
                    if control.is_low_memory():
                        control.log("Player: Throttling background pre-scrape on low-memory device", level='info')
                        if control.monitor.waitForAbort(1):
                            return
                    from resources.lib import MetaBrowser
                    sources = MetaBrowser.get_sources(self.mal_id, next_ep, 'show', rescrape=False, source_select=False, silent=True)
                    if sources:
                        control.log(f"Player: Background pre-scrape complete for ep {next_ep} ({len(sources)} source(s) pre-cached)", level='info')
                        # Zero-Wait Pre-Resolved Stream Handoff
                        if control.getBool('smartplay.preresolve', default=True) and control.getBool('general.smartplay') and control.getInt('general.playstyle.episode') != 1:
                            from resources.lib.windows.resolver import resolve_silent
                            res_data = resolve_silent(sources, next_ep, self.mal_id)
                            if res_data and res_data.get('url'):
                                control.playerWindow.setProperty('otaku.preResolved_url', str(res_data['url']))
                                control.playerWindow.setProperty('otaku.preResolved_malId', str(self.mal_id))
                                control.playerWindow.setProperty('otaku.preResolved_episode', str(next_ep))
                                control.playerWindow.setProperty('otaku.preResolved_data', json.dumps(res_data))
                                control.log(f"Player: Zero-Wait direct stream pre-resolved for {self.mal_id} Ep {next_ep}", level='info')
                            else:
                                control.log(
                                    f"Player: Zero-Wait pre-resolve did not verify a stream for {self.mal_id} Ep {next_ep} ({len(sources)} source(s) remaining in cache)",
                                    level='debug',
                                )
                except Exception as e:
                    control.log(f"Player: Pre-scrape background task error: {e}", level='warning')

            t = threading.Thread(target=prescrape_worker, name="Otaku-PreScrapeThread", daemon=True)
            t.start()
        except Exception as e:
            control.log(f"Player: Failed to launch pre-scrape: {e}", level='warning')

    def _check_still_watching(self):
        """Evaluate if the 'Still Watching?' binge safeguard should be triggered."""
        try:
            stillwatching_count = control.getInt('smartplay.stillwatching_count', default=3)
            if stillwatching_count <= 0:
                return True

            consecutive_str = control.playerWindow.getProperty('otaku.consecutive_autoplay')
            consecutive = int(consecutive_str) if consecutive_str and consecutive_str.isdigit() else 1

            if consecutive >= stillwatching_count:
                control.log(f"Player: Triggering 'Still Watching?' safeguard (consecutive={consecutive}, limit={stillwatching_count})", 'info')
                from resources.lib.windows.still_watching import StillWatchingXML
                title = control.playerWindow.getProperty('item.info.tvshowtitle') or getattr(self, 'title', '')
                dlg = None
                try:
                    dlg = StillWatchingXML('still_watching.xml', control.ADDON_PATH, actionArgs={'title': title})
                    keep_watching = dlg.doModal()
                finally:
                    if dlg:
                        try:
                            dlg.close()
                        except Exception:
                            pass
                        del dlg
                if keep_watching:
                    control.log("Player: User confirmed 'Keep Watching' — resetting consecutive counter", 'info')
                    control.playerWindow.setProperty('otaku.consecutive_autoplay', '0')
                    return True
                else:
                    control.log("Player: Still Watching unanswered or stopped — halting playback", 'info')
                    self._playback_stopped = True
                    control.playList.clear()
                    self.stop()
                    control.playerWindow.clearProperty('otaku.consecutive_autoplay')
                    return False
            return True
        except Exception as e:
            control.log(f"Player: Error during still watching check: {e}", 'warning')
            return True

    def _should_show_dialog(self, time_remaining, playnext_time):
        """Determine if we should show a dialog - simplified"""
        if self.skipoutro_aniskip and not self.skipoutro_aniskip_auto:
            return self.current_time >= self.skipoutro_start and self.skipoutro_start > 0
        elif not self.skipoutro_aniskip and playnext_time > 0:
            return time_remaining <= playnext_time
        return False

    # ── Audio & Subtitle Setup ────────────────────────────────────────

    def _query_player_streams(self, max_attempts=10):
        """Poll Player.GetProperties for audio & subtitle tracks with brief demuxer warmup."""
        query = {
            'jsonrpc': '2.0',
            "method": "Player.GetProperties",
            "params": {
                "playerid": 1,
                "properties": ["subtitles", "audiostreams"]
            },
            "id": 1
        }
        audio_streams = []
        subtitle_streams = []
        for _ in range(max_attempts):
            response = control.jsonrpc(query)
            if isinstance(response, dict) and 'result' in response:
                player_properties = response['result']
                audio_streams = player_properties.get('audiostreams', []) or []
                subtitle_streams = player_properties.get('subtitles', []) or []
                if audio_streams or subtitle_streams:
                    break
            if control.monitor.waitForAbort(0.2):
                break
        return audio_streams, subtitle_streams

    def _trigger_auto_subtitle_download(self, preferred_subtitle_lang='', is_eng_audio=False):
        """Trigger automatic external subtitle download when no matching subtitles are available."""
        if not control.getBool('subtitles.enabled', True) or not control.getBool('subtitles.auto_search', True):
            return False
        if preferred_subtitle_lang and str(preferred_subtitle_lang).lower() == 'none':
            return False
        # Do not auto-download unwanted full dialogue subs over English Dub unless dubsubtitles or prefer_forced is enabled
        if is_eng_audio and not control.getBool('general.dubsubtitles') and not control.getBool('subtitles.prefer_forced'):
            control.log("Player: English audio active with dubsubtitles disabled; skipping external subtitle auto-download", 'debug')
            return False
        try:
            from resources.lib import subtitles
            control.log("Player: No matching subtitle stream available; triggering native subtitles auto-download", 'info')
            return bool(subtitles.auto_download_subtitles())
        except Exception as e:
            control.log(f"Player: Native subtitles trigger error: {e}", 'warning')
            return False

    def _ensure_subtitles_available(self):
        """Verify subtitle presence for embed/direct/kodi-language streams and auto-download if absent."""
        if not control.getBool('subtitles.enabled', True) or not control.getBool('subtitles.auto_search', True):
            return False
        audio_streams, subtitle_streams = self._query_player_streams(max_attempts=5)
        from resources.lib.subtitles import languages as sub_langs
        preferred_lang = sub_langs.get_preferred_subtitle_language()
        if not preferred_lang or preferred_lang == 'none':
            return False

        # Check if any existing stream already matches preferred language
        has_matching_sub = any(
            is_language_match(s.get('language'), s.get('name'), preferred_lang)
            for s in subtitle_streams
        )
        only_signs_embed = (
            control.getGlobalProp('otaku.embed_sub_signs_only') == 'true'
            and control.getGlobalProp('otaku.embed_sub_has_full_dialog') != 'true'
            and not control.getBool('subtitles.prefer_forced')
        )
        if has_matching_sub and not only_signs_embed:
            return True

        # Determine if active audio is English (for dubsubtitles guard)
        is_eng_audio = False
        if audio_streams:
            first_audio = audio_streams[0]
            is_eng_audio = is_language_match(first_audio.get('language'), first_audio.get('name'), 'eng')

        return self._trigger_auto_subtitle_download(preferred_subtitle_lang=preferred_lang, is_eng_audio=is_eng_audio)

    def setup_audio_and_subtitles(self):
        """Handle audio and subtitle setup, plus automatic external subtitle download when none exist."""
        if control.getBool('general.kodi_language'):
            # Kodi manages language selection, but still auto-download subtitles when no matching track exists
            self._ensure_subtitles_available()
            return

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
        audio_streams, subtitle_streams = self._query_player_streams(max_attempts=10)

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
            # Detect if the only available subtitle is a Signs/Forced-only track while Full Dialogue is requested
            selected_sub = next(
                (s for idx, s in enumerate(subtitle_streams) if s.get('index', idx) == subtitle_int),
                {},
            )
            sub_name_l = (selected_sub.get('name') or '').lower()
            is_signs_only_sub = bool(
                selected_sub.get('isforced', False)
                or any(kw in sub_name_l for kw in SIGNS_SUBTITLE_KEYWORDS)
                or (
                    control.getGlobalProp('otaku.embed_sub_signs_only') == 'true'
                    and control.getGlobalProp('otaku.embed_sub_has_full_dialog') != 'true'
                    and (len(subtitle_streams) == 1 or sub_name_l in ('', '(external)', 'english', 'eng'))
                )
            )
            want_full_dialogue = (
                target_mode == 'dialog'
                and preferred_subtitle_lang != "none"
                and not control.getBool('subtitles.prefer_forced')
                and (not is_eng_audio or control.getBool('general.dubsubtitles'))
            )

            auto_upgraded = False
            if is_signs_only_sub and want_full_dialogue:
                control.log(
                    "Player: Only Signs/Forced subtitle track available while Full Dialogue is requested; "
                    "triggering native subtitles auto-download",
                    'info',
                )
                auto_upgraded = self._trigger_auto_subtitle_download(
                    preferred_subtitle_lang=preferred_subtitle_lang,
                    is_eng_audio=is_eng_audio,
                )

            if not auto_upgraded:
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
        elif preferred_subtitle_lang != "none":
            # No matching internal subtitle stream found in video container:
            # Trigger native external subtitle search and auto-download if enabled
            loaded = self._trigger_auto_subtitle_download(
                preferred_subtitle_lang=preferred_subtitle_lang,
                is_eng_audio=is_eng_audio,
            )
            if not loaded:
                if len(subtitle_streams) > 0 and (not is_eng_audio or control.getBool('general.dubsubtitles')):
                    self.setSubtitleStream(0)
                    self.showSubtitles(True)
                else:
                    self.showSubtitles(False)
        elif not subtitle_streams or preferred_subtitle_lang == "none":
            # No valid subtitle stream found for current stream: ensure subtitles are disabled
            # so lingering external or temp subtitles from earlier episodes are not displayed
            self.showSubtitles(False)

    # ── Skip Time Processing (AniSkip / AnimeSkip / Embed / FFprobe chapters) ─

    def query_demuxer_chapters(self):
        """Query native Kodi 22 demuxer chapters via Player.GetChapters JSON-RPC directly."""
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
                    return True
        except Exception as e:
            control.log(f'Player: Kodi Player.GetChapters lookup failed: {e}', 'debug')
        return False

    def process_ffprobe_chapter_skips(self):
        """
        Intro/outro windows from native demuxer chapters or ffprobe container chapters.
        First queries native Kodi 22 Player.GetChapters directly (decoupled from ffprobe setting),
        then processes pre-probed chapters.
        """
        if not self.ffprobe_chapters:
            self.query_demuxer_chapters()

        if not self.ffprobe_chapters or not self.total_time:
            return

        total = float(self.total_time)
        # Allow small clock slop vs container duration
        max_end = total + 5.0

        if self.skipintro_aniskip_enable and not self.skipintro_aniskip:
            intro_cap = max(600.0, total * 0.25)
            intro_candidates = []
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
                    score = getattr(source_utils, 'score_intro_chapter', lambda t, d: 50)(title, duration)
                    intro_candidates.append({
                        'title': title,
                        'start': int(start),
                        'end': int(end),
                        'score': score,
                        'raw_start': float(ch.get('start', 0) or 0)
                    })

            if intro_candidates:
                # Highest confidence score first; break ties by earliest start time
                best = max(intro_candidates, key=lambda c: (c['score'], -c['raw_start']))
                self.skipintro_start = best['start']
                self.skipintro_end = best['end']
                self.skipintro_aniskip = True
                self.skipintro_from_chapters = True
                control.log(
                    'ffprobe chapter intro fallback [%s] %s-%ss (score=%s)'
                    % (best['title'], self.skipintro_start, self.skipintro_end, best['score']),
                    'info',
                )

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
                    self.skipoutro_from_chapters = True
                    control.log(
                        'ffprobe chapter outro fallback [%s] %s-%ss'
                        % (title, self.skipoutro_start, self.skipoutro_end),
                        'info',
                    )

    def process_aniskip(self):
        # AniSkip integration takes precedence over chapter extraction fallback
        if self.skipintro_aniskip_enable and (not self.skipintro_aniskip or self.skipintro_from_chapters):
            skipintro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'op')
            if not skipintro_aniskip_res or not skipintro_aniskip_res.get('results'):
                skipintro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'mixed-op')
            if skipintro_aniskip_res and skipintro_aniskip_res.get('results'):
                skip_times = skipintro_aniskip_res['results'][0]['interval']
                self.skipintro_start = max(0, int(skip_times['startTime']) + self.skipintro_offset)
                self.skipintro_end = int(skip_times['endTime']) + self.skipintro_offset
                self.skipintro_aniskip = True
                self.skipintro_from_chapters = False
                control.log(f'AniSkip: applied intro {self.skipintro_start}-{self.skipintro_end}s (precedence over chapters)', 'info')

        if self.skipoutro_aniskip_enable and (not self.skipoutro_aniskip or self.skipoutro_from_chapters):
            skipoutro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'ed')
            if not skipoutro_aniskip_res or not skipoutro_aniskip_res.get('results'):
                skipoutro_aniskip_res = aniskip.get_skip_times(self.mal_id, self.episode, 'mixed-ed')
            if skipoutro_aniskip_res and skipoutro_aniskip_res.get('results'):
                skip_times = skipoutro_aniskip_res['results'][0]['interval']
                self.skipoutro_start = max(0, int(skip_times['startTime']) + self.skipoutro_offset)
                self.skipoutro_end = int(skip_times['endTime']) + self.skipoutro_offset
                self.skipoutro_aniskip = True
                self.skipoutro_from_chapters = False
                control.log(f'AniSkip: applied outro {self.skipoutro_start}-{self.skipoutro_end}s (precedence over chapters)', 'info')

    def process_animeskip(self):
        # Anime-Skip secondary fallback when AniSkip returns 404 or empty results
        need_intro = (
            self.skipintro_aniskip_enable
            and self.animeskip_enable
            and self.skipintro_animeskip_enable
            and bool(self.animeskip_apikey)
            and (not self.skipintro_aniskip or self.skipintro_from_chapters)
        )
        need_outro = (
            self.skipoutro_aniskip_enable
            and self.animeskip_enable
            and self.skipoutro_animeskip_enable
            and bool(self.animeskip_apikey)
            and (not self.skipoutro_aniskip or self.skipoutro_from_chapters)
        )

        if not need_intro and not need_outro:
            return

        if need_intro:
            intro_res = anime_skip.get_skip_times(self.mal_id, self.episode, 'op', client_id=self.animeskip_apikey)
            if intro_res and intro_res.get('results'):
                skip_times = intro_res['results'][0]['interval']
                self.skipintro_start = max(0, int(skip_times['startTime']) + self.skipintro_offset)
                self.skipintro_end = int(skip_times['endTime']) + self.skipintro_offset
                self.skipintro_aniskip = True
                self.skipintro_from_chapters = False
                control.log(f'Anime-Skip: applied intro {self.skipintro_start}-{self.skipintro_end}s (fallback from AniSkip)', 'info')

        if need_outro:
            outro_res = anime_skip.get_skip_times(self.mal_id, self.episode, 'ed', client_id=self.animeskip_apikey)
            if outro_res and outro_res.get('results'):
                skip_times = outro_res['results'][0]['interval']
                self.skipoutro_start = max(0, int(skip_times['startTime']) + self.skipoutro_offset)
                self.skipoutro_end = int(skip_times['endTime']) + self.skipoutro_offset
                self.skipoutro_aniskip = True
                self.skipoutro_from_chapters = False
                control.log(f'Anime-Skip: applied outro {self.skipoutro_start}-{self.skipoutro_end}s (fallback from AniSkip)', 'info')

    def process_introdb(self):
        # IntroDB tertiary fallback when AniSkip and Anime-Skip return 404 or empty results
        need_intro = (
            self.skipintro_aniskip_enable
            and self.introdb_enable
            and self.skipintro_introdb_enable
            and (not self.skipintro_aniskip or self.skipintro_from_chapters)
        )
        need_outro = (
            self.skipoutro_aniskip_enable
            and self.introdb_enable
            and self.skipoutro_introdb_enable
            and (not self.skipoutro_aniskip or self.skipoutro_from_chapters)
        )

        if not need_intro and not need_outro:
            return

        if need_intro:
            intro_res = introdb.get_skip_times(self.mal_id, self.episode, 'op')
            if intro_res and intro_res.get('results'):
                skip_times = intro_res['results'][0]['interval']
                self.skipintro_start = max(0, int(skip_times['startTime']) + self.skipintro_offset)
                self.skipintro_end = int(skip_times['endTime']) + self.skipintro_offset
                self.skipintro_aniskip = True
                self.skipintro_from_chapters = False
                control.log(f'IntroDB: applied intro {self.skipintro_start}-{self.skipintro_end}s (fallback from AniSkip/Anime-Skip)', 'info')

        if need_outro:
            outro_res = introdb.get_skip_times(self.mal_id, self.episode, 'ed')
            if outro_res and outro_res.get('results'):
                skip_times = outro_res['results'][0]['interval']
                self.skipoutro_start = max(0, int(skip_times['startTime']) + self.skipoutro_offset)
                self.skipoutro_end = int(skip_times['endTime']) + self.skipoutro_offset
                self.skipoutro_aniskip = True
                self.skipoutro_from_chapters = False
                control.log(f'IntroDB: applied outro {self.skipoutro_start}-{self.skipoutro_end}s (fallback from AniSkip/Anime-Skip)', 'info')

        extras = introdb.get_extra_segments(self.mal_id, self.episode)
        if extras.get('recap'):
            self.recap_start = int(extras['recap']['startTime'])
            self.recap_end = int(extras['recap']['endTime'])
        if extras.get('post_credits'):
            self.post_credits_start = int(extras['post_credits']['startTime'])
            self.post_credits_end = int(extras['post_credits']['endTime'])

    def process_embed(self, embed):
        embed_skipintro_start = control.getInt(f'{embed}.skipintro.start')
        embed_skipintro_end = control.getInt(f'{embed}.skipintro.end')
        embed_skipoutro_start = control.getInt(f'{embed}.skipoutro.start')
        embed_skipoutro_end = control.getInt(f'{embed}.skipoutro.end')
        control.setInt(f'{embed}.skipintro.start', -1)
        control.setInt(f'{embed}.skipintro.end', -1)
        control.setInt(f'{embed}.skipoutro.start', -1)
        control.setInt(f'{embed}.skipoutro.end', -1)
        if self.skipintro_aniskip_enable and not self.skipintro_aniskip:
            if embed_skipintro_start != -1:
                self.skipintro_start = embed_skipintro_start + self.skipintro_offset
                self.skipintro_end = embed_skipintro_end + self.skipintro_offset
                self.skipintro_aniskip = True
        if self.skipoutro_aniskip_enable and not self.skipoutro_aniskip:
            if embed_skipoutro_start != -1:
                self.skipoutro_start = embed_skipoutro_start + self.skipoutro_offset
                self.skipoutro_end = embed_skipoutro_end + self.skipoutro_offset
                self.skipoutro_aniskip = True


# ═══════════════════════════════════════════════════════════════════════════
#  PlayerDialogs - Skip Intro / Outro / Playing Next
# ═══════════════════════════════════════════════════════════════════════════

class PlayerDialogs(xbmc.Player):
    def __init__(self):
        super().__init__()
        try:
            self.playing_file = self.getPlayingFile()
        except RuntimeError:
            self.playing_file = ''

    def display_dialog(self, skipoutro_aniskip, skipoutro_end):
        if playList.size() == 0 or playList.getposition() == (playList.size() - 1):
            return
        try:
            current_file = self.getPlayingFile()
        except RuntimeError:
            return
        if self.playing_file != current_file or not self.isPlayingVideo() or not self._is_video_window_open():
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
                dlg = None
                try:
                    dlg = PlayingNext(xml_file, control.ADDON_PATH, actionArgs=args)
                    dlg.doModal()
                finally:
                    if dlg:
                        try:
                            dlg.close()
                        except Exception:
                            pass
                        del dlg
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
                dlg = None
                try:
                    dlg = PlayingNext(xml_file, control.ADDON_PATH, actionArgs=args)
                    dlg.doModal()
                finally:
                    if dlg:
                        try:
                            dlg.close()
                        except Exception:
                            pass
                        del dlg

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
            dlg = None
            try:
                dlg = SkipIntro(xml_file, control.ADDON_PATH, actionArgs=args)
                dlg.doModal()
            finally:
                if dlg:
                    try:
                        dlg.close()
                    except Exception:
                        pass
                    del dlg

    @staticmethod
    def _get_next_item_args():
        current_position = playList.getposition()
        _next_info = playList[current_position + 1]
        next_info = {
            'item_type': "playing_next",
            'thumb': [_next_info.getArt('thumb')],
            'name': _next_info.getLabel()
        }
        try:
            vtag = _next_info.getVideoInfoTag()
            if vtag:
                next_info['tvshowtitle'] = getattr(vtag, 'getTVShowTitle', lambda: '')()
                next_info['season'] = getattr(vtag, 'getSeason', lambda: 0)()
                next_info['episode'] = getattr(vtag, 'getEpisode', lambda: 0)()
                next_info['aired'] = (
                    (vtag.getFirstAiredAsW3C() if hasattr(vtag, 'getFirstAiredAsW3C') else '')
                    or (vtag.getPremieredAsW3C() if hasattr(vtag, 'getPremieredAsW3C') else '')
                    or ('' if hasattr(vtag, 'getFirstAiredAsW3C') else getattr(vtag, 'getFirstAired', lambda: '')())
                    or ('' if hasattr(vtag, 'getPremieredAsW3C') else getattr(vtag, 'getPremiered', lambda: '')())
                )
                next_info['rating'] = getattr(vtag, 'getRating', lambda: 0.0)()
                next_info['plot'] = getattr(vtag, 'getPlot', lambda: '')()
        except Exception:
            pass
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
