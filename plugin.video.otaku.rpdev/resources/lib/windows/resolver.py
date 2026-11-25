import re
import time
import xbmcgui
import xbmcplugin
import xbmc
import urllib.parse

from resources.lib.WatchlistIntegration import watchlist_update_episode
from resources.lib.debrid import all_debrid, debrid_link, easynews, premiumize, real_debrid, torbox, easydebrid
from resources.lib.ui import client, control, database, domains, ffprobe_chapters, source_utils, player
from resources.lib.windows.base_window import BaseWindow

control.sys.path.append(control.dataPath)


def _get_header_ci(headers, name):
    """Case-insensitive HTTP header lookup."""
    if not isinstance(headers, dict):
        return ''
    target = name.lower()
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == target and v:
            return str(v)
    return ''


def _extract_source_origin(source):
    """Extract scheme://netloc/ origin for embed/direct stream candidates, or '' for non-URL hashes."""
    if not isinstance(source, dict):
        return ''
    if source.get('type') not in ('embed', 'direct'):
        return ''
    raw = source.get('hash') or source.get('url') or ''
    if not isinstance(raw, str) or not raw.startswith(('http://', 'https://')):
        return ''
    url_part = raw.split('|', 1)[0]
    parsed = urllib.parse.urlparse(url_part)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}/"
    return ''


def _is_candidate_host_healthy(source):
    """Return False when an embed/direct candidate's origin is currently in mirror failure cooldown."""
    origin = _extract_source_origin(source)
    if origin and not domains.is_mirror_healthy(origin):
        return False
    return True


def _deprioritize_unhealthy_hosts(sources):
    """Stably move embed/direct candidates whose stream host is in failure cooldown to the tail."""
    if not sources or len(sources) <= 1:
        return list(sources) if sources else []
    healthy = []
    unhealthy = []
    for src in sources:
        if not _is_candidate_host_healthy(src):
            unhealthy.append(src)
        else:
            healthy.append(src)
    return healthy + unhealthy


def _mark_candidate_mirror_failure(candidate, resolved_link=None, cooldown=900):
    """Record mirror cooldown for failed embed/direct candidates and their resolved stream host."""
    if not isinstance(candidate, dict) or candidate.get('type') not in ('embed', 'direct'):
        return
    origin = _extract_source_origin(candidate)
    if origin:
        domains.mark_mirror_failure(origin, cooldown=cooldown)
    if isinstance(resolved_link, str) and resolved_link:
        url_part = resolved_link.split('|', 1)[0]
        parsed = urllib.parse.urlparse(url_part)
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            stream_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}/"
            if stream_origin != origin:
                domains.mark_mirror_failure(stream_origin, cooldown=cooldown)


class hook_mimetype:
    __MIME_HOOKS = {}

    @classmethod
    def _normalize(cls, mimetype):
        if not mimetype or not isinstance(mimetype, str):
            return ''
        return mimetype.split(';', 1)[0].strip().lower()

    @classmethod
    def trigger(cls, mimetype, item):
        norm = cls._normalize(mimetype)
        if norm in cls.__MIME_HOOKS:
            return cls.__MIME_HOOKS[norm](item)
        return item

    def __init__(self, mimetype):
        self._type = self._normalize(mimetype)

    def __call__(self, func):
        assert self._type not in self.__MIME_HOOKS
        self.__MIME_HOOKS[self._type] = func
        return func


def _build_resolvers_map():
    return {
        'Alldebrid': all_debrid.AllDebrid,
        'Debrid-Link': debrid_link.DebridLink,
        'Premiumize': premiumize.Premiumize,
        'Real-Debrid': real_debrid.RealDebrid,
        'TorBox': torbox.TorBox,
        'EasyDebrid': easydebrid.EasyDebrid,
        'Easynews': easynews.Easynews,
    }


_DEBRID_SETTING_TO_NAME = {
    'realdebrid': 'Real-Debrid',
    'alldebrid': 'Alldebrid',
    'debridlink': 'Debrid-Link',
    'premiumize': 'Premiumize',
    'torbox': 'TorBox',
    'easydebrid': 'EasyDebrid',
}


def get_enabled_debrid_names(resolvers_map=None):
    """Return ordered list of enabled Debrid provider display keys present in *resolvers_map*."""
    rmap = resolvers_map if resolvers_map is not None else _build_resolvers_map()
    enabled_map = control.enabled_debrid()
    return [
        label for key, label in _DEBRID_SETTING_TO_NAME.items()
        if enabled_map.get(key) and label in rmap
    ]


