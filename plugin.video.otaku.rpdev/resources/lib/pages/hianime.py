import base64
import json
import re
import urllib.parse

from bs4 import BeautifulSoup
from resources.lib.endpoints import malsync
from resources.lib.ui import client, control, database, domains, utils
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.ui.megaplay_extractor import extract_megaplay_sources


class Sources(BrowserBase):
    _MEGAPLAY_S2 = 'https://megaplay.buzz/stream/s-2/{0}/{1}'
    _MEGAPLAY_ANI = 'https://megaplay.buzz/stream/ani/{0}/{1}/{2}'
    _MEGAPLAY_MAL = 'https://megaplay.buzz/stream/mal/{0}/{1}/{2}'
    _PROXY_VOLT = 'https://megacloud.animanga.fun'
    _PROXY_AYAME = 'https://upcloud.animanga.fun'
    _MEGAPLAY_REF = 'https://megaplay.buzz/'
    _VIDNEST_REF = 'https://vidnest.fun/'

    _SERVER_NAMES = ('ryu', 'volt', 'ayame')

    def get_sources(self, mal_id, episode):
        control.log(f"HiAnime: Getting sources for MAL ID {mal_id}, Episode {episode}")
        show = database.get_show(mal_id)
        if not show:
            return []

        kodi_meta = database.loads(show.get('kodi_meta'))
        title = self._clean_title(kodi_meta.get('name') or '')

        try:
            ep_num = int(episode)
        except (TypeError, ValueError):
            control.log(f"HiAnime: Invalid episode number: {episode}")
            return []

        langs = ['sub', 'dub']
        if control.getInt('general.source') == 1:
            langs.remove('dub')
        elif control.getInt('general.source') == 2:
            langs.remove('sub')

        enabled = self._enabled_servers()
        if not enabled:
            control.log("HiAnime: No embed servers enabled (ryu/volt/ayame)")
            return []

        mirrors = domains.get_healthy_mirrors('hianime')
        sources = []
        all_failed = True
        failed_count = 0

        for mirror in mirrors:
            try:
                sources = self._scrape_mirror(mirror, title, kodi_meta, mal_id, ep_num, langs, enabled)
                all_failed = False
                if sources:
                    control.log(f"HiAnime: Successfully extracted {len(sources)} source(s) from mirror {mirror}", 'info')
                    return sources
            except Exception as e:
                failed_count += 1
                domains.mark_mirror_failure(mirror)
                control.log(f"HiAnime: Mirror {mirror} failed: {e}", 'warning')

        # Conditional fallback: ONLY if all mirrors failed AND internet is verified
        if all_failed and failed_count >= len(mirrors):
            if domains.is_internet_available():
                control.log("HiAnime: All mirrors failed but internet is available; refreshing domains from hianime.pw", 'info')
                success, new_mirrors = domains.refresh_hianime_domains(force=True)
                if success:
                    for mirror in new_mirrors:
                        if mirror not in mirrors:
                            try:
                                sources = self._scrape_mirror(mirror, title, kodi_meta, mal_id, ep_num, langs, enabled)
                                if sources:
                                    control.log(f"HiAnime: Extracted {len(sources)} source(s) from refreshed mirror {mirror}", 'info')
                                    return sources
                            except Exception as e:
                                control.log(f"HiAnime: Refreshed mirror {mirror} failed: {e}", 'warning')
            else:
                control.log("HiAnime: All mirrors failed and internet connectivity check failed; skipping domain refresh", 'warning')

        control.log(f"HiAnime: Returning {len(sources)} source(s)")
        return sources

    def _scrape_mirror(self, mirror, title, kodi_meta, mal_id, ep_num, langs, enabled):
        headers = {'Referer': mirror, 'User-Agent': client.randomagent()}
        anime_id = self._resolve_anime_id(mirror, title, kodi_meta, mal_id, headers)
        if not anime_id:
            return []

        ep_id = self._resolve_episode_id(mirror, anime_id, ep_num, headers)
        if not ep_id:
            return []

        servers = self._resolve_servers(mirror, ep_id, langs, headers)
        if not servers:
            return []

        lang_results = {}
        for lang in langs:
            megaplay_url = servers.get(lang)
            if megaplay_url:
                try:
                    res = extract_megaplay_sources(megaplay_url, mirror)
                    if res and res.get('sources'):
                        lang_results[lang] = res
                except Exception as e:
                    control.log(f"HiAnime: Megaplay extraction error for {lang}: {e}", 'warning')

        tasks = []
        for lang in langs:
            res = lang_results.get(lang)
            if not res or not res.get('sources'):
                continue
            for server in enabled:
                tasks.append((server, lang, res, {'mal_id': mal_id, 'episode': ep_num}, title, ep_num))

        results = utils.parallel_process(tasks, self._extract_server_source)
        return [src for src in results if src]

    def _enabled_servers(self):
        allowed = set(self.embeds())
        enabled = [name for name in self._SERVER_NAMES if name in allowed]
        if not enabled:
            control.log(
                'HiAnime: ryu/volt/ayame not in embed settings; using all HiAnime servers',
                level='info',
            )
            return list(self._SERVER_NAMES)
        return enabled

    def _search_keywords(self, title, mal_id, kodi_meta=None):
        keywords = []
        seen = set()

        def add(value):
            value = (value or '').strip()
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                keywords.append(value)

        add(title)
        if kodi_meta and isinstance(kodi_meta, dict):
            add(kodi_meta.get('ename'))
            add(kodi_meta.get('title_english'))
            add(kodi_meta.get('title_romaji'))

        if ':' in title:
            add(title.split(':', 1)[1].strip())
            add(title.split(':', 1)[0].strip())
        words = [w for w in re.split(r'\s+', title) if len(w) > 2]
        if len(words) >= 2:
            add(words[-1])

        try:
            zoro_title = malsync.get_title(mal_id, site='Zoro')
            add(zoro_title)
        except Exception:
            pass

        return keywords

    @staticmethod
    def _parse_search_results(html):
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        for block in soup.select('.flw-item'):
            link = block.select_one('.film-name a') or block.select_one('a.film-poster-ahref')
            if not link:
                continue
            href = link.get('href', '').split('?')[0]
            name = link.get_text(strip=True) or link.get('title') or ''
            slug = href.strip('/').split('/')[-1]
            if '-' in slug:
                anime_id = slug.split('-')[-1]
                if anime_id.isdigit():
                    items.append({'id': anime_id, 'name': name, 'slug': slug, 'href': href})
        return items

    @staticmethod
    def _season_number(text):
        if not text:
            return None
        match = re.search(r'(?:season|part)\s*(\d+)', text, re.I)
        if match:
            return int(match.group(1))
        match = re.search(r'(\d+)(?:st|nd|rd|th)\s+season', text, re.I)
        if match:
            return int(match.group(1))
        return None

    def _score_candidate(self, candidate_name, title, kodi_meta=None):
        name_lower = candidate_name.lower()
        title_lower = title.lower()
        score = 0

        if title_lower == name_lower:
            score += 150
        elif title_lower in name_lower or name_lower in title_lower:
            score += 100

        if kodi_meta and isinstance(kodi_meta, dict):
            for key in ('ename', 'title_english', 'title_romaji'):
                val = (kodi_meta.get(key) or '').lower()
                if val:
                    if val == name_lower:
                        score += 140
                    elif val in name_lower:
                        score += 90

        title_tokens = [w for w in re.split(r'[^a-z0-9]+', title_lower) if len(w) > 2]
        name_tokens = set(re.split(r'[^a-z0-9]+', name_lower))
        overlap = sum(1 for token in title_tokens if token in name_tokens)
        score += overlap * 10

        wanted_season = self._season_number(title)
        candidate_season = self._season_number(candidate_name)
        if wanted_season is None:
            if candidate_season not in (None, 1):
                score -= 40
        elif candidate_season != wanted_season:
            score -= 50

        if 'season' in name_lower and wanted_season is None and candidate_season not in (None, 1):
            score -= 20

        return score

    def _resolve_anime_id(self, mirror, title, kodi_meta, mal_id, headers):
        keywords = self._search_keywords(title, mal_id, kodi_meta)
        candidates = {}
        for keyword in keywords:
            search_url = f"{mirror}search?keyword={urllib.parse.quote_plus(keyword)}"
            html = database.get(self._get_request, 8, search_url, headers=headers)
            if not html:
                continue
            for item in self._parse_search_results(html):
                if item['id'] not in candidates:
                    candidates[item['id']] = item['name']
            if candidates:
                break

        if not candidates:
            control.log(f"HiAnime: No search matches on {mirror} for '{title}'", level='info')
            return None

        ranked = sorted(
            candidates.items(),
            key=lambda row: self._score_candidate(row[1], title, kodi_meta),
            reverse=True,
        )
        if ranked:
            best_id, best_name = ranked[0]
            control.log(f"HiAnime: Selected '{best_name}' (ID: {best_id}) on {mirror}", level='info')
            return best_id
        return None

    def _resolve_episode_id(self, mirror, anime_id, ep_num, headers):
        ep_url = f"{mirror}api/theme/episode/list/{anime_id}"
        resp_json = database.get(self._get_json_request, 8, ep_url, headers=headers)
        if not resp_json or not isinstance(resp_json, dict) or not resp_json.get('html'):
            return None

        soup = BeautifulSoup(resp_json['html'], 'html.parser')
        # 1. Direct data-number match
        ep_item = soup.select_one(f'a.ep-item[data-number="{ep_num}"]')
        if ep_item and ep_item.get('data-id'):
            return ep_item.get('data-id')

        # 2. Sequential fallback if data-number is missing
        items = soup.select('a.ep-item')
        if 0 < ep_num <= len(items):
            return items[ep_num - 1].get('data-id')

        return None

    def _resolve_servers(self, mirror, ep_id, langs, headers):
        servers_url = f"{mirror}api/theme/episode/servers?episodeId={ep_id}"
        resp_json = database.get(self._get_json_request, 8, servers_url, headers=headers)
        if not resp_json or not isinstance(resp_json, dict) or not resp_json.get('html'):
            return {}

        soup = BeautifulSoup(resp_json['html'], 'html.parser')
        server_map = {}
        for s in soup.select('.server-item'):
            stype = (s.get('data-type') or '').lower()
            if stype not in langs or stype in server_map:
                continue
            raw_hash = s.get('data-hash')
            if not raw_hash:
                continue
            try:
                decoded = base64.b64decode(raw_hash).decode('utf-8', errors='ignore')
                if 'megaplay.buzz' in decoded:
                    server_map[stype] = decoded
            except Exception:
                continue

        return server_map

    def _get_json_request(self, url, headers=None):
        raw = self._get_request(url, headers=headers)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return None

    @staticmethod
    def _proxy_playlist(m3u8_url, proxy_base, referer=None):
        referer = referer or Sources._MEGAPLAY_REF
        stream_headers = json.dumps({
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.5',
            'origin': 'https://megaplay.buzz',
            'referer': referer,
        }, separators=(',', ':'))
        return '{0}/proxy?url={1}&headers={2}'.format(
            proxy_base,
            urllib.parse.quote(m3u8_url, safe=''),
            urllib.parse.quote(stream_headers, safe=''),
        )

    @staticmethod
    def _proxy_subtitle(sub_url, fetch_base, ref=None):
        if not sub_url:
            return sub_url
        if 'animanga.fun/fetch' in sub_url or 'anixx.cloud/proxy' in sub_url:
            return sub_url
        ref = ref or Sources._MEGAPLAY_REF
        return '{0}/fetch?url={1}&ref={2}'.format(
            fetch_base,
            urllib.parse.quote(sub_url, safe=''),
            urllib.parse.quote(ref, safe=''),
        )

    @staticmethod
    def _build_tracks_subs(tracks, sub_fetch_base, play_referer, sub_ref=None):
        from resources.lib.ui import embed_extractor

        subs = []
        sub_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0',
            'Referer': play_referer,
        }
        sub_ref = sub_ref or Sources._MEGAPLAY_REF

        for idx, track in enumerate(tracks or []):
            if track.get('kind') != 'captions' or not track.get('file'):
                continue
            label = track.get('label') or ''
            sub_url = track.get('file')
            if sub_fetch_base:
                sub_url = Sources._proxy_subtitle(sub_url, sub_fetch_base, ref=sub_ref)
            subs.append({
                'url': sub_url,
                'file': track.get('file'),
                'lang': embed_extractor.detect_sub_lang(track.get('file'), label),
                'name': label,
                'index': idx,
                'headers': sub_headers,
            })
        return subs

    def _extract_server_source(self, task):
        server, lang, res, meta, title, episode = task
        try:
            play_referer = self._VIDNEST_REF
            if server == 'ayame':
                sub_fetch_base = self._PROXY_AYAME
            else:
                sub_fetch_base = self._PROXY_VOLT

            if not res or not res.get('sources'):
                control.log(f"HiAnime: No stream for {server} ({lang})", level='info')
                return None

            srclink = res['sources'][0].get('file')
            if not srclink:
                return None

            if server in ('ryu', 'volt'):
                srclink = self._proxy_playlist(srclink, self._PROXY_VOLT)
            elif server == 'ayame':
                srclink = self._proxy_playlist(srclink, self._PROXY_AYAME)

            subs = self._build_tracks_subs(
                res.get('tracks'),
                sub_fetch_base,
                play_referer,
            )

            skip = {}
            intro = res.get('intro') or {}
            outro = res.get('outro') or {}
            if intro.get('end') and int(intro.get('end', 0)) > 0:
                skip['intro'] = intro
            if outro.get('end') and int(outro.get('end', 0)) > 0:
                skip['outro'] = outro

            headers = {
                'Referer': play_referer,
                'Origin': play_referer.rstrip('/'),
            }
            quality = self._playlist_quality(srclink, headers)

            source = {
                'release_title': '{0} - Ep {1}'.format(title, episode),
                'hash': srclink + '|User-Agent=iPad&{0}'.format(urllib.parse.urlencode(headers)),
                'type': 'direct',
                'quality': quality,
                'debrid_provider': '',
                'provider': 'hianime',
                'size': 'NA',
                'seeders': 0,
                'byte_size': 0,
                'info': [server.upper() + (' DUB' if lang == 'dub' else ' SUB')],
                'lang': 3 if lang == 'dub' else 2,
                'channel': 3,
                'sub': 1,
            }
            if subs:
                source['subs'] = subs
                control.log(f"HiAnime: {server} ({lang}) attached {len(subs)} subtitle track(s)", level='info')
            if skip:
                source['skip'] = skip
            return source
        except Exception as e:
            control.log(f"HiAnime: Failed {server} ({lang}): {e}", level='error')
            return None

    def _playlist_quality(self, srclink, headers):
        quality = 0
        m3u8_res = self._get_request(srclink, headers=headers)
        if not m3u8_res:
            return 3
        quals = re.findall(r'#EXT.+?RESOLUTION=\d+x(\d+).*\n(?!#)(.+)', m3u8_res)
        if quals:
            qual = int(sorted(quals, key=lambda x: int(x[0]), reverse=True)[0][0])
            if qual <= 480:
                quality = 1
            elif qual <= 720:
                quality = 2
            elif qual <= 1080:
                quality = 3
            else:
                quality = 4
        return quality or 3
