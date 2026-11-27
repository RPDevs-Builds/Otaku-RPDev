"""subsource.py - SubSource API Subtitle Provider
==============================================
"""

# -*- coding: utf-8 -*-

from typing import List, Dict, Any, Optional
from resources.lib.ui import client, control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages

API_BASE = "https://api.subsource.net/api/v1"


class SubSourceService:
    service_name = 'subsource'
    display_name = 'SubSource'

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        apikey = settings.get('subtitles.subsource.apikey', '').strip()
        if not apikey:
            return []

        timeout = float(settings.get('subtitles.timeout', 15) or 15)
        headers = {
            'X-API-Key': apikey,
            'Accept': 'application/json',
        }

        # 1. Search for movie / TV series
        target_name = (meta.tvshow or meta.title or meta.search_string) if meta.is_manual_search else (meta.tvshow or meta.title)
        if not target_name:
            return []
        search_params: Dict[str, Any] = {
            'searchType': 'text',
            'q': target_name,
        }
        if not meta.is_manual_search or meta.is_tvshow:
            search_params['type'] = 'tvseries' if meta.is_tvshow else 'movie'
        if meta.is_tvshow and (meta.tvshow_year or meta.year):
            search_params['year'] = str(meta.tvshow_year or meta.year)
        elif not meta.is_tvshow and meta.year:
            search_params['year'] = str(meta.year)

        try:
            from resources.lib.subtitles.search import title_overlap_ratio

            search_url = f"{API_BASE}/movies/search"
            res = client.get(search_url, params=search_params, headers=headers, timeout=timeout)
            search_data = res.json(default={}) if (res and res.status_code == 200) else {}
            found = search_data.get('data', []) if isinstance(search_data, dict) else []

            def _is_relevant_show(item, is_imdb_lookup=False):
                if meta.imdb_id and item.get('imdbId'):
                    return str(item['imdbId']).strip() == str(meta.imdb_id).strip()
                item_title = str(item.get('title') or '').strip()
                if not item_title:
                    return bool(is_imdb_lookup)
                return title_overlap_ratio(target_name, item_title) >= 0.4

            relevant = [it for it in found if isinstance(it, dict) and _is_relevant_show(it, is_imdb_lookup=False)]
            if not relevant and meta.imdb_id:
                imdb_params = {'searchType': 'imdb', 'imdb': meta.imdb_id}
                res = client.get(search_url, params=imdb_params, headers=headers, timeout=timeout)
                search_data = res.json(default={}) if (res and res.status_code == 200) else {}
                found = search_data.get('data', []) if isinstance(search_data, dict) else []
                relevant = [it for it in found if isinstance(it, dict) and _is_relevant_show(it, is_imdb_lookup=True)]

            if not relevant:
                return []

            movie_id = None
            matched_season = None
            first_season_id = None
            for item in relevant:
                if meta.is_movie and meta.imdb_id and item.get('imdbId') and item['imdbId'] != meta.imdb_id:
                    continue
                if item.get('season') == 1:
                    first_season_id = item.get('movieId')
                if meta.is_tvshow and meta.season and str(item.get('season')) != str(meta.season):
                    continue
                movie_id = item.get('movieId')
                if item.get('season') is not None:
                    try:
                        matched_season = int(item.get('season'))
                    except (ValueError, TypeError):
                        matched_season = None
                break

            target_movie_id = movie_id or first_season_id
            if not target_movie_id:
                return []
            if matched_season is None and target_movie_id == first_season_id and meta.is_tvshow:
                matched_season = 1

            # For long-running absolute-numbered anime (e.g. Bleach S1E60), Season 1 on SubSource
            # only covers early episodes; prioritize later-season entries before Season 1.
            is_long_running_s1 = (
                meta.is_tvshow
                and str(meta.season or '') == '1'
                and str(meta.episode or '').isdigit()
                and int(meta.episode) > 20
            )
            if is_long_running_s1:
                query_targets = []
                seen_mids = set()
                for item in relevant:
                    mid = item.get('movieId')
                    if not mid or mid in seen_mids or mid == target_movie_id:
                        continue
                    seen_mids.add(mid)
                    try:
                        it_season = int(item.get('season')) if item.get('season') is not None else None
                    except (ValueError, TypeError):
                        it_season = None
                    query_targets.append((mid, it_season))
                    if len(query_targets) >= 4:
                        break
                query_targets.append((target_movie_id, matched_season))
            else:
                query_targets = [(target_movie_id, matched_season)]

            # 2. Query subtitles for the target movie/season ID(s)
            results = []
            seen_sub_ids = set()
            for q_mid, q_season in query_targets:
                sub_params = {
                    'movieId': q_mid,
                    'language': ','.join([l.lower() for l in meta.languages]),
                }
                subs_res = client.get(f"{API_BASE}/subtitles", params=sub_params, headers=headers, timeout=timeout)
                if not subs_res or subs_res.status_code != 200:
                    continue

                subs_data = subs_res.json(default={})
                if not isinstance(subs_data, dict) or not subs_data.get('success') or not subs_data.get('data'):
                    continue

                for item in subs_data['data']:
                    rel_info = item.get('releaseInfo', [''])
                    name = rel_info[0] if rel_info else f"{target_name}.srt"
                    lang_name = (item.get('language') or 'English').capitalize()
                    lang_code = languages.to_iso639_1(lang_name)
                    impaired = bool(item.get('hearingImpaired', False))
                    link = item.get('link', '')
                    sub_id = link.split('/')[-1] if link else str(item.get('subtitleId', ''))
                    if sub_id and sub_id in seen_sub_ids:
                        continue
                    if sub_id:
                        seen_sub_ids.add(sub_id)

                    rating_data = item.get('rating', {})
                    rating = float(rating_data.get('total', 0.0) or 0.0)

                    sub = SubtitleResult(
                        service_name=cls.service_name,
                        display_name=cls.display_name,
                        name=name,
                        lang=lang_name,
                        lang_code=lang_code,
                        download_url=f"{API_BASE}/subtitles/{sub_id}/download",
                        rating=rating,
                        sync=(meta.filename_without_ext.lower() in name.lower()) if meta.filename_without_ext else False,
                        impaired=impaired,
                        season=q_season if meta.is_tvshow else None,
                        action_args={
                            'sub_id': sub_id,
                            'apikey': apikey,
                            'filename': name,
                        },
                    )
                    results.append(sub)

            return results
        except Exception as e:
            control.log(f"SubSource search error: {e}", 'warning')
            return []

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        timeout = float(settings.get('subtitles.timeout', 15) or 15)
        apikey = result.action_args.get('apikey') or settings.get('subtitles.subsource.apikey', '').strip()
        url = result.download_url
        if not url:
            return None

        headers = {'X-API-Key': apikey} if apikey else {}
        try:
            res = client.get(url, headers=headers, timeout=timeout)
            if res and res.status_code == 200:
                return res.content
        except Exception as e:
            control.log(f"SubSource download error: {e}", 'error')

        return None
