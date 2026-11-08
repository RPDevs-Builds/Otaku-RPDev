import itertools
import re
import urllib.parse
from functools import partial
from bs4 import BeautifulSoup

from resources.lib.endpoints import malsync
from resources.lib.ui import control, client, database, source_utils, utils, domains
from resources.lib.ui.BrowserBase import BrowserBase


def get_backup(mal_id, source):
    try:
        slugs = malsync.get_slugs(mal_id, site='Gogoanime')
        if slugs:
            return {s.split('/')[-1]: s for s in slugs if s}
    except Exception as e:
        control.log(f"GogoAnime: MALSync backup lookup failed: {e}", 'warning')
    return {}


class Sources(BrowserBase):
    _BASE_URL = 'https://anitaku.bz/' if control.getBool('provider.gogoalt') else domains.get_domain('gogoanime', 'https://gogoanime.me/')
    if not _BASE_URL.endswith('/'):
        _BASE_URL += '/'

    def _normalize_title_text(self, text):
        if not text:
            return ''
        return (
            text.replace('’', "'")
            .replace('‘', "'")
            .replace('`', "'")
            .replace('´', "'")
            .replace('ʻ', "'")
            .replace('ʼ', "'")
            .replace('′', "'")
            .replace('“', '"')
            .replace('”', '"')
            .replace('„', '"')
            .replace('‟', '"')
            .replace('—', '-')
            .replace('–', '-')
            .strip()
        )

    def _search_keywords(self, title, kodi_meta=None):
        keywords = []
        seen = set()

        def add(value):
            value = (value or '').strip()
            if not value:
                return
            key = value.lower()
            if key not in seen:
                seen.add(key)
                keywords.append(value)
            norm_val = self._normalize_title_text(value)
            norm_key = norm_val.lower()
            if norm_key not in seen:
                seen.add(norm_key)
                keywords.append(norm_val)

        add(title)
        if kodi_meta and isinstance(kodi_meta, dict):
            add(kodi_meta.get('ename'))
            add(kodi_meta.get('title_english'))
            add(kodi_meta.get('title_romaji'))

        if ':' in title:
            add(title.split(':', 1)[0].strip())
            add(title.split(':', 1)[1].strip())

        return keywords

    def _score_candidate(self, candidate_name=None, title='', current_year=None, kodi_meta=None, name=None):
        if candidate_name is None and name is not None:
            candidate_name = name
        if not candidate_name or not title:
            return 0

        if isinstance(current_year, dict):
            kodi_meta = current_year
            current_year = kodi_meta.get('year') or kodi_meta.get('aired_year')

        aliases = []
        if kodi_meta and isinstance(kodi_meta, dict):
            for key in ('ename', 'title_english', 'title_romaji'):
                val_raw = kodi_meta.get(key)
                if val_raw and val_raw not in aliases:
                    aliases.append(val_raw)
            if not current_year:
                current_year = kodi_meta.get('year') or kodi_meta.get('aired_year')

        return source_utils.score_title_candidate(title, candidate_name, aliases=aliases or None, year=current_year)

    def get_sources(self, mal_id, episode):
        show = database.get_show(mal_id)
        if not show:
            control.log(f"Gogoanime: Show not found in local DB for MAL ID {mal_id}", 'warning')
            return []
        kodi_meta = database.loads(show.get('kodi_meta'))
        raw_title = kodi_meta.get('name') if kodi_meta else ''
        title = self._clean_title(raw_title)
        if not title:
            return []

        base_url = 'https://anitaku.bz/' if control.getBool('provider.gogoalt') else domains.get_domain('gogoanime', 'https://gogoanime.me/')
        if not base_url.endswith('/'):
            base_url += '/'
        self._BASE_URL = base_url

        keywords = self._search_keywords(title, kodi_meta)
        candidates = {}
        headers = {'Referer': self._BASE_URL, 'User-Agent': client.randomagent()}

        for keyword in keywords:
            search_url = f"{self._BASE_URL}search.html?keyword={urllib.parse.quote_plus(keyword)}"
            r = database.get(
                self._send_request,
                8,
                search_url,
                headers=headers
            )
            if not r:
                continue

            soup = BeautifulSoup(r, 'html.parser')
            # 1. Native search results: <p class="name"><a href="/category/...">
            for p_tag in soup.find_all('p', class_='name'):
                a_tag = p_tag.find('a')
                if a_tag and a_tag.get('href'):
                    href = a_tag.get('href').strip()
                    slug = href.split('/')[-1].strip()
                    cand_name = a_tag.get('title') or a_tag.text.strip()
                    if slug and slug not in candidates:
                        candidates[slug] = cand_name

            # 2. Image-based links in .items: <div class="img"><a href="/category/...">
            for img_div in soup.find_all('div', class_='img'):
                a_tag = img_div.find('a')
                if a_tag and a_tag.get('href'):
                    href = a_tag.get('href').strip()
                    slug = href.split('/')[-1].strip()
                    cand_name = a_tag.get('title') or a_tag.text.strip()
                    if slug and slug not in candidates:
                        candidates[slug] = cand_name

            # 3. Legacy ajax format fallback: <div class="list_search_ajax">
            for item in soup.find_all('div', class_='list_search_ajax'):
                a_tag = item.find('a')
                if a_tag and a_tag.get('href'):
                    href = a_tag.get('href').strip()
                    slug = href.split('/')[-1].strip()
                    cand_name = a_tag.text.strip()
                    if slug and slug not in candidates:
                        candidates[slug] = cand_name

            if candidates:
                break

        # Filter candidates based on user sub/dub preferences
        # 0 = All (default), 1 = Sub only, 2 = Dub only
        source_pref = control.getInt('general.source')
        scored_slugs = []

        for slug, cand_name in candidates.items():
            is_dub = '-dub' in slug.lower() or '(dub)' in cand_name.lower()
            if source_pref == 1 and is_dub:
                continue
            if source_pref == 2 and not is_dub:
                continue

            score = self._score_candidate(cand_name, title, kodi_meta=kodi_meta)
            if score >= 50:
                scored_slugs.append((slug, score))

        if scored_slugs:
            max_score = max(s[1] for s in scored_slugs)
            cutoff = max(50, max_score - 30)
            slugs = [item[0] for item in sorted(scored_slugs, key=lambda x: x[1], reverse=True) if item[1] >= cutoff]
        else:
            slugs = database.get(get_backup, 168, mal_id, 'Gogoanime')
            if not slugs:
                return []
            slugs = list(slugs.keys()) if isinstance(slugs, dict) else slugs

        control.log(f"GogoAnime: Processing {len(slugs)} slugs in parallel")
        mapfunc = partial(self._process_gogo, show_id=mal_id, episode=episode)
        all_results = utils.parallel_process(slugs, mapfunc)
        all_results = list(itertools.chain(*all_results))
        return all_results

    def _process_gogo(self, slug, show_id, episode):
        if slug.startswith('http'):
            slug = slug.split('/')[-1]
        lang = 'dub' if '-dub' in slug.lower() else 'sub'
        url = f"{self._BASE_URL}{slug}-episode-{episode}"
        headers = {'Referer': self._BASE_URL, 'User-Agent': client.randomagent()}
        title = (slug.replace('-', ' ')).title() + f" - Ep {episode}"
        r = database.get(
            self._send_request,
            8,
            url,
            headers=headers
        )

        # Fallback to category page if direct episode URL 404s or has no servers
        if not r or 'anime_muti_link' not in r:
            cat_url = f"{self._BASE_URL}category/{slug}"
            html = database.get(
                self._send_request,
                8,
                cat_url,
                headers=headers
            )
            if html:
                cat_soup = BeautifulSoup(html, 'html.parser')
                # Check embedded episode items in #episode-items
                ep_items = cat_soup.find(id='episode-items') or cat_soup.find(id='episode_related')
                target_a = None
                if ep_items:
                    for a_tag in ep_items.find_all('a'):
                        href = a_tag.get('href', '').strip()
                        txt = a_tag.text.strip().lower()
                        if href.endswith(f"-episode-{episode}") or txt == f"ep {episode}" or txt == f"ep. {episode}":
                            target_a = a_tag
                            break

                if target_a and target_a.get('href'):
                    eslug = target_a.get('href').strip()
                    if not eslug.startswith('http'):
                        resolved_url = f"{self._BASE_URL.rstrip('/')}/{eslug.lstrip('/')}"
                    else:
                        resolved_url = eslug
                    r = self._send_request(resolved_url, headers=headers)

        if not r:
            return []

        soup = BeautifulSoup(r, 'html.parser')
        sources = []
        multi_link = soup.find(class_='anime_muti_link')
        ul_tag = multi_link.find('ul', recursive=False) if multi_link else None
        elements = ul_tag.find_all('li', recursive=False) if ul_tag else []
        control.log(f"GogoAnime: Found {len(elements)} servers for episode {episode}")

        enabled_embeds = self.embeds() or []

        for element in elements:
            classes = element.get('class', [])
            raw_server = classes[0] if classes else ''
            a_tag = element.find('a')
            if not a_tag:
                continue
            link = a_tag.get('data-video', '').strip()
            server_text = a_tag.text.strip().lower()
            server_lower = raw_server.lower()

            # Canonical server mapping for GogoAnime embed naming variants
            if server_lower == 'anime' or 'vidstreaming' in server_text:
                norm_server = 'vidcdn'
            elif 'streamwish' in server_lower or 'streamwish' in server_text:
                norm_server = 'streamwish'
            elif 'mp4upload' in server_lower or 'mp4upload' in server_text:
                norm_server = 'mp4upload'
            elif 'doodstream' in server_lower or 'dood' in server_text:
                norm_server = 'doodstream'
            elif 'filemoon' in server_lower or 'filemoon' in server_text:
                norm_server = 'filemoon'
            else:
                norm_server = server_lower

            if norm_server in enabled_embeds or server_lower in enabled_embeds:
                if link.startswith('//'):
                    link = 'https:' + link

                display_server = raw_server.upper() if (server_lower in enabled_embeds and server_lower != 'anime') else norm_server.upper()

                source = {
                    'release_title': title,
                    'hash': link,
                    'type': 'embed',
                    'quality': 0,
                    'debrid_provider': '',
                    'provider': 'gogo',
                    'size': 'NA',
                    'seeders': 0,
                    'byte_size': 0,
                    'info': [f"{display_server} {lang.upper()}"],
                    'lang': 3 if lang == 'dub' else 2,
                    'channel': source_utils.getAudio_channel(title),
                    'sub': source_utils.getSubtitle_lang(title),
                }
                sources.append(source)
                control.log(f"GogoAnime: Found source from server '{display_server}' ({norm_server})")

        return sources
