"""podnadpisi.py - Podnadpisi.NET Subtitle Provider
==================================================
"""

# -*- coding: utf-8 -*-

from typing import List, Dict, Any, Optional
from resources.lib.ui import client, control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages

BASE_URL = 'https://www.podnapisi.net'


class PodnadpisiService:
    service_name = 'podnadpisi'
    display_name = 'Podnadpisi'

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        timeout = int(settings.get('subtitles.timeout', 15))
        lang_codes = languages.map_languages_to_iso639_1(meta.languages)

        params: Dict[str, Any] = {
            'keywords': meta.tvshow or meta.title,
            'language': lang_codes,
        }

        if meta.is_tvshow:
            if meta.season:
                params['seasons'] = str(meta.season)
            if meta.episode:
                params['episodes'] = str(meta.episode)
            params['movie_type'] = ['tv-series', 'mini-series']
            if meta.tvshow_year or meta.year:
                params['year'] = str(meta.tvshow_year or meta.year)
        else:
            params['movie_type'] = 'movie'
            if meta.year:
                params['year'] = str(meta.year)

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'OtakuRPDev v5.7',
        }

        try:
            url = f"{BASE_URL}/subtitles/search/advanced"
            res = client.get(url, params=params, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                return []

            data = res.json()
            items = data.get('data', [])
            results = []

            for item in items:
                publish_id = item.get('publish_id')
                if not publish_id:
                    continue

                custom_releases = item.get('custom_releases', [])
                name = custom_releases[0] if custom_releases else f"{meta.tvshow or meta.title}.srt"
                if not name.endswith(('.srt', '.ass', '.vtt')):
                    name = f"{name}.srt"

                lang_code = (item.get('language') or 'en').lower()
                lang_name = languages.to_english_name(lang_code)
                impaired = 'hearing_impaired' in item.get('flags', [])

                sub = SubtitleResult(
                    service_name=cls.service_name,
                    display_name=cls.display_name,
                    name=name,
                    lang=lang_name,
                    lang_code=lang_code,
                    download_url=f"{BASE_URL}/subtitles/{publish_id}/download",
                    rating=0.0,
                    sync=(meta.filename_without_ext in custom_releases) if meta.filename_without_ext else False,
                    impaired=impaired,
                    action_args={
                        'publish_id': publish_id,
                        'filename': name,
                    },
                )
                results.append(sub)

            return results
        except Exception as e:
            control.log(f"Podnadpisi search error: {e}", 'warning')
            return []

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        timeout = int(settings.get('subtitles.timeout', 15))
        url = result.download_url
        if not url:
            return None

        headers = {
            'User-Agent': 'OtakuRPDev v5.7',
            'Referer': BASE_URL,
        }

        try:
            res = client.get(url, headers=headers, timeout=timeout)
            if res and res.status_code == 200:
                return res.content
        except Exception as e:
            control.log(f"Podnadpisi download error: {e}", 'error')

        return None
