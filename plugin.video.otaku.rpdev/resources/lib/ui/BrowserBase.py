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
