"""opensubtitles.py - OpenSubtitles.com REST API v1 Provider
=============================================================
"""

# -*- coding: utf-8 -*-

import json
import time
from typing import List, Dict, Any, Optional
from resources.lib.ui import client, control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages

API_HOST = 'api.opensubtitles.com'
API_URL = f'https://{API_HOST}/api/v1'
DEFAULT_API_KEY = '7IQ4FYAepMynq20VYYHyj5mVHtx3qvKa'
USER_AGENT = 'OtakuRPDev v5.7'

_token_cache: Dict[str, Any] = {}


def _get_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        'User-Agent': USER_AGENT,
        'Api-Key': DEFAULT_API_KEY,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def authenticate(username: str = '', password: str = '', timeout: int = 10) -> Optional[str]:
    """Authenticate with OpenSubtitles and cache the session token."""
    global _token_cache

    # Check cached token
    if _token_cache and _token_cache.get('token') and _token_cache.get('expires_at', 0) > time.time():
        return _token_cache['token']

    if not username or not password:
        return None

    try:
        url = f'{API_URL}/login'
        payload = json.dumps({'username': username, 'password': password})
        headers = _get_headers()
        res = client.post(url, data=payload, headers=headers, timeout=timeout)
        if res and res.status_code == 200:
            data = res.json()
            token = data.get('token')
            if token:
                _token_cache = {
                    'token': token,
                    'expires_at': time.time() + 86400,  # 24 hours
                }
                return token
        elif res and res.status_code == 400:
            control.log('OpenSubtitles: Invalid credentials. Check username/password.', 'warning')
    except Exception as e:
        control.log(f'OpenSubtitles authentication error: {e}', 'warning')

    return None


class OpenSubtitlesService:
    service_name = 'opensubtitles'
    display_name = 'OpenSubtitles'

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        timeout = int(settings.get('subtitles.timeout', 15))
        username = settings.get('subtitles.opensubtitles.username', '')
        password = settings.get('subtitles.opensubtitles.password', '')

        token = authenticate(username=username, password=password, timeout=timeout)

        lang_codes = languages.map_languages_to_iso639_1(meta.languages)
        params: Dict[str, Any] = {
            'languages': ','.join(lang_codes),
            'type': 'episode' if meta.is_tvshow else 'movie',
        }

        # Prefer search by IMDb ID if available
        if meta.imdb_id_int:
            params['imdb_id'] = meta.imdb_id_int

        if meta.is_tvshow and meta.season and meta.episode:
            params['season_number'] = str(meta.season)
            params['episode_number'] = str(meta.episode)
            query_title = meta.tvshow or meta.title
            if query_title and not meta.imdb_id_int:
                params['query'] = f"{query_title} S{int(meta.season):02d}E{int(meta.episode):02d}"
        else:
            if meta.year:
                params['year'] = str(meta.year)
            if not meta.imdb_id_int and meta.title:
                params['query'] = f"{meta.title} {meta.year}".strip()

        if meta.filehash:
            params['moviehash'] = meta.filehash

        try:
            url = f"{API_URL}/subtitles"
            headers = _get_headers(token=token)
            res = client.get(url, params=params, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                control.log(f"OpenSubtitles: Search failed with code {res.status_code if res else 'None'}", 'warning')
                return []

            data = res.json()
            items = data.get('data', [])
            results = []

            for item in items:
                attrs = item.get('attributes', {})
                files = attrs.get('files', [])
                if not files:
                    continue

                file_info = files[0]
                file_id = file_info.get('file_id')
                file_name = file_info.get('file_name', '')
                lang_code = attrs.get('language', 'en')
                lang_name = languages.to_english_name(lang_code)

                # Check episode and season metadata in response
                feat_details = attrs.get('feature_details', {})
                res_season = feat_details.get('season_number')
                res_ep = feat_details.get('episode_number')

                impaired = bool(attrs.get('hearing_impaired', False))
                forced = bool(attrs.get('foreign_parts_only', False))
                rating = float(attrs.get('ratings', 0.0) or 0.0) / 2.0  # normalize 0-5

                sub = SubtitleResult(
                    service_name=cls.service_name,
                    display_name=cls.display_name,
                    name=file_name,
                    lang=lang_name,
                    lang_code=lang_code,
                    download_url=f"{API_URL}/download",
                    rating=rating,
                    sync=bool(attrs.get('moviehash_match', False)),
                    impaired=impaired,
                    forced=forced,
                    action_args={
                        'file_id': file_id,
                        'file_name': file_name,
                        'token': token,
                    },
                    season=int(res_season) if res_season is not None else None,
                    episode=int(res_ep) if res_ep is not None else None,
                )
                results.append(sub)

            return results
        except Exception as e:
            control.log(f"OpenSubtitles search error: {e}", 'warning')
            return []

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        timeout = int(settings.get('subtitles.timeout', 15))
        file_id = result.action_args.get('file_id')
        token = result.action_args.get('token')

        if not file_id:
            return None

        try:
            url = f"{API_URL}/download"
            headers = _get_headers(token=token)
            payload = json.dumps({'file_id': file_id})
            res = client.post(url, data=payload, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                control.log(f"OpenSubtitles download token request failed: {res.status_code if res else 'None'}", 'warning')
                return None

            data = res.json()
            download_link = data.get('link')
            if not download_link:
                control.log("OpenSubtitles download link missing from response", 'warning')
                return None

            # Stream direct subtitle content
            file_res = client.get(download_link, timeout=timeout)
            if file_res and file_res.status_code == 200:
                return file_res.content
        except Exception as e:
            control.log(f"OpenSubtitles download error: {e}", 'error')

        return None