class Resolver(BaseWindow):
    def __init__(self, xml_file, location, actionArgs=None, source_select=False):
        if actionArgs is None:
            actionArgs = {}
        super().__init__(xml_file, location, actionArgs=actionArgs)
        self.return_data = {
            'link': None,
            'linkinfo': None,
            'source': None
        }
        self.canceled = False
        self.sources = None
        self.args = None
        self.image = {}
        self.resolvers = _build_resolvers_map()
        self.source_select = source_select
        self.pack_select = False
        self.mal_id = actionArgs.get('mal_id') if actionArgs else None
        # self.season = database.get_episode(self.mal_id)['season']
        self.episode = int(actionArgs.get('episode', 1)) if actionArgs else 1
        self.media_type = self.actionArgs.get('media_type', 'tv') if self.actionArgs else 'tv'
        self.play = actionArgs.get('play')
        self.source_select_close = actionArgs.get('close')
        self.resume = actionArgs.get('resume')
        self.context = actionArgs.get('context')
        self.silent = actionArgs.get('silent')
        self.params = actionArgs.get('params', {})
        self.abort = False

        # if self.season:
        #     control.setStr('resolve_season', str(self.season))

        # if self.source_select:
        #     control.setSetting('last_played_source', str(None))

    def get_enabled_debrid_providers(self):
        """Return list of resolver keys that are currently authenticated and enabled."""
        return get_enabled_debrid_names(self.resolvers)

    def onInit(self):
        if isinstance(self.actionArgs, dict) and self.actionArgs.get('ui_review'):
            return
        self.sources = self.reorder_sources(self.sources)
        self.resolve(self.sources)

    def reorder_sources(self, sources):
        if len(sources) > 1 and not self.source_select:
            sources = _deprioritize_unhealthy_hosts(sources)
            lp = control.getSetting('last_played_source') or ''
            # remove any [HASH] blocks (e.g. [E5A85899])
            lp = re.sub(r'\[[0-9A-Fa-f]{8,}\]', '', lp).strip()

            ep = str(self.episode)
            L = len(ep)

            # SmartPlay embed / provider continuity
            last_played_profile = database.get_last_played_source(self.mal_id) if hasattr(self, 'mal_id') and self.mal_id else None
            prefer_same_embed = control.getBool('smartplay.prefer_same_embed', default=True)

            # 1) Precompute all offsets where exactly L digits occur in a row
            digit_positions = [
                i for i in range(len(lp) - L + 1)
                if lp[i:i + L].isdigit()
            ]

            for idx, source in enumerate(sources):
                if not _is_candidate_host_healthy(source):
                    continue
                # embed/direct-style
                stype = source.get('type')
                if stype in ['embed', 'direct']:
                    key = source.get('provider', '') + " " + " ".join(map(str, source.get('info') or []))
                    if key == lp:
                        sources[0], sources[idx] = sources[idx], sources[0]
                        return sources
                    if prefer_same_embed and last_played_profile:
                        if source.get('provider') == last_played_profile.get('provider'):
                            if not last_played_profile.get('lang') or source.get('lang') == last_played_profile.get('lang'):
                                sources[0], sources[idx] = sources[idx], sources[0]
                                return sources

                # torrent-style
                elif stype in ['torrent', 'torrent (uncached)', 'cloud', 'hoster', 'local']:
                    rel = str(source['release_title'])
                    # strip hashes from the release title too
                    rel = re.sub(r'\[[0-9A-Fa-f]{8,}\]', '', rel).strip()

                    # 2) exact match fallback
                    if rel == lp:
                        sources[0], sources[idx] = sources[idx], sources[0]
                        return sources

                    # 3) try each digit-run position
                    for pos in digit_positions:
                        if rel.startswith(lp[:pos]) and rel.endswith(lp[pos + L:]):
                            sources[0], sources[idx] = sources[idx], sources[0]
                            return sources

        return sources

    def resolve(self, sources):
        """Optimized resolve with reduced property updates"""
        if not isinstance(self.return_data, dict):
            self.return_data = {}
        else:
            self.return_data.pop('linkinfo', None)
            self.return_data.pop('link', None)
            self.return_data.pop('sub', None)

        for idx, i in enumerate(sources):
            self.return_data['source'] = i
            if self.canceled:
                break

            # Batch property updates
            self._update_source_properties(i)
            stream_link = None

            if 'uncached' in i['type']:
                stream_link = self.resolve_uncache(i)

            elif i['type'] in ['torrent', 'cloud', 'hoster']:
                if i['type'] == 'cloud' and i['debrid_provider'] == 'Alldebrid':
                    stream_link = i['hash']
                else:
                    stream_link = self.resolve_source(self.resolvers[i['debrid_provider']], i)

            elif i['type'] == 'direct':
                stream_link = i['hash']

            elif i['type'] == 'embed':
                from resources.lib.ui import embed_extractor
                stream_link = embed_extractor.load_video_from_url(i['hash'])

            elif i['type'] == 'local':
                stream_link = i['hash']
                self.return_data['linkinfo'] = {
                    'source': i,
                    'url': stream_link,
                    'local': True,
                    'headers': {}
                }
                self.return_data['link'] = stream_link
                self.return_data['candidate_index'] = idx
                break

            if stream_link:
                self.return_data['link'] = stream_link
                try:
                    verified_linkinfo = self.prefetch_play_link(stream_link)
                except Exception as e:
                    control.log(f"Resolver: prefetch error for {i.get('provider')}: {e}", level='warning')
                    verified_linkinfo = None

                if verified_linkinfo:
                    self.return_data['linkinfo'] = verified_linkinfo
                    self.return_data['source'] = i
                    self.return_data['candidate_index'] = idx
                    if i.get('subs'):
                        self.return_data['sub'] = i['subs']
                    break
                else:
                    self.return_data['link'] = None

            # Multi-Debrid failover for torrents: if primary provider failed, try remaining active providers
            if not self.return_data.get('linkinfo') and i.get('type') == 'torrent' and not self.canceled:
                primary_provider = i.get('debrid_provider')
                enabled_providers = self.get_enabled_debrid_providers()
                for fallback_provider in enabled_providers:
                    if fallback_provider == primary_provider or self.canceled:
                        continue
                    resolver_cls = self.resolvers.get(fallback_provider)
                    if not resolver_cls:
                        continue
                    control.log(f"Resolver: Attempting Debrid failover for hash {i.get('hash')} via {fallback_provider}", level='info')
                    fallback_source = dict(i)
                    fallback_source['debrid_provider'] = fallback_provider
                    try:
                        stream_link = self.resolve_source(resolver_cls, fallback_source)
                        if stream_link:
                            verified_linkinfo = self.prefetch_play_link(stream_link)
                            if verified_linkinfo:
                                self.return_data['linkinfo'] = verified_linkinfo
                                self.return_data['source'] = fallback_source
                                self.return_data['link'] = stream_link
                                self.return_data['candidate_index'] = idx
                                if fallback_source.get('subs'):
                                    self.return_data['sub'] = fallback_source['subs']
                                control.log(f"Resolver: Debrid failover succeeded with {fallback_provider}", level='info')
                                break
                    except Exception as e:
                        control.log(f"Resolver: Failover attempt with {fallback_provider} failed: {e}", level='warning')

                if self.return_data.get('linkinfo'):
                    break

            if not self.return_data.get('linkinfo'):
                _mark_candidate_mirror_failure(i, stream_link, cooldown=900)
                control.log(f"Resolver: candidate {i.get('provider')} failed prefetch/verification, advancing to next candidate", level='warning')
                self.return_data['link'] = None

        if not self.return_data.get('linkinfo'):
            # If this was a cached season pack that failed unrestrict, clear cache and rescrape
            if len(sources) == 1 and sources[0].get('_cached_season_pack'):
                control.log("Resolver: Cached season pack unrestrict failed, clearing and rescraping", level='info')
                episode_data = database.get_episode(self.mal_id)
                season = episode_data.get('season') if episode_data else None
                database.clear_season_pack(self.mal_id, season)
                from resources.lib import MetaBrowser
                fresh_sources = MetaBrowser.get_sources(self.mal_id, self.episode, self.media_type, rescrape=True, silent=True)
                if fresh_sources:
                    self.sources = fresh_sources
                    return self.resolve(fresh_sources)

        if self.return_data.get('linkinfo'):
            ffprobe_chapters.attach_to_linkinfo(self.return_data['linkinfo'])
        else:
            self.return_data = False

        if self.play and isinstance(self.return_data, dict):
            self._handle_playback()
        else:
            self.close()

    def _update_source_properties(self, source):
        """Batch update source properties to reduce overhead"""
        debrid_provider = source.get('debrid_provider', 'None').replace('_', ' ')
        self.setProperty('debrid_provider', debrid_provider)
        self.setProperty('source_provider', source['provider'])
        self.setProperty('release_title', str(source['release_title']))
        self.setProperty('source_resolution', source_utils.res[source['quality']])
        self.setProperty('source_info', " ".join(source['info']))
        self.setProperty('source_type', source['type'])
        self.setProperty('source_size', source.get('size', ''))
        self.setProperty('source_seeders', str(source.get('seeders', '')))

    def _handle_playback(self):
        """Separate playback handling to reduce resolve() complexity"""
        if self.source_select_close:
            self.source_select_close()

        linkInfo = self.return_data['linkinfo']

        item = xbmcgui.ListItem(path=linkInfo['url'], offscreen=True)

        # Always purge stale temporary subtitle files and embed sub flags before preparing new playback
        from resources.lib.ui import embed_extractor
        embed_extractor.del_subs()
        control.clearGlobalProp('otaku.embed_sub_signs_only')
        control.clearGlobalProp('otaku.embed_sub_has_full_dialog')

        # Handle subtitles
        if self.return_data.get('sub'):
            from resources.lib.subtitles import languages
            pref_lang = languages.get_preferred_subtitle_language()
            subtitle_entries = []
            if pref_lang != 'none':
                for idx, sub in enumerate(self.return_data['sub']):
                    sub_lang = sub.get('lang') or embed_extractor.detect_sub_lang(sub.get('url'), sub.get('name'))
                    if pref_lang and not languages.is_language_match(sub_lang, pref_lang):
                        control.log(f"Resolver: Skipping embed subtitle '{sub.get('name', '')}' ({sub_lang}) - does not match preferred '{pref_lang}'", 'debug')
                        continue
                    entry = embed_extractor.get_sub(
                        sub.get('url'),
                        sub.get('lang'),
                        headers=sub.get('headers'),
                        sub_index=sub.get('index', idx),
                        display_name=sub.get('name'),
                        source_url=sub.get('file'),
                        sub_tag=f"{getattr(self, 'mal_id', None) or '0'}_{getattr(self, 'episode', None) or '0'}_{int(time.time() * 1000)}",
                    )
                    if entry:
                        if entry.get('is_signs_only') and control.getInt('subtitles.keywords') == 1 and not control.getBool('subtitles.prefer_forced'):
                            control.log(f"Resolver: Skipping sparse Signs-only sidecar '{entry.get('path')}' in Full Dialogue mode", 'info')
                        else:
                            subtitle_entries.append(entry)
            if subtitle_entries:
                item.setSubtitles([entry['path'] for entry in subtitle_entries])

        # Handle mimetype - hooks will configure InputStream Adaptive for HLS/DASH
        hdr = linkInfo.get('headers') or {}
        content_type = _get_header_ci(hdr, 'Content-Type')
        if content_type:
            item.setProperty('MimeType', content_type.split(';', 1)[0].strip())
            item = hook_mimetype.trigger(content_type, item)

        if self.params.get('image'):
            self.image = self.params.get('image') or {}
            if not isinstance(self.image, dict):
                self.image = {}

        # Extract HDR / Dolby Vision metadata from resolved source if available
        selected_source = self.return_data.get('source', {}) if isinstance(self.return_data, dict) else {}
        source_tags = selected_source.get('info', []) if isinstance(selected_source, dict) else []
        is_dub_source = bool(
            isinstance(selected_source, dict)
            and (
                selected_source.get('lang') == 3
                or str(selected_source.get('lang') or '').lower() in ('dub', 'eng')
                or any('DUB' in str(t).upper().split() for t in (source_tags or []))
            )
        )
        control.playerWindow.setProperty('otaku.active_source_is_dub', 'true' if is_dub_source else 'false')
        hdr_type = None
        if 'DV' in source_tags:
            hdr_type = 'dolbyvision'
        elif 'HDR' in source_tags:
            hdr_type = 'hdr10'

        video_info = dict(self.params.get('info', {})) if self.params.get('info') else dict(self.params)
        if hdr_type and 'hdr_type' not in video_info:
            video_info['hdr_type'] = hdr_type
        if getattr(self, 'mal_id', None):
            uids = dict(video_info.get('UniqueIDs') or {}) if isinstance(video_info.get('UniqueIDs'), dict) else {}
            if 'tvdb' not in uids and 'tmdb' not in uids:
                uids.update(database.get_unique_ids(self.mal_id, 'mal_id') or {})
            uids.setdefault('mal_id', str(self.mal_id))
            uids.setdefault('mal', str(self.mal_id))
            video_info['UniqueIDs'] = {
                str(k): str(v) for k, v in uids.items()
                if v is not None and str(v).strip() not in ('', 'None', 'null')
            }
            if video_info.get('season') in (None, '') and getattr(self, 'media_type', 'episode') != 'movie':
                mapped_s, mapped_ep = player.resolve_trakt_season_episode(self.mal_id, self.episode or 1, is_movie=False)
                if mapped_s is not None:
                    video_info['season'] = mapped_s
                    if video_info.get('episode') in (None, '', 0):
                        video_info['episode'] = mapped_ep

        # Set video tags from the best available source
        control.set_videotags(item, video_info)
        if control.getBool('trakt.enabled') and getattr(self, 'mal_id', None):
            player.publish_trakt_ids(self.mal_id, fetch_remote=False)
        else:
            player.clear_trakt_ids()

        # Signal standardized filename to Kodi Player and subtitle search addons (e.g. a4kSubtitles / OpenSubtitles)
        clean_filename = source_utils.format_video_filename(video_info)
        if clean_filename:
            item.setProperty('original_filename', clean_filename)
            item.setProperty('VideoPlayer.OriginalFilename', clean_filename)
            item.setLabel(clean_filename)

        art = self._build_art_dict(use_params=False)
        if isinstance(art, dict):
            clean_art = control.clean_art_dict(art)
            if clean_art:
                item.setArt(clean_art)
            studio_art = clean_art.get('studio') or clean_art.get('tvshow.studio')
            if studio_art:
                item.setProperty('StudioIcon', studio_art)
                item.setProperty('StudioLogo', studio_art)
                item.setProperty('Studio.Icon', studio_art)
                item.setProperty('Studio.Logo', studio_art)
                item.setProperty('Studio.1.Icon', studio_art)
                item.setProperty('Studio.1.Logo', studio_art)
                item.setProperty('Studio.1.Art', studio_art)

        # Get the clean URL from item (hooks may have stripped headers)
        stream_url = item.getPath()

        # Detect widget/TMDB player context — Container.PluginName won't match
        # our addon when playback is launched from a widget or external player.
        is_widget = xbmc.getInfoLabel('Container.PluginName') != control.ADDON_ID

        # Check whether we're resolving an auto-next episode inside an existing
        # playlist (build_playlist added items after the first episode started).
        in_playlist = control.playList.size() > 1

        if self.context or (is_widget and not in_playlist):
            # control.print("Playlist-based playback for widget or context menu")
            # Playlist-based playback for:
            #   1. Context menu (RunPlugin) — no valid plugin HANDLE
            #   2. Widget / TMDB first-play — ensures metadata displays in
            #      player OSD (not needed for auto-next; playlist is already
            #      populated by build_playlist at that point).
            control.playList.clear()
            control.playList.add(stream_url, item)
            pl_to_play = control.playList._get_pl() if hasattr(control.playList, '_get_pl') else control.playList
            xbmc.Player().play(pl_to_play, item)
        else:
            # control.print("Standard resolved URL playback for in-addon and playlist auto-next")
            # Standard resolved URL playback for in-addon and playlist
            # auto-next.  setResolvedUrl satisfies Kodi's plugin HANDLE,
            # preventing "Playback Failed" errors that pile up during
            # playlist episode transitions.
            xbmcplugin.setResolvedUrl(control.HANDLE, True, item)

        # Monitor playback start
        monitor = Monitor()
        for _ in range(30):
            if monitor.waitForAbort(1) or monitor.playbackerror or monitor.abortRequested():
                xbmcplugin.setResolvedUrl(control.HANDLE, False, item)
                control.playList.clear()
                self.abort = True
                break
            if monitor.playing:
                break
        else:
            control.log('no xbmc playing source found; aborting candidate for failover', level='warning')
            self.abort = True
        del monitor

        self.close()

        if self.abort:
            failed_source = self.return_data.get('source', {}) if isinstance(self.return_data, dict) else {}
            mal_id = getattr(self, 'mal_id', None)
            episode = getattr(self, 'episode', None)
            failed_provider = failed_source.get('provider', 'unknown') if isinstance(failed_source, dict) else 'unknown'
            failed_parsed = urllib.parse.urlparse(stream_url) if isinstance(stream_url, str) and stream_url else None
            failed_host = failed_parsed.netloc if failed_parsed and failed_parsed.netloc else 'unknown'
            control.log(
                f"Resolver: Playback startup failed for provider={failed_provider} host={failed_host} (mal_id={mal_id}, ep={episode})",
                level='warning',
            )
            if (
                isinstance(failed_source, dict)
                and failed_source.get('type') in ('embed', 'direct')
                and failed_parsed
                and failed_parsed.scheme in ('http', 'https')
                and failed_parsed.netloc
            ):
                domains.mark_mirror_failure(f"{failed_parsed.scheme}://{failed_parsed.netloc}/", cooldown=300)
            if mal_id is not None and episode is not None:
                database.clear_episode_sources(mal_id, episode)
            # If the failed source was a cached season pack, clear pack and rescrape
            if failed_source.get('_cached_season_pack'):
                control.log("Resolver: Playback startup failed for cached season pack, rescraping", level='warning')
                episode_data = database.get_episode(mal_id)
                season = episode_data.get('season') if episode_data else None
                database.clear_season_pack(mal_id, season)
                from resources.lib import MetaBrowser
                fresh_sources = MetaBrowser.get_sources(mal_id, episode, self.media_type, rescrape=True, silent=True)
                if fresh_sources:
                    self.abort = False
                    self.sources = fresh_sources
                    self.resolve(fresh_sources)
                    return

            cand_idx = self.return_data.get('candidate_index', 0) if isinstance(self.return_data, dict) else 0
            remaining = self.sources[cand_idx + 1:] if self.sources and cand_idx + 1 < len(self.sources) else []
            if remaining:
                remaining = _deprioritize_unhealthy_hosts(remaining)
                control.log(f"Resolver: Playback startup failed, advancing to next candidate ({len(remaining)} left)", level='info')
                self.abort = False
                self.sources = remaining
                self.resolve(remaining)
                return

        if not self.abort:
            try:
                # If the playing source is a season pack, save it for future fast-path reuse
                resolved_source = self.return_data.get('source') if isinstance(self.return_data, dict) else None
                if resolved_source and source_utils.is_season_pack(resolved_source):
                    episode_data = database.get_episode(self.mal_id)
                    season = episode_data.get('season') if episode_data else None
                    database.set_season_pack(self.mal_id, season, resolved_source)

                if resolved_source:
                    database.save_last_played_source(self.mal_id, resolved_source)
                    if resolved_source.get('type') in ['embed', 'direct']:
                        lp_key = f"{resolved_source.get('provider', '')} {' '.join(map(str, resolved_source.get('info') or []))}".strip()
                    else:
                        lp_key = str(resolved_source.get('release_title') or resolved_source.get('name') or '')
                    control.setSetting('last_played_source', lp_key)
                    control.setSetting('last_watched_series', str(self.mal_id))

                link_info = self.return_data.get('linkinfo') or {}
                ch = link_info.get('chapters') if isinstance(link_info, dict) else None
                active_url = str(link_info.get('url') or stream_url or '')
                active_parsed = urllib.parse.urlparse(active_url.split('|', 1)[0]) if active_url else None
                database.save_playback_failover_context(
                    self.mal_id,
                    self.episode or 1,
                    {
                        'sources': list(self.sources or []),
                        'candidate_index': int(self.return_data.get('candidate_index') or 0),
                        'active_url': active_url,
                        'active_host': active_parsed.netloc.lower() if active_parsed and active_parsed.netloc else '',
                        'debrid_provider': (resolved_source or {}).get('debrid_provider', '') if isinstance(resolved_source, dict) else '',
                        'media_type': getattr(self, 'media_type', 'episode') or 'episode',
                    },
                )
                player.WatchlistPlayer().handle_player(
                    self.mal_id,
                    watchlist_update_episode,
                    self.episode,
                    self.resume,
                    self.params.get('path', ''),
                    self.return_data['source']['type'] if 'type' in self.return_data['source'] else '',
                    self.return_data['source']['provider'] if 'provider' in self.return_data['source'] else '',
                    self.context,
                    ch,
                )
            finally:
                self.close()

    def _build_art_dict(self, use_params=False):
        """Build art dictionary efficiently and defensively for Kodi C++ SWIG contracts."""
        def _get_str(container, key):
            if not isinstance(container, dict):
                return ''
            val = container.get(key)
            if isinstance(val, (list, tuple)) and val:
                val = val[0]
            if isinstance(val, str):
                return val.strip()
            return ''

        params = self.params if isinstance(self.params, dict) else {}
        image = self.image if isinstance(self.image, dict) else {}

        if use_params:
            return {
                'icon': _get_str(params, 'icon') or _get_str(image, 'icon'),
                'thumb': _get_str(params, 'thumb') or _get_str(image, 'thumb'),
                'fanart': _get_str(params, 'fanart') or _get_str(image, 'fanart'),
                'landscape': _get_str(params, 'landscape') or _get_str(image, 'landscape'),
                'banner': _get_str(params, 'banner') or _get_str(image, 'banner'),
                'clearart': _get_str(params, 'clearart') or _get_str(image, 'clearart'),
                'clearlogo': _get_str(params, 'clearlogo') or _get_str(image, 'clearlogo'),
                'tvshow.poster': _get_str(params, 'tvshow.poster') or _get_str(params, 'poster') or _get_str(image, 'poster'),
                'studio': _get_str(params, 'studio') or _get_str(image, 'studio'),
                'tvshow.studio': _get_str(params, 'tvshow.studio') or _get_str(image, 'tvshow.studio'),
            }
        else:
            return {
                'icon': _get_str(image, 'icon'),
                'thumb': _get_str(image, 'thumb'),
                'fanart': _get_str(image, 'fanart'),
                'landscape': _get_str(image, 'landscape'),
                'banner': _get_str(image, 'banner'),
                'clearart': _get_str(image, 'clearart'),
                'clearlogo': _get_str(image, 'clearlogo'),
                'tvshow.poster': _get_str(image, 'poster') or _get_str(params, 'poster'),
                'studio': _get_str(image, 'studio') or _get_str(params, 'studio'),
                'tvshow.studio': _get_str(image, 'tvshow.studio') or _get_str(params, 'tvshow.studio'),
            }

    def resolve_source(self, api, source):
        """Improved resolve_source with better error handling for Premiumize"""
        try:
            api = api()
            hash_ = source['hash']
            magnet = f"magnet:?xt=urn:btih:{hash_}"
            stream_link = None

            if source['type'] == 'torrent':
                filename = source.get('filename')
                if filename:
                    ep_reg = source_utils.get_cache_check_reg(self.episode)
                    clean_fname = re.sub(r'\[.*?\]', '', filename.split('/')[-1])
                    if not ep_reg.search(clean_fname):
                        filename = None
                ep_re = source.get('episode_re') or str(self.episode)
                stream_link = api.resolve_single_magnet(hash_, magnet, ep_re, self.pack_select, filename)
            elif source['type'] == 'cloud':
                hash_ = api.resolve_cloud(source, self.pack_select)
                if hash_:
                    stream_link = api.resolve_hoster(hash_)
            elif source['type'] == 'hoster':
                if source.get('debrid_provider') == 'Easynews':
                    stream_link = api.unrestrict_link(source['hash'])
                else:
                    hoster_response = api.resolve_hoster(magnet, source['episode_re'], self.pack_select)
                    if hoster_response:
                        stream_link = hoster_response

            return stream_link
        except Exception as e:
            control.log(f"Error resolving source with {source.get('debrid_provider', 'Unknown')}: {str(e)}", 'error')
            return None

    @staticmethod
    def prefetch_play_link(link):
        if not link:
            return
        url = link
        headers = {}
        if '|' in url:
            url, hdrs = url.split('|', 1)
            headers = dict([item.split('=', 1) for item in hdrs.split('&') if '=' in item])
            for header in headers:
                headers[header] = urllib.parse.unquote_plus(headers[header])

        def _probe_stream(req_headers):
            resp = None
            try:
                resp = client.head(url, headers=req_headers, timeout=8.0)
            except Exception as e:
                control.log(f"Resolver: HEAD request failed for {url}: {e}", level='warning')

            if not resp or str(resp.status_code) not in ('200', '201', '206'):
                try:
                    get_headers = req_headers.copy()
                    get_headers['Range'] = 'bytes=0-0'
                    resp = client.get(url, headers=get_headers, timeout=8.0)
                except Exception as e:
                    control.log(f"Resolver: GET fallback failed for {url}: {e}", level='warning')
            return resp

        response = _probe_stream(headers)

        # Only invoke FlareSolverr if enabled AND initial stream probe hit an anti-bot challenge
        if (
            (not response or str(response.status_code) in ('403', '429', '503'))
            and control.getBool('fs_enable')
        ):
            srv = (response.headers.get('Server', '') if response and response.headers else '').lower()
            cf_mit = (response.headers.get('Cf-Mitigated', '') if response and response.headers else '').lower()
            if 'cloudflare' in srv or 'ddos-guard' in srv or 'challenge' in cf_mit:
                from resources.lib.ui.client import cfcookie, ddgcookie
                parsed_u = urllib.parse.urlparse(url)
                origin = f"{parsed_u.scheme}://{parsed_u.netloc}/"
                solver = ddgcookie() if 'ddos-guard' in srv else cfcookie()
                cookie, ua = solver.get(origin, control.getInt('fs_timeout'))
                if cookie:
                    headers["Cookie"] = cookie
                    if ua:
                        headers["User-Agent"] = ua
                    response = _probe_stream(headers)

        if not response or str(response.status_code) not in ['200', '201', '206']:
            control.log(f"Resolver: could not verify {url}, status={response.status_code if response else 'failed'}", level='warning')
            return None
        resp_headers = dict(response.headers)
        existing_ct = _get_header_ci(resp_headers, 'Content-Type')
        existing_cl = _get_header_ci(resp_headers, 'Content-Length')
        if not existing_ct:
            if not existing_cl:
                resp_headers.update({'Content-Type': 'video/MP2T'})
            elif '.m3u8' in url:
                resp_headers.update({'Content-Type': 'application/vnd.apple.mpegurl'})
        elif existing_ct.split(';', 1)[0].strip().lower() == 'application/octet-stream' and '.m3u8' in url:
            resp_headers.update({'Content-Type': 'video/MP2T'})
        elif 'Content-Type' not in resp_headers:
            resp_headers['Content-Type'] = existing_ct
        return {
            "url": link if '|' in link else response.url,
            "headers": resp_headers,
        }

    def resolve_uncache(self, source):
        heading = f'{control.ADDON_NAME}: Cache Resolver'
        status = None
        api = self.resolvers[source['debrid_provider']]()
        f_string = (f"[I]{source['release_title']}[/I][CR]"
                    f"[CR]"
                    f"This source is not cached. Would you like to cache it now?")

        if source['debrid_provider'] in ['Alldebrid', 'Real-Debrid', 'Debrid-Link']:
            # Get an instance of the debrid API and check torrent status early.
            torrent_status = api.get_torrent_status(source['magnet'])
            # torrent_status returns (torrent_id, status, torrent_info)
            if torrent_status is None or torrent_status[0] is None:
                # Torrent selection failed.
                return

            torrent_id, status, torrent_info = torrent_status
            if source['debrid_provider'] == 'Alldebrid':
                api.delete_magnet(torrent_id)
            elif source['debrid_provider'] == 'Real-Debrid':
                api.deleteTorrent(torrent_id)

        # If the file is already cached, bypass any prompting.
        if status in ['downloaded', 'Ready']:
            runbackground = False
            runinforground = False
        else:
            # Not yet cached: prompt the user.
            yesnocustom = control.yesnocustom_dialog(
                heading, f_string, "Cancel", "Run in Background", "Run in Foreground",
                defaultbutton=xbmcgui.DLG_YESNO_YES_BTN
            )
            if yesnocustom == -1 or yesnocustom == 2:
                self.canceled = True
                return
            runbackground = (yesnocustom == 0)
            runinforground = (yesnocustom == 1)

        try:
            resolved_cache = api.resolve_uncached_source(source, runbackground, runinforground, self.pack_select)
        except Exception as e:
            control.progressDialog.close()
            import traceback
            control.ok_dialog(control.ADDON_NAME, f'Error: {e}')
            control.log(traceback.format_exc(), level='error')
            return

        if not resolved_cache:
            self.canceled = True

        return resolved_cache

    def doModal(self, sources=None, args=None, pack_select=False):
        if isinstance(self.actionArgs, dict) and self.actionArgs.get('ui_review'):
            try:
                super().doModal()
            finally:
                self.close()
            return self.return_data

        if sources:
            # Reorder sources first.
            self.sources = self.reorder_sources(sources)
            self.args = args
            # Now assign pack_select after the sources are reordered.
            self.pack_select = pack_select
            self.setProperty('release_title', str(self.sources[0]['release_title']))
            self.setProperty('debrid_provider', self.sources[0].get('debrid_provider', 'None').replace('_', ' '))
            self.setProperty('source_provider', self.sources[0]['provider'])
            self.setProperty('source_resolution', source_utils.res[self.sources[0]['quality']])
            self.setProperty('source_info', " ".join(self.sources[0]['info']))
            self.setProperty('source_type', self.sources[0]['type'])
            self.setProperty('source_size', self.sources[0]['size'])
            self.setProperty('source_seeders', str(self.sources[0].get('seeders', '')))

            if self.sources[0]['type'] in ['embed', 'direct']:
                control.setSetting('last_played_source', str(self.sources[0]['provider']) + " " + " ".join(map(str, self.sources[0]['info'])))
            else:
                control.setSetting('last_played_source', str(self.sources[0]['release_title']))

            try:
                if self.silent:
                    if self.source_select_close:
                        self.source_select_close()
                    self.resolve(self.sources)
                else:
                    super().doModal()
            finally:
                self.close()

        return self.return_data

    def close(self):
        # Only drop the parent-window callback here. self.sources must survive close():
        # resolve() calls close() before its failover logic advances to the next candidate.
        self.source_select_close = None
        super().close()

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [9, 10, 92, 216]:
            # BACK / BACKSPACE / ESCAPE (including Android TV remote back action 9)
            self.canceled = True
            self.close()


class Monitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.playbackerror = False
        self.playing = False
        self._created = time.time()
        try:
            self._was_playing_at_start = bool(xbmc.Player().isPlaying())
        except Exception:
            self._was_playing_at_start = False
        self._saw_onplay = False

    def onNotification(self, sender, method, data):
        if method == 'Player.OnPlay':
            self._saw_onplay = True
        elif method == 'Player.OnAVStart':
            self.playing = True
            self.playbackerror = False
        elif method == 'Player.OnStop':
            # Only ignore rapid OnStop events arriving within 2s when the player was
            # already playing a previous item and hasn't emitted Player.OnPlay for the new item yet.
            if (time.time() - self._created < 2) and self._was_playing_at_start and not self._saw_onplay:
                return
            if not self.playing:
                self.playbackerror = True
        # else:
        #     control.log(f'{method} | {data}')


@hook_mimetype('application/dash+xml')
def _DASH_HOOK(item):
    if control.getBool('inputstreamadaptive.enabled'):
        stream_url = item.getPath()
        import inputstreamhelper
        is_helper = inputstreamhelper.Helper('mpd')
        if is_helper.check_inputstream():
            item.setProperty('inputstream', is_helper.inputstream_addon)
            if hasattr(item, 'setContentLookup'):
                item.setContentLookup(False)
            if hasattr(item, 'setMimeType'):
                item.setMimeType('application/dash+xml')
            if control.kodi_version < 20.9:
                item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
            if '|' in stream_url:
                stream_url, headers = stream_url.split('|')
                item.setPath(stream_url)  # Set clean URL without headers
                item.setProperty('inputstream.adaptive.stream_headers', headers)
                if control.kodi_version > 21.8:
                    item.setProperty('inputstream.adaptive.common_headers', headers)
                else:
                    item.setProperty('inputstream.adaptive.stream_params', headers)
                    item.setProperty('inputstream.adaptive.manifest_headers', headers)
        else:
            raise Exception("InputStream Adaptive is not supported.")
    return item


