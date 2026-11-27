# -*- coding: utf-8 -*-

import re
import time
import xbmc
import xbmcgui

from resources.lib import Main
from resources.lib.ui import control
from resources.lib.windows.anichart_window import BaseWindow
from resources.lib import MetaBrowser, WatchlistIntegration

BROWSER = MetaBrowser.BROWSER
_YOUTUBE_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?.*?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,20})',
    re.IGNORECASE,
)


def _supports_inline_trailers():
    """Return True only when NF-15 inline trailers are enabled AND Kodi 22 ControlVideoWindow exists."""
    return bool(
        control.getBool('interface.anichart.inline_trailers', True)
        and hasattr(xbmcgui, 'ControlVideoWindow')
    )


def _resolve_preview_trailer_url(item):
    """Extract a playable trailer URL, gating YouTube links on plugin.video.youtube availability."""
    if not isinstance(item, dict):
        return ''
    raw = str(item.get('trailer_url') or item.get('trailer') or '').strip()
    if not raw:
        return ''
    low = raw.lower()
    is_yt = ('plugin.video.youtube' in low) or ('youtube.com' in low) or ('youtu.be' in low)
    if is_yt:
        try:
            if not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
                return ''
        except Exception:
            return ''
        if low.startswith('plugin://plugin.video.youtube'):
            return raw
        m = _YOUTUBE_ID_RE.search(raw)
        if m:
            return f"plugin://plugin.video.youtube/play/?video_id={m.group(1)}"
        return ''
    if low.startswith(('http://', 'https://', 'plugin://')):
        return raw
    return ''


