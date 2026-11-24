"""BrowserBase.py - Scraper Base Class
======================================
Common utilities shared by all page/scraper modules:
pagination, URL construction, HTTP helpers, and encoding.
"""

# -*- coding: utf-8 -*-
import base64
import re
import urllib.parse

from resources.lib.ui import client, control, utils


# ═══════════════════════════════════════════════════════════════════════════
#  BrowserBase - Paging, URL Helpers & HTTP Wrappers
# ═══════════════════════════════════════════════════════════════════════════

class BrowserBase(object):
    _BASE_URL = None

    # Full embed host list applied on metadata schema bumps only
    # (see ``database_sync.SyncDatabase.check_database_version``).
    EMBED_SERVERS_DEFAULT = (
        'ayame', 'doodstream', 'filelions', 'filemoon', 'hd-1', 'hd-2', 'hd-3', 'iga', 'kwik',
        'megacloud', 'megaf', 'moonf', 'mp4upload', 'mp4u', 'mycloud', 'noads',
        'noadsalt', 'ryu', 'swish', 'streamtape', 'streamwish', 't-cloud', 'vidcdn',
        'vidhide', 'vidplay', 'vidsrc', 'vidstream', 'volt', 'yourupload', 'zto'
    )

    @staticmethod
    def handle_paging(hasnextpage, base_url, page):
        if not hasnextpage:
            return []
        if page <= 1 and not control.is_addon_visible() and control.getBool('widget.hide.nextpage'):
            return []

        next_page = page + 1
        name = "Next Page (%d)" % next_page

        url_parts = urllib.parse.urlsplit(base_url)
        path = url_parts.path
        query_dict = dict(urllib.parse.parse_qsl(url_parts.query))
        query_dict['page'] = str(next_page)
        new_query = urllib.parse.urlencode(query_dict)
        next_url = f"{path}?{new_query}" if path else f"?{new_query}"
        return [utils.allocate_item(name, next_url, True, False, [], 'next.png', {'plot': name}, 'next.png')]

    @staticmethod
    def handle_filter(base_url, query=''):
        return []

    def process_multipage_view(self, items, has_next, base_url, page, peek_fn=None, filter_text=None):
        """Assembles and slices items for browse views with robust pagination."""
        from resources.lib.ui import multipage

        # Clean current page items from any stray action / pagination items
        window = [it for it in (items or []) if not multipage.is_next_page_item(it) and not multipage.is_action_item(it)]

        if filter_text:
            window = multipage.filter_window_by_text(window, filter_text)

        per_page = getattr(self, 'perpage', 20) or 20

        if len(window) > per_page:
            sliced = multipage.slice_page(window, page=page, per_page=per_page)
            has_more = (page * per_page) < len(window) or has_next
            paging_items = self.handle_paging(has_more, base_url, page)
            return list(sliced) + paging_items
        else:
            paging_items = self.handle_paging(has_next, base_url, page)
            return list(window) + paging_items

    @staticmethod
    def open_completed():
        import json
        try:
            with open(control.completed_json) as file:
                completed = json.load(file)
        except FileNotFoundError:
            completed = {}
        return completed

    @staticmethod
    def duration_to_seconds(duration_str):
        # Regular expressions to match hours, minutes, and seconds
        hours_pattern = re.compile(r'(\d+)\s*hr')
        minutes_pattern = re.compile(r'(\d+)\s*min')
        seconds_pattern = re.compile(r'(\d+)\s*sec')

        # Extract hours, minutes, and seconds
        hours_match = hours_pattern.search(duration_str)
        minutes_match = minutes_pattern.search(duration_str)
        seconds_match = seconds_pattern.search(duration_str)

        # Convert to integers, default to 0 if not found
        hours = int(hours_match.group(1)) if hours_match else 0
        minutes = int(minutes_match.group(1)) if minutes_match else 0
        seconds = int(seconds_match.group(1)) if seconds_match else 0

        # Calculate total duration in seconds
        total_seconds = hours * 3600 + minutes * 60 + seconds

        return total_seconds

    @staticmethod
    def _clean_title(text):
        return text.replace(u'×', ' x ')

    @staticmethod
    def clean_embed_title(text):
        return re.sub(r'\W', '', text).lower()

    @staticmethod
    def _collect_title_aliases(mal_id=None, kodi_meta=None, limit=6):
        """Return deduplicated metadata & mappings.db anime_aliases for scraper search and scoring."""
        aliases = []
        seen = set()

        def _add(val):
            s = str(val or '').strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                aliases.append(s)

        if isinstance(kodi_meta, dict):
            for key in ('ename', 'title_english', 'title_romaji'):
                _add(kodi_meta.get(key))

        if mal_id:
            try:
                from resources.lib.ui import database
                for alias in (database.get_mapping_aliases(mal_id, limit=limit) or []):
                    _add(alias)
            except Exception:
                pass
        return aliases

    @staticmethod
    def _resolve_target_year(mal_id=None, kodi_meta=None, current_year=None):
        """Resolve integer/string release year from caller arg, kodi_meta, or mappings.db fallback."""
        if current_year:
            return current_year
        if isinstance(kodi_meta, dict):
            yr = kodi_meta.get('year') or kodi_meta.get('aired_year')
            if yr:
                return yr
            sdate = str(kodi_meta.get('start_date') or '')
            if len(sdate) >= 4 and sdate[:4].isdigit():
                return sdate[:4]
        if mal_id:
            try:
                from resources.lib.ui import database
                mp = database.resolve_mappings_with_fallback(
                    mal_id, required_keys=('year', 'start_date'), require_all=False, fetch_remote=False
                )
                if isinstance(mp, dict):
                    if mp.get('year'):
                        return str(mp['year'])
                    sd = str(mp.get('start_date') or '')
                    if len(sd) >= 4 and sd[:4].isdigit():
                        return sd[:4]
            except Exception:
                pass
        return None

    @staticmethod
    def _merge_offline_metadata_into_kodi_meta(mal_id, kodi_meta):
        """Fill missing kodi_meta fields from anime_metadata.db / mappings.db respecting titlelanguage."""
        out = dict(kodi_meta or {})
        if not mal_id:
            return out
        try:
            from resources.lib.ui import database
            offline = database.get_offline_anime_metadata(mal_id) or {}
        except Exception:
            offline = {}
        if not offline:
            return out

        name = out.get('name') or offline.get('mal_title')
        ename = out.get('ename') or offline.get('title_english')
        prefer_en = control.getInt('titlelanguage') == 1
        pref_title = (ename or name) if prefer_en else (name or ename)

        out['name'] = name
        out['ename'] = ename
        out['title_userPreferred'] = out.get('title_userPreferred') or pref_title
        if not out.get('query'):
            out['query'] = f"({name})|({ename})" if (name and ename) else (f"({name})" if name else (f"({ename})" if ename else ''))
        out['start_date'] = out.get('start_date') or offline.get('start_date')
        if out.get('episodes') is None and offline.get('episodes') is not None:
            out['episodes'] = offline.get('episodes')
        out['poster'] = out.get('poster') or offline.get('mal_picture')
        out['status'] = out.get('status') or offline.get('status')
        out['format'] = out.get('format') or offline.get('anime_media_type') or ''
        out['plot'] = out.get('plot') or offline.get('synopsis')
        out['duration'] = out.get('duration') or offline.get('duration')
        if not out.get('genre') and offline.get('genres'):
            out['genre'] = [g.strip() for g in str(offline['genres']).split(',') if g.strip()]
        if not out.get('studio') and offline.get('studios'):
            out['studio'] = [s.strip() for s in str(offline['studios']).split(',') if s.strip()]
        out['mpaa'] = out.get('mpaa') or offline.get('age_rating')
        if not out.get('country') and offline.get('country_of_origin'):
            out['country'] = [str(offline['country_of_origin']).strip()]
        if not out.get('banner') and offline.get('banner_image'):
            out['banner'] = offline['banner_image']
        if not out.get('premiered') and offline.get('start_date'):
            out['premiered'] = str(offline['start_date'])[:10]
        if not out.get('year') and offline.get('year'):
            try:
                out['year'] = int(offline['year'])
            except (TypeError, ValueError):
                pass
        if not out.get('rating') and offline.get('score'):
            try:
                out['rating'] = {'score': float(offline['score'])}
            except (TypeError, ValueError):
                pass
        if not out.get('trailer') and offline.get('trailer_yt_id'):
            out['trailer'] = f"plugin://plugin.video.youtube/play/?video_id={offline['trailer_yt_id']}"
        return out

    def _to_url(self, url=''):
        assert self._BASE_URL is not None, "Must be set on inherentance"

        if url.startswith("/"):
            url = url[1:]
        return "%s/%s" % (self._BASE_URL, url)

    @staticmethod
    def _send_request(url, data=None, headers=None):
        if data:
            response = client.post(url, data=data, headers=headers)
        else:
            response = client.get(url, headers=headers)
        return response.text if response else None

    def _post_request(self, url, data=None, headers=None):
        if data is None:
            data = {}
        return self._send_request(url, data, headers)

    def _get_request(self, url, data=None, headers=None):
        if data:
            url = "%s?%s" % (url, urllib.parse.urlencode(data))
        return self._send_request(url, data=None, headers=headers)

    @staticmethod
    def _get_redirect_url(url, headers=None):
        if headers is None:
            headers = {}
        response = client.get(url, redirect=False, headers=headers)
        if response:
            return response.headers.get('Location')
        return ''

    @staticmethod
    def _bencode(text):
        return (base64.b64encode(control.bin(text))).decode('latin-1')

    @staticmethod
    def _bdecode(text, binary=False):
        dec = base64.b64decode(text)
        return dec if binary else dec.decode('latin-1')

    @staticmethod
    def _get_origin(url):
        purl = urllib.parse.urlparse(url)
        return '{0}://{1}'.format(purl.scheme, purl.netloc)

    @staticmethod
    def _get_size(size=0):
        power = 1024.0
        n = 0
        power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB'}
        while size > power:
            size /= power
            n += 1
        return '{0:.2f} {1}'.format(size, power_labels[n])

    @staticmethod
    def _sphinx_clean(text):
        text = text.replace('+', r'\+')
        text = text.replace('-', r'\-')
        text = text.replace('!', r'\!')
        text = text.replace('^', r'\^')
        text = text.replace('"', r'\"')
        text = text.replace('~', r'\~')
        text = text.replace('*', r'\*')
        text = text.replace('?', r'\?')
        text = text.replace(':', r'\:')
        return text

    @staticmethod
    def embeds():
        return control.getStringList('embed.config')

    @staticmethod
    def _plugin_page_url(prefix, route_slug):
        return f"{prefix}?page=%d" if prefix else f"{route_slug}?page=%d"

    @staticmethod
    def attach_genre_methods(cls, presets):
        for slug, preset_val in presets:
            def make_genre(_slug, _val):
                def method(self, page, format, prefix=None, filter_text=None):
                    return self._browse_genre_preset(page, format, prefix, f'genre_{_slug}', _val, filter_text=filter_text)
                method.__name__ = f'get_genre_{_slug}'
                method.__doc__ = f'Browse anime with genre preset {_slug} ({_val}).'
                return method
            setattr(cls, f'get_genre_{slug}', make_genre(slug, preset_val))