@hook_mimetype('application/vnd.apple.mpegurl')
@hook_mimetype('application/x-mpegurl')
@hook_mimetype('video/MP2T')
@hook_mimetype('image/jpeg')
def _HLS_HOOK(item):
    if control.getBool('inputstreamadaptive.enabled'):
        stream_url = item.getPath()
        import inputstreamhelper
        is_helper = inputstreamhelper.Helper('hls')
        if is_helper.check_inputstream():
            item.setProperty('inputstream', is_helper.inputstream_addon)
            if hasattr(item, 'setContentLookup'):
                item.setContentLookup(False)
            if hasattr(item, 'setMimeType'):
                item.setMimeType('application/vnd.apple.mpegurl')
            item.setProperty('MimeType', 'application/vnd.apple.mpegurl')
            if control.kodi_version < 20.9:
                item.setProperty('inputstream.adaptive.manifest_type', 'hls')
            if '|' in stream_url:
                stream_url, headers = stream_url.split('|')
                item.setPath(stream_url)  # Set clean URL without headers
                item.setProperty('inputstream.adaptive.stream_headers', headers)
                # For HLS AES-128 encrypted streams, license_key is used for key file requests
                item.setProperty('inputstream.adaptive.license_key', '|' + headers + '||R{SSM}')
                if control.kodi_version > 21.8:
                    item.setProperty('inputstream.adaptive.common_headers', headers)
                else:
                    item.setProperty('inputstream.adaptive.stream_params', headers)
                    item.setProperty('inputstream.adaptive.manifest_headers', headers)

    return item


