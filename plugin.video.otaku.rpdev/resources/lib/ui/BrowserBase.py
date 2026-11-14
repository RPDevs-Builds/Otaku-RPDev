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
        'doodstream', 'filelions', 'filemoon', 'hd-1', 'hd-2', 'hd-3', 'iga', 'kwik',
        'megacloud', 'megaf', 'moonf', 'mp4upload', 'mp4u', 'mycloud', 'noads',
        'noadsalt', 'swish', 'streamtape', 'streamwish', 't-cloud', 'vidcdn',
        'vidhide', 'vidplay', 'vidsrc', 'vidstream', 'yourupload', 'zto'
    )

    @staticmethod
    def handle_paging(hasnextpage, base_url, page):
        if not hasnextpage:
            return []
        if page <= 1 and not control.is_addon_visible() and control.getBool('widget.hide.nextpage'):
            return []

        next_page = page + 1
        name = "Next Page (%d)" % next_page
        next_url = re.sub(r'page=%d', f'page={next_page}', base_url)
        url_path, sep, query = next_url.partition('?')

        try:
            from resources.lib import Main
            plugin_path = getattr(Main, 'plugin_url', '')
            if plugin_path and plugin_path.startswith(url_path):
                url_path = plugin_path
        except (ImportError, AttributeError):
            pass

        next_url = url_path + (sep + query if query else '')
        return [utils.allocate_item(name, next_url, True, False, [], 'next.png', {'plot': name}, 'next.png')]

    @staticmethod
    def handle_filter(base_url, query=''):
        """Generate multipage action item ([Filter List by Text...] or [Clear Filter])."""
        if not control.getBool('multipage.show.filter.item'):
            return []

        base_clean = base_url.replace('%d', '1') if '%d' in base_url else base_url
        if query:
            name = f"[COLOR deepskyblue][Clear Filter: {query}][/COLOR]"
            url = f"multipage_clear_filter?base_url={urllib.parse.quote_plus(base_clean)}"
            plot = f"Clear active text filter: {query}"
        else:
            name = control.lang(30712) or "[Filter List by Text...]"
            url = f"multipage_filter?base_url={urllib.parse.quote_plus(base_clean)}"
            plot = control.lang(30714) or "Filter Anime by Title"

        return [utils.allocate_item(name, url, False, False, [], 'search.png', {'plot': plot})]

    def process_multipage_view(self, items, has_next, base_url, page, peek_fn=None, filter_text=None):
        """Assembles, pre-caches, filters, sorts, and slices items for browse views."""
        from resources.lib.ui import multipage

        if filter_text is None:
            try:
                import sys
                if len(sys.argv) > 2 and sys.argv[2]:
                    qs = urllib.parse.parse_qs(sys.argv[2].lstrip('?'))
                    filter_text = qs.get('filter_text', [''])[0] or qs.get('filter_query', [''])[0]
                else:
                    filter_text = ''
            except Exception:
                filter_text = ''

        mp_settings = multipage.get_multipage_settings()
        precache_pages = mp_settings['precache_pages']
        sort_by = mp_settings['sort_by']
        sort_order = mp_settings['sort_order']
        display_mode = mp_settings['display_mode']
        show_filter = mp_settings['show_filter_item']

        # Clean current page items from any stray action / pagination items
        window = [it for it in (items or []) if not multipage.is_next_page_item(it) and not multipage.is_action_item(it)]

        # Peek already cached subsequent pages if pre-caching is active (>1) and peek_fn provided
        if peek_fn and precache_pages > 1:
            for p in range(2, precache_pages + 1):
                if len(window) >= 1000:
                    break
                cached_items = peek_fn(p)
                if not cached_items:
                    break
                clean_cached = [it for it in cached_items if not multipage.is_next_page_item(it) and not multipage.is_action_item(it)]
                if not clean_cached:
                    break
                window = multipage.merge_window(window, clean_cached, max_items=1000)

        # Apply text filter
        if filter_text:
            window = multipage.filter_window_by_text(window, filter_text)

        # Apply cross-page sorting
        if sort_by != 0:
            window = multipage.sort_window(window, sort_by, sort_order)

        per_page = getattr(self, 'perpage', 20) or 20

        if display_mode == 1:
            # Mode 1: All Pre-Cached Items loaded into the container
            final_items = list(window)
            if show_filter:
                final_items = self.handle_filter(base_url, query=filter_text) + final_items
            return final_items

        else:
            # Mode 0: Paged mode
            if sort_by != 0 or filter_text or len(window) > per_page:
                sliced = multipage.slice_page(window, page=page, per_page=per_page)
                has_more = (page * per_page) < len(window) or has_next
                paging_items = self.handle_paging(has_more, base_url, page)
                final_items = list(sliced) + paging_items
            else:
                paging_items = self.handle_paging(has_next, base_url, page)
                final_items = list(window) + paging_items

            if show_filter:
                final_items = self.handle_filter(base_url, query=filter_text) + final_items

            return final_items

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
