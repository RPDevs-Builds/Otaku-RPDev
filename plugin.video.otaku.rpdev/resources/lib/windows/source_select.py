import xbmcgui

from resources.lib.ui import control, database, colors, source_utils
from resources.lib.windows.base_window import BaseWindow
from resources.lib.windows.download_manager import Manager
from resources.lib.windows.resolver import Resolver
from resources.lib import MetaBrowser


class SourceSelect(BaseWindow):
    def __init__(self, xml_file, location, actionArgs=None, sources=None, rescrape=None):
        super().__init__(xml_file, location, actionArgs=actionArgs)
        self.actionArgs = actionArgs
        self.sources = sources
        self.displayed_sources = []  # List to maintain displayed sources
        self.showing_uncached = False  # Track whether uncached sources are being shown
        self.rescrape = rescrape
        self.position = -1
        self.canceled = False
        self.display_list = None
        self.stream_link = None
        self.view_mode = 'both'  # Default view mode
        episode = actionArgs.get('episode')

        # Set properties for the selected episode
        if episode:
            anime_init = MetaBrowser.get_anime_init(actionArgs.get('mal_id'))
            episode = int(episode)
            try:
                self.setProperty('item.info.season', str(anime_init[0][episode - 1]['info']['season']))
                self.setProperty('item.info.episode', str(anime_init[0][episode - 1]['info']['episode']))
                self.setProperty('item.info.title', str(anime_init[0][episode - 1]['info']['title'] or ''))
                self.setProperty('item.info.plot', str(anime_init[0][episode - 1]['info']['plot'] or ''))
                ep_thumb = anime_init[0][episode - 1]['image'].get('thumb')
                if isinstance(ep_thumb, (list, tuple)):
                    ep_thumb = ep_thumb[0] if ep_thumb else ''
                if ep_thumb:
                    self.setProperty('item.art.thumb', ep_thumb)
                ep_poster = anime_init[0][episode - 1]['image'].get('poster') or (self.item_information.get('poster') if isinstance(self.item_information, dict) else '')
                if isinstance(ep_poster, (list, tuple)):
                    ep_poster = ep_poster[0] if ep_poster else ''
                if ep_poster:
                    self.setProperty('item.art.poster', ep_poster)
            except IndexError:
                self.setProperty('item.info.season', '-1')
                self.setProperty('item.info.episode', '-1')

            try:
                fallback_aired = self.item_information.get('start_date') if isinstance(self.item_information, dict) else ''
                aired = anime_init[0][episode - 1]['info'].get('aired') or fallback_aired or '0000-00-00'
                year, month, day = aired.split('-')
                self.setProperty('item.info.aired', aired)
                self.setProperty('item.info.year', year)
            except (ValueError, AttributeError, IndexError):
                pass
        else:
            show = database.get_show(actionArgs.get('mal_id'))
            if show:
                kodi_meta = database.loads(show.get('kodi_meta')) or {}
                self.setProperty('item.info.plot', kodi_meta.get('plot') or '')
                rating_raw = kodi_meta.get('rating')
                score = rating_raw.get('score') if isinstance(rating_raw, dict) else rating_raw
                self.setProperty('item.info.rating', score if score is not None else '')
                self.setProperty('item.info.aired', kodi_meta.get('start_date') or '')
                poster_val = kodi_meta.get('poster')
                if isinstance(poster_val, (list, tuple)):
                    poster_val = poster_val[0] if poster_val else ''
                self.setProperty('item.art.thumb', poster_val or '')
                start_date = kodi_meta.get('start_date')
                if start_date and isinstance(start_date, str) and '-' in start_date:
                    self.setProperty('item.info.year', start_date.split('-')[0])

        fanart = (actionArgs.get('fanart') if actionArgs else None) or (self.item_information.get('fanart') if isinstance(self.item_information, dict) else None)
        if fanart:
            if isinstance(fanart, list):
                fanart = fanart[0] if fanart else ''
            if fanart:
                self.setProperty('item.art.fanart', str(fanart))
        clearlogo = (actionArgs.get('clearlogo') if actionArgs else None) or (self.item_information.get('clearlogo') if isinstance(self.item_information, dict) else None)
        if clearlogo:
            if isinstance(clearlogo, list):
                clearlogo = clearlogo[0] if clearlogo else ''
            if clearlogo:
                self.setProperty('item.art.clearlogo', str(clearlogo))

    def onInit(self):
        self.display_list = self.getControl(1000)
        # build all four lists
        cached = [s for s in self.sources if s.get('cached') is True]
        uncached = [s for s in self.sources if s.get('cached') is False]
        embeds = [s for s in self.sources if s.get('type') in ('embed', 'direct')]
        both = list(self.sources)

        # always start on “both”
        self.view_mode = 'both'
        self._show_current_sources(cached, both, uncached, embeds)
        self.setFocusId(1000)

    def _show_current_sources(self, cached, both, uncached, embeds):
        if self.view_mode == 'both':
            items, label = both, "View Cached"
        elif self.view_mode == 'cached':
            items, label = cached, "View Uncached"
        elif self.view_mode == 'uncached':
            items, label = uncached, "View Embeds"
        else:  # 'embeds'
            items, label = embeds, "View Both"

        self.populate_sources(items)
        # update the button label
        self.getControl(15).setLabel(label)

    def populate_sources(self, sources):
        self.display_list.reset()
        self.displayed_sources = sources  # Update the displayed sources list
        show_badges = control.getBool('interface.source_select.badges', default=True)
        for source in sources:
            if source is None:
                continue
            debrid_name = source.get('debrid_provider') or ''
            provider_name = source.get('provider') or ''
            source_type = source.get('type') or source.get('source') or ''

            p_color = colors.get_provider_color(provider_name or source_type)
            d_color = colors.get_provider_color(debrid_name or source_type)

            info_raw = source.get('info', [])
            if isinstance(info_raw, list):
                info_list = [str(t) for t in info_raw if t]
            else:
                info_str = str(info_raw or '')
                info_list = [t.strip() for t in info_str.replace('|', ' ').split() if t.strip()]

            if source_utils.is_season_pack(source) and 'BATCH' not in info_list:
                info_list.append('BATCH')
            info_str = ' '.join(info_list)

            raw_qual = str(source.get('quality', '')).strip().lower()
            qual_map = {
                '0': '0', 'eq': '0',
                '1': '1', '480p': '1', 'sd': '1', '480': '1',
                '2': '2', '720p': '2', '720': '2', 'hd': '2',
                '3': '3', '1080p': '3', '1080': '3', 'fhd': '3',
                '4': '4', '4k': '4', '2160p': '4', '2160': '4', 'uhd': '4',
            }
            norm_quality = qual_map.get(raw_qual, raw_qual)

            codec = next((t for t in info_list if t.upper() in ('HEVC', 'AVC', 'AV1', 'VP9', 'XVID', 'DIVX', 'MP4', 'H.264', 'H.265')), '')
            audio_channels = next((t for t in info_list if t in ('7.1', '5.1', '2.0', '1.0')), '')
            audio_codec = next((t for t in info_list if t.upper() in ('AAC', 'DTS', 'DTS-HDMA', 'DTS-X', 'ATMOS', 'TRUEHD', 'DD+', 'DD', 'OPUS', 'FLAC', 'MP3')), '')
            raw_rel_title = source.get('release_title', '')
            hdr_type = source_utils.detect_hdr_type(raw_rel_title, stream_info=source.get('stream_info'))
            hdr_badge = (
                next((t for t in info_list if t.upper() in ('DV', 'DOVI', 'HDR', 'HDR10', 'HDR10+', 'HLG', 'HYBRID')), '')
                or source_utils.format_hdr_badge(hdr_type)
            )
            if not hdr_type and hdr_badge:
                hdr_type = source_utils.detect_hdr_type(hdr_badge)

            seeders_raw = source.get('seeders', -1)
            seeders_str = str(seeders_raw) if seeders_raw != -1 else 'na'

            if show_badges:
                colored_debrid = f"[COLOR {d_color}]{debrid_name}[/COLOR]" if debrid_name else f"[COLOR {p_color}]{source_type.upper()}[/COLOR]"
                colored_provider = f"[COLOR {p_color}]{provider_name}[/COLOR]" if provider_name else ""
                colored_codec = colors.colorize_badge(codec) if codec else ""
                colored_audio = colors.colorize_badge(audio_channels or audio_codec) if (audio_channels or audio_codec) else ""
                colored_hdr = colors.colorize_badge(hdr_badge) if hdr_badge else ""
                colored_seeders = f"[COLOR {colors.get_seeder_color(seeders_str)}]{seeders_str}[/COLOR]" if seeders_str != 'na' else 'na'
            else:
                colored_debrid = debrid_name if debrid_name else source_type.upper()
                colored_provider = provider_name
                colored_codec = codec
                colored_audio = audio_channels or audio_codec
                colored_hdr = hdr_badge
                colored_seeders = seeders_str

            release_title = source.get('release_title', '')
            release_group = source_utils.extract_release_group(release_title or source.get('filename') or '')
            menu_item = xbmcgui.ListItem(release_title, offscreen=True)
            properties = {
                'type': source_type,
                'debrid_provider': debrid_name,
                'provider': provider_name,
                'provider_color': p_color,
                'debrid_color': d_color,
                'colored_debrid': colored_debrid,
                'colored_provider': colored_provider,
                'quality': norm_quality,
                'info': info_str,
                'codec': codec,
                'audio_channels': audio_channels,
                'audio_codec': audio_codec,
                'hdr_type': hdr_type,
                'hdr_badge': hdr_badge,
                'colored_codec': colored_codec,
                'colored_audio': colored_audio,
                'colored_hdr': colored_hdr,
                'seeders': seeders_str,
                'colored_seeders': colored_seeders,
                'size': source.get('size', ''),
                'release_group': release_group,
                'group_pin_status': self._get_group_pin_status(release_group),
            }
            menu_item.setProperties(properties)
            self.display_list.addItem(menu_item)

    def _get_mal_id(self):
        raw_args = getattr(self, 'actionArgs', None)
        args = raw_args if isinstance(raw_args, dict) else {}
        mal_id = str(args.get('mal_id') or '').strip()
        return mal_id if mal_id.isdigit() else ''

    def _get_group_pin_status(self, release_group):
        mal_id = self._get_mal_id()
        if not mal_id or not release_group:
            return ''
        override = database.get_series_override(mal_id)
        if not isinstance(override, dict):
            return ''
        norm_grp = source_utils.normalize_release_group(release_group)
        if norm_grp and norm_grp == source_utils.normalize_release_group(override.get('preferred_group')):
            return 'pinned'
        if norm_grp and norm_grp in source_utils.parse_excluded_groups(override.get('excluded_groups')):
            return 'excluded'
        return ''

    def _refresh_group_status_in_place(self):
        """Mutate ListItem group_pin_status properties in place without resetting focus."""
        if self.display_list is None:
            return
        try:
            count = self.display_list.size()
        except Exception:
            return
        for idx in range(min(count, len(self.displayed_sources))):
            src = self.displayed_sources[idx]
            grp = source_utils.extract_release_group(src.get('release_title') or src.get('filename') or '')
            status = self._get_group_pin_status(grp)
            try:
                li = self.display_list.getListItem(idx)
                if li is not None:
                    li.setProperty('release_group', grp)
                    li.setProperty('group_pin_status', status)
            except Exception:
                pass

    def doModal(self):
        super().doModal()
        return self.stream_link

    def handle_action(self, action_id):
        # Implement the logic for handling the action here
        # For now, you can just log the action_id
        control.log(f"Action handled: {action_id}")

    def onClick(self, controlId):
        if controlId == 15:  # cycle views
            sequence = ['both', 'cached', 'uncached', 'embeds']
            idx = sequence.index(self.view_mode)
            self.view_mode = sequence[(idx + 1) % len(sequence)]

            # rebuild the four lists and refresh
            cached = [s for s in self.sources if s.get('cached') is True]
            uncached = [s for s in self.sources if s.get('cached') is False]
            embeds = [s for s in self.sources if s.get('type') in ('embed', 'direct')]
            both = list(self.sources)
            self._show_current_sources(cached, both, uncached, embeds)

        elif controlId == 1000:
            self.position = self.display_list.getSelectedPosition()
            if self.position < 0 or not self.displayed_sources or self.position >= len(self.displayed_sources):
                return
            self.resolve_item()

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [9, 10, 92, 110, 216]:
            # BACK / BACKSPACE / ESCAPE (including Android TV remote back action 9)
            control.playList.clear()
            self.stream_link = False
            self.close()

        if actionID == 117:
            # Extract selected item before any dialog/close (prevents stale position reads)
            self.position = self.display_list.getSelectedPosition() if self.display_list is not None else -1
            if self.position < 0 or not self.displayed_sources or self.position >= len(self.displayed_sources):
                return
            selected_source = self.displayed_sources[self.position]
            mal_id = self._get_mal_id()
            release_group = source_utils.extract_release_group(
                selected_source.get('release_title') or selected_source.get('filename') or ''
            )
            pin_status = self._get_group_pin_status(release_group) if (mal_id and release_group) else ''

            menu_options = ["Play", "Download", "File Select"]
            action_keys = ["play", "download", "file_select"]
            if mal_id and release_group:
                if pin_status == 'pinned':
                    menu_options.append(f"Unpin Release Group: {release_group}")
                    action_keys.append("unpin_group")
                else:
                    menu_options.append(f"Pin Release Group: {release_group}")
                    action_keys.append("pin_group")
                if pin_status == 'excluded':
                    menu_options.append(f"Remove {release_group} from Exclusions")
                    action_keys.append("unexclude_group")
                else:
                    menu_options.append(f"Exclude Release Group: {release_group}")
                    action_keys.append("exclude_group")

            context = control.context_menu(menu_options)
            if context < 0 or context >= len(action_keys):
                return
            chosen = action_keys[context]
            if chosen == "play":
                self.resolve_item()
            elif chosen == "download":
                if selected_source.get('debrid_provider') in ('Local-Debrid', ''):
                    control.notify(control.ADDON_NAME, "Please Select A Debrid File")
                elif selected_source.get('debrid_provider') == 'EasyDebrid':
                    control.notify(control.ADDON_NAME, "EasyDebrid does not support Downloads")
                else:
                    source = [selected_source]
                    self.close()
                    self.actionArgs['play'] = False
                    resolver_dialog = None
                    try:
                        if control.getInt('general.dialog') in (5, 6):
                            resolver_dialog = Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True)
                        else:
                            resolver_dialog = Resolver('resolver.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True)
                        return_data = resolver_dialog.doModal(source, {}, False)
                    finally:
                        if resolver_dialog:
                            try:
                                resolver_dialog.close()
                            except Exception:
                                pass
                            del resolver_dialog
                    if isinstance(return_data, dict):
                        Manager().download_file(return_data['link'])

            elif chosen == "file_select":
                if not selected_source.get('debrid_provider'):
                    control.notify(control.ADDON_NAME, "Please Select A Debrid File")
                else:
                    self.resolve_item(True)
            elif chosen == "pin_group":
                if database.pin_series_release_group(mal_id, release_group):
                    database.clear_episode_sources(mal_id)
                    self._refresh_group_status_in_place()
                    control.notify(control.ADDON_NAME, f"Pinned release group: {release_group}")
            elif chosen == "unpin_group":
                if database.unpin_series_release_group(mal_id):
                    database.clear_episode_sources(mal_id)
                    self._refresh_group_status_in_place()
                    control.notify(control.ADDON_NAME, f"Unpinned release group: {release_group}")
            elif chosen == "exclude_group":
                if database.exclude_series_release_group(mal_id, release_group, remove=False):
                    database.clear_episode_sources(mal_id)
                    self._refresh_group_status_in_place()
                    control.notify(control.ADDON_NAME, f"Excluded release group: {release_group}")
            elif chosen == "unexclude_group":
                if database.exclude_series_release_group(mal_id, release_group, remove=True):
                    database.clear_episode_sources(mal_id)
                    self._refresh_group_status_in_place()
                    control.notify(control.ADDON_NAME, f"Removed {release_group} from exclusions")

    def close(self):
        self.displayed_sources = []
        self.sources = []
        self.display_list = None
        super().close()

    def resolve_item(self, pack_select=False):
        if self.position < 0 or not self.displayed_sources or self.position >= len(self.displayed_sources):
            return
        if control.getBool('general.autotrynext') and not pack_select:
            sources = self.displayed_sources[self.position:]
        else:
            sources = [self.displayed_sources[self.position]]
        if self.rescrape:
            selected_source = self.displayed_sources[self.position]
            selected_source['name'] = selected_source['release_title']
        self.actionArgs['close'] = self.close
        resolver_dialog = None
        try:
            if control.getInt('general.dialog') in (5, 6):
                resolver_dialog = Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True)
            else:
                resolver_dialog = Resolver('resolver.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True)
            self.stream_link = resolver_dialog.doModal(sources, {}, pack_select)
        finally:
            if isinstance(self.actionArgs, dict):
                self.actionArgs.pop('close', None)
            if resolver_dialog:
                try:
                    resolver_dialog.close()
                except Exception:
                    pass
                del resolver_dialog
        if isinstance(self.stream_link, dict):
            self.close()