class Anichart(BaseWindow):

    def __init__(self, xml_file, location, get_anime=None, anime_items=None, calendar=None):
        super().__init__(xml_file, location)
        self.get_anime = get_anime
        self.anime_items = anime_items
        self.position = -1
        self.display_list = None
        self.last_action_time = 0
        self.last_touch_position = -1
        self.touch_count = 0
        self.anime_path = ''
        self.anime_items = calendar if calendar is not None else anime_items
        self._win_closed = False
        self._trailer_active = False
        self._trailer_position = -1
        self._prev_mute_state = None

    def _start_inline_trailer(self, position=None):
        """Start muted inline trailer preview in ControlVideoWindow (Kodi 22+, NF-15)."""
        if not _supports_inline_trailers():
            return False
        if not self.anime_items:
            return False
        if position is None and self.display_list is not None:
            try:
                position = self.display_list.getSelectedPosition()
            except Exception:
                position = -1
        if position is None or not (0 <= position < len(self.anime_items)):
            return False
        if self._trailer_active and self._trailer_position == position:
            return True

        player = xbmc.Player()
        # Never interrupt active user media playback (unless we started the previous preview)
        if not self._trailer_active:
            try:
                if player.isPlaying():
                    return False
            except Exception:
                return False

        trailer_url = _resolve_preview_trailer_url(self.anime_items[position])
        if not trailer_url:
            if self._trailer_active:
                self._stop_inline_trailer()
            return False

        if self._trailer_active:
            self._stop_inline_trailer()

        try:
            was_muted = bool(xbmc.getCondVisibility('Player.Muted'))
            self._prev_mute_state = was_muted
            if not was_muted:
                control.jsonrpc({
                    'jsonrpc': '2.0',
                    'method': 'Application.SetMute',
                    'params': {'mute': True},
                    'id': 1,
                })
        except Exception:
            self._prev_mute_state = None

        control.setGlobalProp('otaku.preview_mode', 'true')
        self.setProperty('anichart.trailer_active', 'true')
        self._trailer_active = True
        self._trailer_position = position
        try:
            li = xbmcgui.ListItem(
                label=str(self.anime_items[position].get('release_title') or 'Trailer Preview'),
                path=trailer_url,
                offscreen=True,
            )
            player.play(trailer_url, listitem=li, windowed=True)
            return True
        except Exception as e:
            control.log(f"[ANICHART] Inline trailer preview failed: {e}", 'debug')
            self._stop_inline_trailer()
            return False

    def _stop_inline_trailer(self):
        """Stop active inline trailer preview and restore prior mute & preview state."""
        was_active = bool(getattr(self, '_trailer_active', False))
        prev_mute = getattr(self, '_prev_mute_state', None)
        self._trailer_active = False
        self._trailer_position = -1
        if was_active:
            try:
                self.clearProperty('anichart.trailer_active')
            except Exception:
                try:
                    self.setProperty('anichart.trailer_active', '')
                except Exception:
                    pass
            control.clearGlobalProp('otaku.preview_mode')
            try:
                player = xbmc.Player()
                if player.isPlaying():
                    player.stop()
            except Exception:
                pass
        if prev_mute is False:
            try:
                control.jsonrpc({
                    'jsonrpc': '2.0',
                    'method': 'Application.SetMute',
                    'params': {'mute': False},
                    'id': 1,
                })
            except Exception:
                pass
        self._prev_mute_state = None

    def close(self):
        self._stop_inline_trailer()
        try:
            super().close()
        finally:
            self._win_closed = True

    def onInit(self):
        self.display_list = self.getControl(1000)
        menu_items = []

        control.log(f"[ANICHART] Initializing with {len(self.anime_items)} anime items", "info")
        if self.anime_items and len(self.anime_items) > 0:
            control.log(f"[ANICHART] First item keys: {list(self.anime_items[0].keys())}", "info")
            control.log(f"[ANICHART] First item sample: {str(self.anime_items[0])[:500]}", "info")

        for idx, i in enumerate(self.anime_items):
            if not i:
                continue

            menu_item = control.menuItem(label='%s' % i['release_title'])
            for info in list(i.keys()):
                try:
                    value = i[info]
                    if isinstance(value, list):
                        value = [str(k) for k in value if k is not None]
                        value = ' '.join(sorted(value))
                    val_str = '' if value is None else str(value).replace('_', ' ')
                    menu_item.setProperty(str(info), val_str)
                except UnicodeEncodeError:
                    raw_val = i[info]
                    menu_item.setProperty(str(info), '' if raw_val is None else str(raw_val))

            menu_items.append(menu_item)
            self.display_list.addItem(menu_item)

        control.log(f"[ANICHART] Successfully added {len(menu_items)} items to display list", "info")
        self.setFocusId(1000)

    def doModal(self):
        super().doModal()
        return self.anime_path

    def onDoubleClick(self, controlId):
        # immediate activate on double-click
        control.log(f"Double click detected on control: {controlId}")
        if controlId == 1000:  # only handle double-clicks on our anime list
            control.log("Handling double click action")
            self.handle_action(controlId)

    def onClick(self, controlId):
        self.handle_action(controlId)

    def onAction(self, action):
        actionID = action.getId()
        control.log(f"Action detected: {actionID}")

        # back navigation (including Android TV remote back action 9)
        if actionID in [9, 10, 92, 216,
                        xbmcgui.ACTION_NAV_BACK,
                        xbmcgui.ACTION_PREVIOUS_MENU]:
            self.close()
            return

        # NF-15: Stop preview when moving focus to a different anime card; toggle preview on Info (11)
        if actionID in (1, 2, 3, 4, 5, 6):
            if self._trailer_active and self.display_list is not None:
                try:
                    cur_pos = self.display_list.getSelectedPosition()
                except Exception:
                    cur_pos = -1
                if cur_pos != self._trailer_position:
                    self._stop_inline_trailer()
        elif actionID == 11:  # ACTION_SHOW_INFO toggles inline trailer preview on Kodi 22+
            if self._trailer_active:
                self._stop_inline_trailer()
            else:
                self._start_inline_trailer()
            return

        # Touch input fallback - require double tap when onClick is not dispatched
        if actionID == xbmcgui.ACTION_TOUCH_TAP:
            control.log("Touch input detected - checking for double tap")
            current_time = time.time()
            current_position = self.display_list.getSelectedPosition() if self.getFocusId() == 1000 else -1

            # Check if this is a double-tap (same position within 0.5 seconds)
            time_diff = current_time - self.last_action_time
            is_double_tap = (time_diff < 0.5
                             and current_position == self.last_touch_position
                             and current_position != -1)

            if is_double_tap:
                control.log("Double tap detected - activating")
                self.handle_action(1000)
                # Reset to prevent triple-tap activation
                self.last_action_time = 0
                self.last_touch_position = -1
            else:
                control.log(f"First tap detected at position {current_position}")
                # Store tap info for potential double-tap
                self.last_action_time = current_time
                self.last_touch_position = current_position

        # rest of your existing context‐menu code…
        if actionID == 117:
            context_menu_options = []
            if control.getBool('context.otaku.findrecommendations'):
                context_menu_options.append("Find Recommendations")
            if control.getBool('context.otaku.findrelations'):
                context_menu_options.append("Find Relations")
            if control.getBool('context.otaku.getwatchorder'):
                context_menu_options.append("Get Watch Order")
            if control.getBool('context.otaku.viewreviews'):
                context_menu_options.append("View Reviews")
            if control.getBool('context.otaku.viewstatistics'):
                context_menu_options.append("View Statistics")
            if control.getBool('context.otaku.deletefromdatabase'):
                context_menu_options.append("Delete From Database")
            if control.getBool('context.otaku.watchlist'):
                context_menu_options.append("WatchList Manager")

            context = control.context_menu(context_menu_options)
            # if user cancels (context == -1), just return
            if context < 0:
                return

            self.position = self.display_list.getSelectedPosition()
            if not self.anime_items or not (0 <= self.position < len(self.anime_items)):
                return
            item = self.anime_items[self.position]
            anime = item.get('id') or item.get('mal_id')
            if not anime:
                return
            page = 1

            choice = context_menu_options[context]
            if choice == "Find Recommendations":
                control.draw_items(BROWSER.get_recommendations(anime, page), 'tvshows')
                self.close()
            elif choice == "Find Relations":
                control.draw_items(BROWSER.get_relations(anime), 'tvshows')
                self.close()
            elif choice == "Get Watch Order":
                control.draw_items(BROWSER.get_watch_order(anime), 'tvshows')
                self.close()
            elif choice == "View Reviews":
                Main.draw_anime_reviews_listing(anime, page, 'animes', '0')
                self.close()
            elif choice == "View Statistics":
                Main.open_anime_statistics(anime)
                self.close()
            elif choice == "Delete From Database":
                payload = f"some_path/{anime}/0"
                params = {}
                Main.DELETE_ANIME_DATABASE(payload, params)
            elif choice == "WatchList Manager":
                payload = f"some_path/{anime}/0"
                params = {}
                WatchlistIntegration.CONTEXT_MENU(payload, params)

    def handle_action(self, actionID) -> None:
        if getattr(self, '_activated', False):
            return
        # only act when control 1000 is clicked or focused
        if actionID != 1000 and self.getFocusId() != 1000:
            return

        self.position = self.display_list.getSelectedPosition()
        if not self.anime_items or not (0 <= self.position < len(self.anime_items)):
            return
        self._activated = True
        self._stop_inline_trailer()

        # Get the selected anime item
        selected_item = self.anime_items[self.position]

        control.log(f"[ANICHART] Selected anime at position {self.position}", "info")
        control.log(f"[ANICHART] Selected item keys: {list(selected_item.keys())}", "debug")
        control.log(f"[ANICHART] Selected item title: {selected_item.get('release_title', 'N/A')}", "info")
        control.log(f"[ANICHART] Selected item mal_id: {selected_item.get('mal_id', 'N/A')}", "info")
        control.log(f"[ANICHART] Selected item id: {selected_item.get('id', 'N/A')}", "info")
        control.log(f"[ANICHART] Selected item route: {selected_item.get('route', 'N/A')}", "info")

        # Extract MAL ID - try different fields for compatibility
        anime_id = selected_item.get('mal_id') or selected_item.get('id') or selected_item.get('route')

        # Fetch anime data to ensure it's cached
        from resources.lib.OtakuBrowser import OtakuBrowser
        OtakuBrowser().get_anime_data(anime_id)

        control.log(f"[ANICHART] Resolved anime_id: {anime_id}", "info")

        if not anime_id:
            control.log("Error: Could not find anime ID in selected item", "error")
            return

        # Ensure we have a numeric ID for the URL
        try:
            if not isinstance(anime_id, int):
                anime_id = int(anime_id) if anime_id.isdigit() else anime_id
        except (ValueError, AttributeError):
            pass

        url = f"animes/{anime_id}/"
        self.anime_path = control.addon_url(url)

        control.log(f"[ANICHART] Generated URL: {self.anime_path}", "info")

        # Show progress dialog for all actions
        control.progressDialog.create(control.ADDON_NAME, "Loading..")
        try:
            new_payload, new_params = control.get_payload_params(self.anime_path)
            if 'animes/' in new_payload:
                x = new_payload.split('animes/', 1)[1]
                Main.ANIMES_PAGE(x, new_params)
            elif 'airing_calendar' in new_payload:
                Main.AIRING_CALENDAR(new_payload.rsplit('airing_calendar', 0)[0], new_params)
        finally:
            control.progressDialog.close()
        self.close()
