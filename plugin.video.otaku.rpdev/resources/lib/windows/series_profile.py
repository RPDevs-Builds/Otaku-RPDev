# -*- coding: utf-8 -*-
"""
    Otaku Add-on - Per-Series Playback Profile Editor WindowXML (NF-12)
    Provides an interactive GUI editor over SQLite series_overrides supporting
    audio/subtitle/provider/filler overrides alongside per-cour episode_offset
    and visual intro/outro skip offset tuning.
"""

import xbmcgui
from resources.lib.ui import control, database
from resources.lib.windows.base_window import BaseWindow

_AUDIO_CHOICES = [
    (None, 'Global Default'),
    ('jpn', 'Japanese (Sub)'),
    ('eng', 'English (Dub)'),
]

_SUB_LANG_CHOICES = [
    (None, 'Global Default'),
    ('none', 'Disabled (None)'),
    ('eng', 'English'),
    ('jpn', 'Japanese'),
    ('spa', 'Spanish'),
    ('fre', 'French'),
    ('ger', 'German'),
    ('ita', 'Italian'),
    ('dut', 'Dutch'),
    ('rus', 'Russian'),
    ('por', 'Portuguese'),
    ('kor', 'Korean'),
    ('chi', 'Chinese'),
    ('ara', 'Arabic'),
    ('hin', 'Hindi'),
    ('tur', 'Turkish'),
    ('pol', 'Polish'),
    ('swe', 'Swedish'),
    ('nor', 'Norwegian'),
    ('dan', 'Danish'),
    ('fin', 'Finnish'),
]

_SUB_MODE_CHOICES = [
    (None, 'Global Default'),
    ('dialog', 'Full Dialogue'),
    ('signs', 'Signs & Songs'),
    ('smart', 'Smart Pair'),
]

_PROVIDER_CHOICES = [
    (None, 'Global Default'),
    ('nyaa', 'Nyaa'),
    ('animetosho', 'AnimeTosho'),
    ('nekobt', 'NekoBT'),
    ('bitsearch', 'Bitsearch'),
    ('piratebay', 'The Pirate Bay'),
    ('torrentio', 'Torrentio'),
    ('hianime', 'HiAnime'),
    ('animepahe', 'AnimePahe'),
    ('anikoto', 'Anikoto'),
    ('animekai', 'AnimeKai'),
    ('watchnixtoons2', 'WatchNixtoons2'),
    ('gogo', 'Gogoanime'),
    ('easynews', 'Easynews'),
]

_FILLER_CHOICES = [
    ('default', 'Global Default'),
    ('skip', 'Skip Filler & Recap'),
    ('skip_mixed', 'Skip All Including Mixed'),
    ('keep', 'Keep All Episodes'),
]

_FIELD_SPECS = [
    {
        'key': 'audio_lang',
        'title': 'Audio Language',
        'description': 'Preferred playback audio track for this series',
        'kind': 'choice',
        'choices': _AUDIO_CHOICES,
        'default': None,
    },
    {
        'key': 'sub_lang',
        'title': 'Subtitle Language',
        'description': 'Preferred subtitle language code for this series',
        'kind': 'choice',
        'choices': _SUB_LANG_CHOICES,
        'default': None,
    },
    {
        'key': 'sub_mode',
        'title': 'Subtitle Matching Mode',
        'description': 'Full dialogue, Signs & Songs, or dual Smart Pair filtering',
        'kind': 'choice',
        'choices': _SUB_MODE_CHOICES,
        'default': None,
    },
    {
        'key': 'preferred_provider',
        'title': 'Preferred Scraper / Provider',
        'description': 'Prioritize a release source within equal relevance tiers',
        'kind': 'choice',
        'choices': _PROVIDER_CHOICES,
        'default': None,
    },
    {
        'key': 'skip_filler_mode',
        'title': 'Filler Auto-Skip Mode',
        'description': 'Override binge playlist filler/recap skipping',
        'kind': 'choice',
        'choices': _FILLER_CHOICES,
        'default': 'default',
    },
    {
        'key': 'episode_offset',
        'title': 'Episode Offset (+/- Episodes)',
        'description': 'Manual cour / split-season episode offset (-24 to +24)',
        'kind': 'int',
        'min': -24,
        'max': 24,
        'step': 1,
        'unit': ' ep',
        'default': 0,
    },
    {
        'key': 'intro_offset_s',
        'title': 'Intro Skip Offset (+/- Seconds)',
        'description': 'Fine-tune AniSkip / Chapter OP skip bounds (-30s to +30s)',
        'kind': 'int',
        'min': -30,
        'max': 30,
        'step': 1,
        'unit': 's',
        'default': 0,
    },
    {
        'key': 'outro_offset_s',
        'title': 'Outro Skip Offset (+/- Seconds)',
        'description': 'Fine-tune AniSkip / Chapter ED skip bounds (-30s to +30s)',
        'kind': 'int',
        'min': -30,
        'max': 30,
        'step': 1,
        'unit': 's',
        'default': 0,
    },
    {
        'key': 'sub_offset_ms',
        'title': 'Subtitle Timing Offset (+/- ms)',
        'description': 'Per-series external subtitle timing shift (-15000ms to +15000ms)',
        'kind': 'int',
        'min': -15000,
        'max': 15000,
        'step': 250,
        'unit': 'ms',
        'default': 0,
    },
]


