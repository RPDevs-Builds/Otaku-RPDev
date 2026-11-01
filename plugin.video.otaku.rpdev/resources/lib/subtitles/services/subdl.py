"""subdl.py - SubDL API v2 Subtitle Provider
==========================================
"""

# -*- coding: utf-8 -*-

from typing import List, Dict, Any, Optional
from resources.lib.ui import client, control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages

BASE_URL = 'https://api.subdl.com/api/v2'
DL_BASE_URL = 'https://dl.subdl.com'


class SubDLService:
    service_name = 'subdl'
    display_name = 'SubDL'

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        apikey = settings.get('subtitles.subdl.apikey', '').strip()
        if not apikey:
            return []

        timeout = int(settings.get('subtitles.timeout', 15))
        lang_codes = languages.map_languages_to_iso639_1(meta.languages)

        params: Dict[str, Any] = {
            'languages': ','.join(lang_codes),
            'type': 'tv' if meta.is_tvshow else 'movie',
        }
        headers = {
            'Authorization': f'Bearer {apikey}',
            'Accept': 'application/json',
        }

        if meta.is_tvshow:
            params['film_name'] = meta.tvshow or meta.title
            params['file_name'] = meta.filename_without_ext
            if meta.season:
                params['season'] = str(meta.season)
            if meta.episode:
                params['episode'] = str(meta.episode)
            if meta.tvshow_year or meta.year:
                params['year'] = str(meta.tvshow_year or meta.year)
        else:
            if meta.imdb_id:
                params['imdb_id'] = meta.imdb_id
            if meta.year:
                params['year'] = str(meta.year)
            params['film_name'] = meta.title

        try:
            url = f"{BASE_URL}/subtitles/search"
            res = client.get(url, params=params, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                control.log(f"SubDL search returned status {res.status_code if res else 'None'}", 'warning')
                return []

            data = res.json()
            if 'error' in data:
                err_msg = data['error'].get('message', str(data['error'])) if isinstance(data['error'], dict) else str(data['error'])
                control.log(f"SubDL error: {err_msg}", 'warning')
                return []

            subtitles = data.get('subtitles', [])
            results = []

            for sub_data in subtitles:
                release_name = sub_data.get('release_name', '') or sub_data.get('name', '')
                dl_path = sub_data.get('url', '')
                if not dl_path:
                    continue

                lang_code = (sub_data.get('language') or 'en').lower()
                lang_name = languages.to_english_name(lang_code)
                impaired = bool(sub_data.get('hi', False))
                forced = bool(sub_data.get('forced', False))
                res_season = sub_data.get('season')
                res_ep = sub_data.get('episode')

                sub = SubtitleResult(
                    service_name=cls.service_name,
                    display_name=cls.display_name,
                    name=release_name,
                    lang=lang_name,
                    lang_code=lang_code,
                    download_url=f"{DL_BASE_URL}{dl_path}" if dl_path.startswith('/') else dl_path,
                    rating=0.0,
                    sync=(meta.filename_without_ext.lower() in release_name.lower()) if meta.filename_without_ext else False,
                    impaired=impaired,
                    forced=forced,
                    action_args={
                        'url': dl_path,
                        'filename': release_name,
                    },
                    season=int(res_season) if res_season is not None else None,
                    episode=int(res_ep) if res_ep is not None else None,
                )
                results.append(sub)

            return results
        except Exception as e:
            control.log(f"SubDL search error: {e}", 'warning')
            return []

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        timeout = int(settings.get('subtitles.timeout', 15))
        url = result.download_url
        if not url:
            return None

        try:
            res = client.get(url, timeout=timeout)
            if res and res.status_code == 200:
                return res.content
        except Exception as e:
            control.log(f"SubDL download error: {e}", 'error')

        return None