class _HeadlessResolver:
    """Resolve one source candidate to a raw link without opening WindowXML UI."""

    def __init__(self, ep, mid):
        try:
            self.episode = int(ep) if ep is not None and str(ep).strip() != '' else 1
        except (TypeError, ValueError):
            self.episode = 1
        self.mal_id = mid
        self.pack_select = False

    def resolve_source(self, api_cls, source):
        try:
            api = api_cls()
            hash_ = source.get('hash')
            if not hash_:
                return None
            magnet = source.get('magnet') or f"magnet:?xt=urn:btih:{hash_}"
            stream_link = None

            if source.get('type') == 'torrent':
                filename = source.get('filename')
                if filename:
                    ep_reg = source_utils.get_cache_check_reg(self.episode)
                    clean_fname = re.sub(r'\[.*?\]', '', filename.split('/')[-1])
                    if not ep_reg.search(clean_fname):
                        filename = None
                ep_re = source.get('episode_re') or str(self.episode)
                stream_link = api.resolve_single_magnet(hash_, magnet, ep_re, self.pack_select, filename)
            elif source.get('type') == 'cloud':
                if source.get('debrid_provider') == 'Alldebrid':
                    return hash_
                resolved_hash = api.resolve_cloud(source, self.pack_select)
                if resolved_hash:
                    stream_link = api.resolve_hoster(resolved_hash)
            elif source.get('type') == 'hoster':
                if source.get('debrid_provider') == 'Easynews':
                    stream_link = api.unrestrict_link(source['hash'])
                else:
                    ep_re = source.get('episode_re') or str(self.episode)
                    stream_link = api.resolve_hoster(magnet, ep_re, self.pack_select)
            return stream_link
        except Exception as e:
            control.log(f"Headless resolver error: {e}", 'debug')
            return None