class SeriesProfileDialog(BaseWindow):
    """Interactive WindowXML dialog for editing per-series playback & timing profiles."""

    def __init__(self, xml_file, location, mal_id=None, actionArgs=None):
        super().__init__(xml_file, location, actionArgs=actionArgs)
        self.mal_id = str(mal_id or '')
        self.list_control = None
        self.selected_index = 0
        self.modified = False
        self._pending_reset = False
        self._win_closed = False
        self.show_title = f"MAL #{self.mal_id}" if self.mal_id else "Series Profile"
        self.poster_art = ''
        self.values = self._load_initial_values()

    def _default_values(self):
        return {spec['key']: spec['default'] for spec in _FIELD_SPECS}

    def _load_initial_values(self):
        vals = self._default_values()
        if not self.mal_id:
            return vals
        try:
            show_row = database.get_show(self.mal_id)
            if show_row and show_row.get('kodi_meta'):
                meta = database.loads(show_row['kodi_meta'])
                if isinstance(meta, dict):
                    self.show_title = str(meta.get('title_userPreferred') or meta.get('ename') or meta.get('name') or self.show_title)
            meta_row = database.get_show_meta(self.mal_id)
            if meta_row and meta_row.get('art'):
                art = database.loads(meta_row['art'])
                if isinstance(art, dict):
                    poster = art.get('poster') or art.get('thumb')
                    if isinstance(poster, list) and poster:
                        poster = poster[0]
                    self.poster_art = str(poster or '')
            if (self.show_title == f"MAL #{self.mal_id}" or not self.poster_art):
                mp = database.get_mappings(self.mal_id, 'mal_id')
                if isinstance(mp, dict):
                    if self.show_title == f"MAL #{self.mal_id}":
                        mp_title = mp.get('title_english') or mp.get('mal_title')
                        if mp_title:
                            self.show_title = str(mp_title).strip()
                    if not self.poster_art and mp.get('mal_picture'):
                        pic = str(mp.get('mal_picture') or '').strip()
                        if pic:
                            self.poster_art = pic if pic.startswith(('http://', 'https://')) else f"https://cdn.myanimelist.net/images/anime/{pic}"
            existing = database.get_series_override(self.mal_id)
            if isinstance(existing, dict):
                for spec in _FIELD_SPECS:
                    k = spec['key']
                    if spec['kind'] == 'int':
                        vals[k] = int(existing.get(k) or 0)
                    else:
                        raw_v = existing.get(k)
                        vals[k] = raw_v if raw_v is not None else spec['default']
        except Exception as e:
            control.log(f"SeriesProfileDialog load warning: {e}", level='debug')
        return vals

    def onInit(self):
        control.closeBusyDialog()
        self.setProperty('series_title', f"Series Playback Profile: {self.show_title}")
        self.setProperty('series_subtitle', f"MAL ID #{self.mal_id or '?'}  •  Customize per-show audio, subtitles, provider, and timing offsets")
        self.setProperty('series_poster', self.poster_art or str(getattr(control, 'OTAKU_ICON', '') or ''))
        self._update_preview_property()

        try:
            self.list_control = self.getControl(1000)
        except Exception as e:
            control.log(f"SeriesProfileDialog: Failed to acquire list control 1000: {e}", level='error')
            self.list_control = None

        self._populate_list(selected_idx=0)
        self.setFocusId(1000)

    def _build_preview_text(self):
        rules = database.get_tvdb_rules(self.mal_id) if self.mal_id else []
        filler = database.get_mapping_filler_map(self.mal_id) if self.mal_id else {}
        ep_off = int(self.values.get('episode_offset') or 0)
        in_off = int(self.values.get('intro_offset_s') or 0)
        out_off = int(self.values.get('outro_offset_s') or 0)
        sub_off = int(self.values.get('sub_offset_ms') or 0)
        ep1_mapped = max(1, 1 + ep_off)
        if ep_off < 0:
            src_ep = 1 - ep_off
            ep_line = f"Ep {src_ep} -> Mapped #{max(1, src_ep + ep_off)} ({ep_off:+d} ep)"
        else:
            ep_line = f"Ep 1 -> Mapped #{ep1_mapped} ({ep_off:+d} ep)"
        intro_demo = f"{max(0, 90 + in_off)}s - {max(1, 180 + in_off)}s"
        outro_demo = f"{max(0, 1290 + out_off)}s - {max(1, 1380 + out_off)}s"
        lines = [
            f"Cour Rules (mappings.db): {len(rules or [])}",
            f"Filler Tagged Episodes: {len(filler or {})}",
            ep_line,
            f"OP Example (90-180s): {intro_demo} ({in_off:+d}s)",
            f"ED Example (21:30-23:00): {outro_demo} ({out_off:+d}s)",
            f"Sub Offset: {sub_off:+d}ms",
        ]
        return "\n".join(lines)

    def _update_preview_property(self):
        self.setProperty('skip_preview', self._build_preview_text())

    def _format_value_badge(self, spec):
        val = self.values.get(spec['key'])
        if spec['kind'] == 'int':
            ival = int(val or 0)
            is_ovr = (ival != 0)
            sign_str = f"{ival:+d}{spec.get('unit', '')}" if is_ovr else "0 (Global Default)"
            return sign_str, is_ovr
        for code, lbl in spec['choices']:
            if code == val:
                is_ovr = (val != spec['default'])
                return lbl, is_ovr
        return str(val or 'Global Default'), bool(val != spec['default'])

    def _apply_listitem_props(self, li, spec):
        badge, is_ovr = self._format_value_badge(spec)
        li.setLabel(spec['title'])
        li.setProperty('value_badge', str(badge or ''))
        li.setProperty('is_overridden', 'true' if is_ovr else 'false')
        li.setProperty('description', str(spec['description'] or ''))
        li.setProperty('field_key', spec['key'])

    def _populate_list(self, selected_idx=0):
        if self.list_control is None:
            return
        try:
            existing_size = self.list_control.size()
        except Exception:
            existing_size = 0

        if existing_size == len(_FIELD_SPECS) and existing_size > 0:
            for idx, spec in enumerate(_FIELD_SPECS):
                li = self.list_control.getListItem(idx)
                if li is not None:
                    self._apply_listitem_props(li, spec)
        else:
            self.list_control.reset()
            for spec in _FIELD_SPECS:
                li = xbmcgui.ListItem(label=spec['title'])
                self._apply_listitem_props(li, spec)
                self.list_control.addItem(li)

        if _FIELD_SPECS:
            target = max(0, min(len(_FIELD_SPECS) - 1, selected_idx))
            self.selected_index = target
            self.list_control.selectItem(target)

    def _refresh_row_in_place(self, idx):
        self.modified = True
        self._pending_reset = False
        self._update_preview_property()
        if self.list_control is not None and 0 <= idx < len(_FIELD_SPECS):
            try:
                li = self.list_control.getListItem(idx)
                if li is not None:
                    self._apply_listitem_props(li, _FIELD_SPECS[idx])
            except Exception as e:
                control.log(f"SeriesProfileDialog in-place refresh warning: {e}", level='debug')

    def _get_current_index(self):
        if self.list_control is not None:
            try:
                pos = self.list_control.getSelectedPosition()
                if 0 <= pos < len(_FIELD_SPECS):
                    self.selected_index = pos
                    return pos
            except Exception:
                pass
        return getattr(self, 'selected_index', 0)

    def edit_field(self, idx=None):
        idx = self._get_current_index() if idx is None else idx
        if idx < 0 or idx >= len(_FIELD_SPECS):
            return
        spec = _FIELD_SPECS[idx]
        if spec['kind'] == 'choice':
            labels = [lbl for _code, lbl in spec['choices']]
            pick = control.select_dialog(spec['title'], labels)
            if pick >= 0:
                self.values[spec['key']] = spec['choices'][pick][0]
                self._refresh_row_in_place(idx)
        else:
            unit = spec.get('unit', '')
            cur_v = int(self.values.get(spec['key']) or 0)
            if spec['key'] == 'episode_offset':
                deltas = (-12, -5, -1, None, 1, 5, 12)
            elif spec['key'] == 'sub_offset_ms':
                deltas = (-5000, -1000, -250, None, 250, 1000, 5000)
            else:
                deltas = (-10, -5, -1, None, 1, 5, 10)
            step_opts = [
                "0 (Reset to Global Default)" if d is None else f"{d:+d}{unit}"
                for d in deltas
            ] + ["Enter Value..."]
            pick = control.select_dialog(f"{spec['title']} (Current: {cur_v:+d}{unit})", step_opts)
            if pick < 0 or pick >= len(step_opts):
                return
            if pick == len(step_opts) - 1:
                raw = control.input_dialog(spec['title'], str(cur_v))
                if raw is None or not str(raw).strip():
                    return
                try:
                    new_v = int(str(raw).strip())
                except ValueError:
                    return
            else:
                d_val = deltas[pick]
                new_v = 0 if d_val is None else (cur_v + d_val)
            self.values[spec['key']] = max(spec['min'], min(spec['max'], new_v))
            self._refresh_row_in_place(idx)

    def step_field(self, delta, idx=None):
        idx = self._get_current_index() if idx is None else idx
        if idx < 0 or idx >= len(_FIELD_SPECS):
            return
        spec = _FIELD_SPECS[idx]
        key = spec['key']
        if spec['kind'] == 'int':
            cur_v = int(self.values.get(key) or 0)
            new_v = max(spec['min'], min(spec['max'], cur_v + (int(delta) * spec.get('step', 1))))
            self.values[key] = new_v
        else:
            choices = [c[0] for c in spec['choices']]
            cur_v = self.values.get(key)
            cur_pos = choices.index(cur_v) if cur_v in choices else 0
            nxt_pos = (cur_pos + (1 if delta >= 0 else -1)) % len(choices)
            self.values[key] = choices[nxt_pos]
        self._refresh_row_in_place(idx)

    def reset_defaults(self):
        self.values = self._default_values()
        self.modified = True
        self._pending_reset = True
        self._update_preview_property()
        self._populate_list(selected_idx=self._get_current_index())
        control.notify(control.ADDON_NAME, "Staged reset to Global Defaults — Save to apply")

    def save_and_close(self):
        if self.mal_id:
            defaults = self._default_values()
            all_default = all(self.values.get(k) == defaults.get(k) for k in defaults)
            if self._pending_reset or all_default:
                database.delete_series_override(self.mal_id)
                control.notify(control.ADDON_NAME, f"Cleared Series Profile for MAL #{self.mal_id}")
            else:
                database.set_series_override(
                    self.mal_id,
                    audio_lang=self.values.get('audio_lang'),
                    sub_lang=self.values.get('sub_lang'),
                    sub_mode=self.values.get('sub_mode'),
                    preferred_provider=self.values.get('preferred_provider'),
                    intro_offset_s=int(self.values.get('intro_offset_s') or 0),
                    outro_offset_s=int(self.values.get('outro_offset_s') or 0),
                    episode_offset=int(self.values.get('episode_offset') or 0),
                    sub_offset_ms=int(self.values.get('sub_offset_ms') or 0),
                    skip_filler_mode=self.values.get('skip_filler_mode') or 'default',
                )
                control.notify(control.ADDON_NAME, f"Saved Series Profile for MAL #{self.mal_id}")
            database.clear_episode_sources(self.mal_id)
            database.clear_season_pack(self.mal_id)
        self._pending_reset = False
        self.close()

    def cancel_and_close(self):
        self._pending_reset = False
        self.close()

    def onClick(self, control_id):
        if control_id in (1000, 3001):
            self.edit_field()
        elif control_id == 3002:
            self.step_field(-1)
        elif control_id == 3003:
            self.step_field(1)
        elif control_id == 3004:
            self.reset_defaults()
        elif control_id == 3005:
            self.save_and_close()
        elif control_id == 3006:
            self.cancel_and_close()

    def onAction(self, action):
        action_id = action.getId() if hasattr(action, 'getId') else int(action)
        if action_id in (9, 10, 92, 110, 216):
            self.cancel_and_close()


def open_series_profile_dialog(mal_id):
    """Open interactive Series Profile WindowXML editor cleanly under try...finally."""
    dlg = None
    try:
        dlg = SeriesProfileDialog('series_profile.xml', control.ADDON_PATH, mal_id=mal_id)
        dlg.doModal()
    except Exception as e:
        control.log(f"SeriesProfileDialog error (MAL #{mal_id}): {e}", level='error')
    finally:
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass
            del dlg
