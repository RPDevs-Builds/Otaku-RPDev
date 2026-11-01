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

        timeout = int(settings.get('subtitles.timeout', 15))
        headers = {
            'X-API-Key': apikey,
            'Accept': 'application/json',
        }

        # 1. Search for movie / TV series
        target_name = meta.tvshow or meta.title
        search_params: Dict[str, Any] = {
            'searchType': 'text',
            'q': target_name,
            'type': 'tvseries' if meta.is_tvshow else 'movie',
        }
        if meta.is_tvshow and (meta.tvshow_year or meta.year):
            search_params['year'] = str(meta.tvshow_year or meta.year)
        elif not meta.is_tvshow and meta.year:
            search_params['year'] = str(meta.year)

        try:
            search_url = f"{API_BASE}/movies/search"
            res = client.get(search_url, params=search_params, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                # Try IMDb search fallback
                if meta.imdb_id:
                    imdb_params = {'searchType': 'imdb', 'imdb': meta.imdb_id}
                    res = client.get(search_url, params=imdb_params, headers=headers, timeout=timeout)

            if not res or res.status_code != 200:
                return []

            search_data = res.json()
            found = search_data.get('data', [])
            if not found:
                return []

            movie_id = None
            first_season_id = None
            for item in found:
                if meta.is_movie and meta.imdb_id and item.get('imdbId') and item['imdbId'] != meta.imdb_id:
                    continue
                if item.get('season') == 1:
                    first_season_id = item.get('movieId')
                if meta.is_tvshow and meta.season and str(item.get('season')) != str(meta.season):
                    continue
                movie_id = item.get('movieId')
                break

            target_movie_id = movie_id or first_season_id
            if not target_movie_id:
                return []

            # 2. Query subtitles for the target movie/season ID
            sub_params = {
                'movieId': target_movie_id,
                'language': ','.join([l.lower() for l in meta.languages]),
            }
            subs_res = client.get(f"{API_BASE}/subtitles", params=sub_params, headers=headers, timeout=timeout)
            if not subs_res or subs_res.status_code != 200:
                return []

            subs_data = subs_res.json()
            if not subs_data.get('success') or not subs_data.get('data'):
                return []

            results = []
            for item in subs_data['data']:
                rel_info = item.get('releaseInfo', [''])
                name = rel_info[0] if rel_info else f"{target_name}.srt"
                lang_name = (item.get('language') or 'English').capitalize()
                lang_code = languages.to_iso639_1(lang_name)
                impaired = bool(item.get('hearingImpaired', False))
                link = item.get('link', '')
                sub_id = link.split('/')[-1] if link else str(item.get('subtitleId', ''))

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
        timeout = int(settings.get('subtitles.timeout', 15))
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