def _resolve_candidate_raw_link(helper, resolvers_map, s):
    stype = s.get('type')
    if stype in ('torrent', 'cloud', 'hoster'):
        dprov = s.get('debrid_provider')
        if stype == 'cloud' and dprov == 'Alldebrid':
            return s.get('hash') or s.get('url')
        if dprov in resolvers_map:
            return helper.resolve_source(resolvers_map[dprov], s)
        return None
    if stype in ('direct', 'local'):
        return s.get('hash') or s.get('url')
    if stype == 'embed':
        from resources.lib.ui import embed_extractor
        embed_url = s.get('hash') or s.get('url')
        return embed_extractor.load_video_from_url(embed_url) if embed_url else None
    return None


def failover_candidate_key(source, host=''):
    """Canonical deduplication key so failed CDN/debrid/mirror candidates are not retried."""
    if not isinstance(source, dict):
        return ''
    prov = str(source.get('provider') or '').strip().lower()
    dprov = str(source.get('debrid_provider') or '').strip().lower()
    h_val = str(source.get('hash') or source.get('url') or '').strip().lower()
    host_l = str(host or '').strip().lower()
    return f"{prov}|{dprov}|{h_val}|{host_l}"


def build_midstream_failover_candidates(ctx, failing_host='', enabled_providers=None, circuit_breaker=None):
    """Order alternate Debrid providers and remaining sources for NF-11 mid-stream CDN failover."""
    if not isinstance(ctx, dict):
        return []
    sources = list(ctx.get('sources') or [])
    if not sources:
        return []
    cand_idx = max(0, min(len(sources) - 1, int(ctx.get('candidate_index') or 0)))
    cur_src = sources[cand_idx]
    cur_prov = cur_src.get('debrid_provider') or ctx.get('debrid_provider') or ''
    cb = circuit_breaker or domains.adaptive_circuit_breaker
    tried = {str(k).strip().lower() for k in (ctx.get('tried_candidates') or []) if k}

    def _was_tried(src_item):
        if not tried:
            return False
        k_no_host = failover_candidate_key(src_item, '')
        return k_no_host in tried or any(tk.startswith(k_no_host) for tk in tried if k_no_host)

    out = []
    if cur_src.get('type') == 'torrent' and cur_src.get('hash'):
        providers = list(enabled_providers) if enabled_providers is not None else get_enabled_debrid_names()
        for alt_prov in providers:
            if not alt_prov or alt_prov == cur_prov:
                continue
            if cb and cb.is_tripped(alt_prov.lower(), category='debrid'):
                continue
            alt = dict(cur_src)
            alt['debrid_provider'] = alt_prov
            if not _was_tried(alt):
                out.append(alt)

    healthy_tail = []
    fallback_tail = []
    for cand in sources[cand_idx + 1:]:
        if not isinstance(cand, dict) or _was_tried(cand):
            continue
        prov = str(cand.get('debrid_provider') or '').lower()
        origin = _extract_source_origin(cand)
        origin_host = urllib.parse.urlparse(origin).netloc.lower() if origin else ''
        host_tripped = bool(
            (failing_host and origin_host and origin_host == failing_host.lower())
            or (prov and cb and cb.is_tripped(prov, category='debrid'))
            or (origin and not domains.is_mirror_healthy(origin))
        )
        if host_tripped:
            fallback_tail.append(cand)
        else:
            healthy_tail.append(cand)
    out.extend(healthy_tail)
    if not out:
        out.extend(fallback_tail)
    return out


