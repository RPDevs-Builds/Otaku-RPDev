"""addic7ed.py - Addic7ed Web Subtitle Provider
==============================================
"""

# -*- coding: utf-8 -*-

import re
from typing import List, Dict, Any, Optional
from resources.lib.ui import client, control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages

BASE_URL = 'https://www.addic7ed.com'


class Addic7edService:
    service_name = 'addic7ed'
    display_name = 'Addic7ed'

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        if not meta.is_tvshow or not meta.season or not meta.episode:
            return []

        timeout = int(settings.get('subtitles.timeout', 15))
        show_name = meta.tvshow or meta.title
        s_int = int(meta.season)
        ep_int = int(meta.episode)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': BASE_URL,
        }

        # Addic7ed episode search URL
        clean_show = re.sub(r'[^\w\s]', '', show_name).replace(' ', '_')
        url = f"{BASE_URL}/serie/{clean_show}/{s_int}/{ep_int}/"

        try:
            res = client.get(url, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                return []

            html = res.text
            results = []

            # Match subtitle blocks on the episode page
            # Pattern extracts language, version / release name, and download link
            blocks = html.split('<table class="tabel"')
            for block in blocks[1:]:
                # Extract language
                lang_match = re.search(r'class="language">([^<]+)', block)
                if not lang_match:
                    continue
                lang_name = lang_match.group(1).strip()
                lang_code = languages.to_iso639_1(lang_name)

                # Check if matches target languages
                if lang_name.lower() not in [l.lower() for l in meta.languages] and lang_code != meta.preferred_lang:
                    continue

                # Version / release
                ver_match = re.search(r'Version\s+([^,]+)', block)
                version_str = ver_match.group(1).strip() if ver_match else ''
                name = f"{show_name}.S{s_int:02d}E{ep_int:02d}.{version_str}.srt" if version_str else f"{show_name}.S{s_int:02d}E{ep_int:02d}.srt"

                # Download link
                dl_match = re.search(r'href="(/updated/[^"]+|/original/[^"]+)"', block)
                if not dl_match:
                    continue
                dl_url = f"{BASE_URL}{dl_match.group(1)}"

                impaired = 'Hearing Impaired' in block

                sub = SubtitleResult(
                    service_name=cls.service_name,
                    display_name=cls.display_name,
                    name=name,
                    lang=lang_name,
                    lang_code=lang_code,
                    download_url=dl_url,
                    rating=0.0,
                    sync=(meta.filename_without_ext.lower() in name.lower()) if meta.filename_without_ext else False,
                    impaired=impaired,
                    action_args={
                        'referer': url,
                    },
                    season=s_int,
                    episode=ep_int,
                )
                results.append(sub)

            return results
        except Exception as e:
            control.log(f"Addic7ed search error: {e}", 'warning')
            return []

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        timeout = int(settings.get('subtitles.timeout', 15))
        url = result.download_url
        if not url:
            return None

        referer = result.action_args.get('referer', BASE_URL)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': referer,
        }

        try:
            res = client.get(url, headers=headers, timeout=timeout)
            if res and res.status_code == 200:
                return res.content
        except Exception as e:
            control.log(f"Addic7ed download error: {e}", 'error')

        return None
