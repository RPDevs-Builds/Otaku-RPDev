import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup, SoupStrainer
from resources.lib.ui import database, source_utils, control, domains
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.endpoints import malsync
from resources.lib.ui import client

_ANIME_SESSION_PATH_RE = re.compile(r'/anime/([^/?#]+)', re.I)


class Sources(BrowserBase):
    _BASE_URL = domains.get_domain('animepahe', 'https://animepahe.pw/')

    _headers = {
        'Referer': _BASE_URL,
    }

    @staticmethod
    def _normalize_title(text):
        if not text:
            return ''
        return (
            text.replace('’', "'")
            .replace('‘', "'")
            .replace('‚', "'")
            .replace('‛', "'")
            .replace('´', "'")
            .replace('′', "'")
            .replace('“', '"')
            .replace('”', '"')
            .replace('„', '"')
            .replace('‟', '"')
            .replace('—', '-')
            .replace('–', '-')
            .strip()
        )

    def _get_base_url(self):
        """Resolve active AnimePahe base URL dynamically (respects live provider.animepahealt toggles)."""
        return domains.get_domain('animepahe', self._BASE_URL) or self._BASE_URL

    def _get_headers(self, base_url=None):
        return {'Referer': base_url or self._get_base_url()}

    def _rewrite_origin(self, raw_url, base_url=None):
        """Rewrite legacy MALSync AnimePahe URLs dynamically onto the active mirror origin."""
        target_base = base_url or self._get_base_url()
        parsed_base = urllib.parse.urlparse(target_base)
        parsed_link = urllib.parse.urlparse(raw_url)
        if parsed_base.scheme and parsed_base.netloc and parsed_link.path:
            base_qs = urllib.parse.parse_qsl(parsed_base.query, keep_blank_values=True)
            link_qs = urllib.parse.parse_qsl(parsed_link.query, keep_blank_values=True)
            merged_q = urllib.parse.urlencode(base_qs + link_qs)
            return urllib.parse.urlunparse((
                parsed_base.scheme,
                parsed_base.netloc,
                parsed_link.path,
                parsed_link.params,
                merged_q,
                parsed_link.fragment,
            ))
        return raw_url

    def _build_source(self, item, title, episode, embed_hosts):
        raw_src = item.get('data-src') or ''
        if not raw_src:
            return None
        audio = (item.get('data-audio') or '').lower()
        pref_source = control.getInt('general.source')
        if pref_source == 1 and audio == 'eng':
            return None
        if pref_source == 2 and audio != 'eng':
            return None
        data_src = raw_src + f'|Referer={self._BASE_URL}'
        if not any(host in data_src.lower() for host in embed_hosts):
            return None

        try:
            qual = int(item.get('data-resolution') or 0)
        except (ValueError, TypeError):
            qual = 0
        if qual <= 0:
            quality = 0
        elif qual <= 577:
            quality = 1
        elif qual <= 721:
            quality = 2
        elif qual <= 1081:
            quality = 3
        else:
            quality = 4

        return {
            'release_title': '{0} - Ep {1}'.format(title, episode),
            'hash': data_src,
            'type': 'embed',
            'quality': quality,
            'debrid_provider': '',
            'provider': 'animepahe',
            'size': 'NA',
            'seeders': 0,
            'byte_size': 0,
            'info': [source_utils.get_embedhost(data_src) + (' DUB' if audio == 'eng' else ' SUB')],
            'lang': 3 if audio == 'eng' else 2,
            'channel': 3,
            'sub': 1
        }

    @staticmethod
    def _session_slug_from_animepahe_url(page_url):
        """Extract API session id from a canonical AnimePahe page URL (/anime/{session})."""
        if not page_url:
            return None
        match = _ANIME_SESSION_PATH_RE.search(urllib.parse.urlparse(page_url).path)
        return match.group(1) if match else None

    def _resolve_session_from_malsync(self, mal_id):
        """
        MAL Sync stores legacy links like https://animepahe.com/a/6231; the live site
        redirects to https://animepahe.pw/anime/{uuid}. Follow redirects and return that
        session slug for the API (m=release&id=...).
        """
        for raw in malsync.get_slugs(mal_id, site='animepahe'):
            if not raw:
                continue
            link = raw.strip()
            if link.startswith('//'):
                link = 'https:' + link
            elif link.startswith('/'):
                link = urllib.parse.urljoin(self._BASE_URL, link)
            final = client.request(
                self._rewrite_origin(link),
                output='geturl',
                headers=self._headers,
                referer=self._BASE_URL,
            )
            slug = self._session_slug_from_animepahe_url(final)
            if slug:
                return slug
        return None

    def _collect_search_titles(self, mal_id):
        """Return deduplicated AnimePahe search queries from MALSync, local show meta, and mappings.db."""
        titles = []
        seen = set()

        def _add(val):
            s = str(val or '').strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                titles.append(s)

        _add(malsync.get_title(mal_id, site='animepahe'))
        show = database.get_show(mal_id)
        kodi_meta = database.loads(show.get('kodi_meta')) if isinstance(show, dict) and show.get('kodi_meta') else None
        if isinstance(kodi_meta, dict):
            for key in ('name', 'ename', 'title_english', 'title_romaji'):
                _add(kodi_meta.get(key))
        for alias in self._collect_title_aliases(mal_id=mal_id, kodi_meta=kodi_meta, limit=6):
            _add(alias)
        return titles, kodi_meta

    def _query_search_api(self, api_url, headers, query_title):
        """Query AnimePahe search API and return (sitems, had_valid_json)."""
        r = database.get(
            self._get_request,
            8,
            api_url,
            data={'m': 'search', 'q': query_title},
            headers=headers,
        )
        if not r:
            return None, False
        parsed_r = control.loads_json(r, None)
        if not isinstance(parsed_r, dict):
            return None, False
        return parsed_r.get('data') or [], True

    def get_sources(self, mal_id, episode):
        base_url = self._get_base_url()
        headers = self._get_headers(base_url)

        if not domains.is_mirror_healthy(base_url):
            control.log('AnimePahe: cooling down after recent failure; skipping scrape', level='info')
            return []

        search_titles, kodi_meta = self._collect_search_titles(mal_id)
        if not search_titles:
            control.log('AnimePahe: no mapped title or alias for mal_id={0}'.format(mal_id), level='info')
            return []

        title = search_titles[0]
        control.log('AnimePahe: scraping mal_id={0} ep={1} title="{2}"'.format(mal_id, episode, title), level='info')
        slug = self._resolve_session_from_malsync(mal_id)
        if slug:
            control.log('AnimePahe: resolved session slug from MAL sync: {0}'.format(slug), level='info')
            direct = self._process_ap(slug, title=title, episode=episode)
            if direct:
                control.log('AnimePahe: found {0} source(s) via MAL sync slug'.format(len(direct)), level='info')
                return direct

        api_url = domains.join_url(base_url, 'api')
        sitems, valid_json = self._query_search_api(api_url, headers, title)
        if not valid_json:
            domains.mark_mirror_failure(base_url, cooldown=3600)
            control.log('AnimePahe: search API returned no or invalid JSON data', level='info')
            return []

        query_queue = []
        if not sitems and ':' in title:
            query_queue.append(title.split(':')[0].strip())
        for alt in search_titles[1:]:
            if alt not in query_queue:
                query_queue.append(alt)

        for alt_query in query_queue[:3]:
            if sitems:
                break
            alt_items, alt_ok = self._query_search_api(api_url, headers, alt_query)
            if alt_ok and alt_items:
                sitems = alt_items
                title = alt_query
                break

        target_year = self._resolve_target_year(mal_id=mal_id, kodi_meta=kodi_meta)
        all_results = []
        if sitems:
            scored_candidates = []
            for item in sitems:
                cand_title = item.get('title')
                cand_year = item.get('year')
                cand_score = source_utils.score_title_candidate(
                    title, cand_title, aliases=search_titles
                )
                year_bonus = 1 if (target_year and cand_year and str(cand_year) == str(target_year)) else 0
                scored_candidates.append((item, cand_score, year_bonus))

            scored_candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

            if scored_candidates and scored_candidates[0][1] >= 50:
                best_item, best_score, _ = scored_candidates[0]
                slug = best_item.get('session')
                control.log(f"AnimePahe: Selected '{best_item.get('title')}' (Score: {best_score})", level='info')
                all_results = self._process_ap(slug, title=title, episode=episode)
            else:
                control.log(f"AnimePahe: No candidates scored >= 50 for '{title}'", level='info')
        control.log('AnimePahe: returning {0} source(s)'.format(len(all_results)), level='info')
        return all_results

    def _process_ap(self, slug, title, episode):
        sources = []
        try:
            e_num = int(episode)
        except (ValueError, TypeError):
            e_num = 1
        big_series = e_num > 30
        page = max(1, 1 + ((e_num - 1) // 30))

        base_url = self._get_base_url()
        headers = self._get_headers(base_url)
        api_url = domains.join_url(base_url, 'api')

        params = {
            'm': 'release',
            'id': slug,
            'sort': 'episode_asc',
            'page': page
        }
        r = database.get(
            self._get_request,
            8,
            api_url,
            data=params,
            headers=headers
        )
        if not r:
            domains.mark_mirror_failure(base_url, cooldown=3600)
            control.log('AnimePahe: release API returned no data for slug={0} page={1}'.format(slug, page), level='info')
            return sources
        r = control.loads_json(r, {})
        if not isinstance(r, dict):
            domains.mark_mirror_failure(base_url, cooldown=3600)
            control.log('AnimePahe: release API returned invalid JSON for slug={0}'.format(slug), level='info')
            return sources
        items = r.get('data') or []
        if not items:
            control.log('AnimePahe: no episodes on release page {0} for slug={1}'.format(page, slug), level='info')
            return sources
        items = sorted(items, key=lambda x: x.get('episode'))

        if items[0].get('episode') > 1 and not big_series:
            e_num = e_num + items[0].get('episode') - 1

        items = [x for x in items if x.get('episode') == e_num]
        if not items:
            control.log('AnimePahe: episode {0} not found for slug={1}'.format(e_num, slug), level='info')
            return sources

        eurl = domains.join_url(base_url, f"play/{slug}/{items[0].get('session')}")
        html = self._get_request(eurl, headers=headers)
        if not html:
            control.log('AnimePahe: empty play page for {0}'.format(eurl), level='warning')
            return sources
        mlink = SoupStrainer('div', {'id': 'resolutionMenu'})
        mdiv = BeautifulSoup(html, "html.parser", parse_only=mlink)
        items = mdiv.find_all('button')
        control.log('AnimePahe: found {0} embed button(s) on play page'.format(len(items)), level='info')
        embed_hosts = self.embeds()
        max_workers = max(1, min(control.max_threads or 1, len(items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            parsed = list(executor.map(lambda item: self._build_source(item, title, episode, embed_hosts), items))
        sources.extend([item for item in parsed if item is not None])

        return sources