def resolve_failover_candidate(ctx, mal_id=None, episode='1', failing_host='', circuit_breaker=None):
    """Resolve and probe the first healthy backup stream candidate for NF-11 mid-stream failover."""
    candidates = build_midstream_failover_candidates(ctx, failing_host=failing_host, circuit_breaker=circuit_breaker)
    if not candidates:
        return None
    resolvers_map = _build_resolvers_map()
    helper = _HeadlessResolver(episode, mal_id)
    f_host_low = str(failing_host or '').strip().lower()
    for cand in candidates:
        try:
            raw_link = _resolve_candidate_raw_link(helper, resolvers_map, cand)
            if not raw_link:
                continue
            verified = Resolver.prefetch_play_link(raw_link)
            if not verified or not verified.get('url'):
                continue
            cand_host = urllib.parse.urlparse(str(verified['url']).split('|', 1)[0]).netloc.lower()
            if f_host_low and cand_host and cand_host == f_host_low and len(candidates) > 1:
                continue
            return {
                'source': cand,
                'linkinfo': verified,
                'url': verified['url'],
                'headers': verified.get('headers') or {},
                'sub': cand.get('subs') or [],
            }
        except Exception as e:
            control.log(f"NF-11 failover probe error ({cand.get('debrid_provider') or cand.get('provider')}): {e}", level='debug')
    return None


