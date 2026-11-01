import xbmcgui

from resources.lib.ui import control, database, colors
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
                self.setProperty('item.info.title', anime_init[0][episode - 1]['info']['title'])
                self.setProperty('item.info.plot', anime_init[0][episode - 1]['info']['plot'])
                self.setProperty('item.art.thumb', anime_init[0][episode - 1]['image']['thumb'])
                self.setProperty('item.art.poster', anime_init[0][episode - 1]['image']['poster'])
            except IndexError:
                self.setProperty('item.info.season', '-1')
                self.setProperty('item.info.episode', '-1')

            try:
                aired = anime_init[0][episode - 1]['info'].get('aired') or '0000-00-00'
                year, month, day = aired.split('-')
                self.setProperty('item.info.aired', aired)
                self.setProperty('item.info.year', year)
            except (ValueError, AttributeError, IndexError):
                pass
        else:
            show = database.get_show(actionArgs.get('mal_id'))
            if show:
                kodi_meta = database.loads(show.get('kodi_meta'))
                self.setProperty('item.info.plot', kodi_meta.get('plot'))
                self.setProperty('item.info.rating', str(kodi_meta.get('rating', {}).get('score')))
                self.setProperty('item.info.aired', kodi_meta.get('start_date') or '')
                self.setProperty('item.art.thumb', kodi_meta.get('poster'))
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
            source_type = source.get('type') or ''

            p_color = colors.get_provider_color(provider_name or source_type)
            d_color = colors.get_provider_color(debrid_name or source_type)

            info_list = source.get('info', [])
            info_str = ' '.join(info_list) if isinstance(info_list, list) else str(info_list)

            codec = next((t for t in info_list if t.upper() in ('HEVC', 'AVC', 'AV1', 'VP9', 'XVID', 'DIVX', 'MP4', 'H.264', 'H.265')), '')
            audio_channels = next((t for t in info_list if t in ('7.1', '5.1', '2.0', '1.0')), '')
            audio_codec = next((t for t in info_list if t.upper() in ('AAC', 'DTS', 'DTS-HDMA', 'DTS-X', 'ATMOS', 'TRUEHD', 'DD+', 'DD', 'OPUS', 'FLAC', 'MP3')), '')
            hdr_badge = next((t for t in info_list if t.upper() in ('DV', 'DOVI', 'HDR', 'HDR10', 'HDR10+', 'HYBRID')), '')

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

            menu_item = xbmcgui.ListItem(source.get('release_title', ''), offscreen=True)
            properties = {
                'type': source_type,
                'debrid_provider': debrid_name,
                'provider': provider_name,
                'provider_color': p_color,
                'debrid_color': d_color,
                'colored_debrid': colored_debrid,
                'colored_provider': colored_provider,
                'quality': str(source.get('quality', '')),
                'info': info_str,
                'codec': codec,
                'audio_channels': audio_channels,
                'audio_codec': audio_codec,
                'hdr_badge': hdr_badge,
                'colored_codec': colored_codec,
                'colored_audio': colored_audio,
                'colored_hdr': colored_hdr,
                'seeders': seeders_str,
                'colored_seeders': colored_seeders,
                'size': source.get('size', '')
            }
            menu_item.setProperties(properties)
            self.display_list.addItem(menu_item)

    def doModal(self):
        super(SourceSelect, self).doModal()
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
            pass

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [9, 10, 92, 110, 216]:
            # BACK / BACKSPACE / ESCAPE (including Android TV remote back action 9)
            control.playList.clear()
            self.stream_link = False
            self.close()

        if actionID in [7, 100] and self.getFocusId() == 1000:
            self.position = self.display_list.getSelectedPosition()
            if self.position < 0 or not self.displayed_sources or self.position >= len(self.displayed_sources):
                return
            self.resolve_item()

        if actionID == 117:
            context = control.context_menu(
                [
                    "Play",
                    "Download",
                    "File Select"
                ]
            )
            self.position = self.display_list.getSelectedPosition()
            if self.position < 0 or not self.displayed_sources or self.position >= len(self.displayed_sources):
                return
            if context == 0:  # Play
                self.resolve_item()
            elif context == 1:  # Download
                if self.displayed_sources[self.position]['debrid_provider'] == 'Local-Debrid' or self.displayed_sources[self.position]['debrid_provider'] == '':
                    control.notify(control.ADDON_NAME, "Please Select A Debrid File")
                elif self.displayed_sources[self.position]['debrid_provider'] == 'EasyDebrid':
                    control.notify(control.ADDON_NAME, "EasyDebrid does not support Downloads")
                else:
                    self.close()
                    source = [self.displayed_sources[self.display_list.getSelectedPosition()]]
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

            elif context == 2:  # File Selection
                if not self.displayed_sources[self.position]['debrid_provider']:
                    control.notify(control.ADDON_NAME, "Please Select A Debrid File")
                else:
                    self.resolve_item(True)

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