def resolve_silent(sources, episode, mal_id=None):
    """
    Resolve the top candidate source silently in background without launching WindowXML dialog.
    Used for Zero-Wait Pre-Resolved stream handoffs.
    :param sources: Pre-scraped candidate source list
    :param episode: Target episode number
    :param mal_id: Anime MAL ID
    :return: dict with 'url', 'headers', 'source', 'sub' or None
    """
    if not sources:
        return None
    source_list = list(sources)
    if not source_list:
        return None

    resolvers = _build_resolvers_map()
    helper = _HeadlessResolver(episode, mal_id)
    ordered_sources = _deprioritize_unhealthy_hosts(source_list)
    has_cache_key = (
        mal_id is not None
        and not isinstance(mal_id, bool)
        and str(mal_id).strip() != ''
        and episode is not None
        and not isinstance(episode, bool)
        and str(episode).strip() != ''
    )
    failed_indices = set()

    def _persist_pruned_sources():
        if not failed_indices and ordered_sources == source_list:
            return
        remaining = [src for idx, src in enumerate(ordered_sources) if idx not in failed_indices]
        if isinstance(sources, list):
            sources[:] = remaining
        if has_cache_key:
            if remaining:
                database.set_episode_sources(mal_id, episode, remaining)
            else:
                database.clear_episode_sources(mal_id, episode)

    # Evaluate top candidates (try up to 3)
    for idx, s in enumerate(ordered_sources[:3]):
        if not s or not isinstance(s, dict):
            failed_indices.add(idx)
            continue
        stream_link = None
        try:
            stream_link = _resolve_candidate_raw_link(helper, resolvers, s)

            if stream_link:
                linkinfo = Resolver.prefetch_play_link(stream_link)
                if linkinfo:
                    _persist_pruned_sources()
                    if has_cache_key:
                        active_u = str(linkinfo.get('url') or '')
                        ap = urllib.parse.urlparse(active_u.split('|', 1)[0]) if active_u else None
                        database.save_playback_failover_context(
                            mal_id,
                            episode,
                            {
                                'sources': [src for i2, src in enumerate(ordered_sources) if i2 not in failed_indices],
                                'candidate_index': 0,
                                'active_url': active_u,
                                'active_host': ap.netloc.lower() if ap and ap.netloc else '',
                                'debrid_provider': s.get('debrid_provider', ''),
                                'media_type': 'episode',
                            },
                        )
                    return {
                        'url': linkinfo.get('url'),
                        'headers': linkinfo.get('headers', {}),
                        'source': s,
                        'sub': s.get('subs', []),
                        'resolved_at': time.time(),
                    }
        except Exception as e:
            control.log(f"resolve_silent error for candidate: {e}", 'debug')

        failed_indices.add(idx)
        _mark_candidate_mirror_failure(s, stream_link, cooldown=900)
        control.log(
            f"resolve_silent: pruned failing candidate provider={s.get('provider')} type={s.get('type')}",
            level='warning',
        )

    _persist_pruned_sources()
    return None

