"""bsplayer.py - BSPlayer SOAP Protocol Subtitle Provider
======================================================
"""

# -*- coding: utf-8 -*-

import xml.etree.ElementTree as ET
import time
import base64
import gzip
from typing import List, Dict, Any, Optional
from resources.lib.ui import client, control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages

SUBDOMAINS = [1, 2, 3, 4, 5, 6, 7, 8, 101, 102, 103, 104, 105, 106, 107, 108, 109]

SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
    'xmlns:ns1="{url}">'
    '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    '<ns1:{action}>{params}</ns1:{action}>'
    '</SOAP-ENV:Body>'
    '</SOAP-ENV:Envelope>'
)


def _get_api_url() -> str:
    sub = SUBDOMAINS[int(time.time()) % len(SUBDOMAINS)]
    return f"http://s{sub}.api.bsplayer-subtitles.com/v1.php"


class BSPlayerService:
    service_name = 'bsplayer'
    display_name = 'BSPlayer'

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        timeout = int(settings.get('subtitles.timeout', 15))
        url = _get_api_url()

        lang_code = languages.to_iso639_2(meta.preferred_lang)
        hash_val = meta.filehash or ''
        size_val = str(meta.filesize or '')
        imdb_id = meta.imdb_id_int or ''

        # If neither filehash nor imdb id is present, BSPlayer XML cannot query effectively
        if not hash_val and not imdb_id:
            return []

        params = (
            f'<movieHash>{hash_val}</movieHash>'
            f'<movieSize>{size_val}</movieSize>'
            f'<subLangId>{lang_code}</subLangId>'
            f'<imdbId>{imdb_id}</imdbId>'
        )

        body = SOAP_ENVELOPE.format(url=url, action='searchSubtitles', params=params)
        headers = {
            'User-Agent': 'BSPlayer/2.x (1022.12362)',
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': f'"{url}#searchSubtitles"',
            'Connection': 'close',
        }

        try:
            res = client.post(url, data=body, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                return []

            tree = ET.fromstring(res.text.strip())
            items = tree.findall('.//data/item')
            results = []

            for item in items:
                sub_id_el = item.find('subId')
                sub_name_el = item.find('subName')
                sub_lang_el = item.find('subLang')

                if sub_id_el is None or not sub_id_el.text:
                    continue

                sub_id = sub_id_el.text
                sub_name = sub_name_el.text if sub_name_el is not None and sub_name_el.text else f"{meta.title}.srt"
                sub_lang = sub_lang_el.text if sub_lang_el is not None and sub_lang_el.text else 'eng'

                sub = SubtitleResult(
                    service_name=cls.service_name,
                    display_name=cls.display_name,
                    name=sub_name,
                    lang=languages.to_english_name(sub_lang),
                    lang_code=languages.to_iso639_1(sub_lang),
                    download_url=url,
                    rating=0.0,
                    sync=bool(hash_val and item.find('movieHash') is not None),
                    action_args={
                        'sub_id': sub_id,
                        'sub_name': sub_name,
                    },
                )
                results.append(sub)

            return results
        except Exception as e:
            control.log(f"BSPlayer search error: {e}", 'warning')
            return []

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        timeout = int(settings.get('subtitles.timeout', 15))
        sub_id = result.action_args.get('sub_id')
        if not sub_id:
            return None

        url = _get_api_url()
        params = f'<subId>{sub_id}</subId>'
        body = SOAP_ENVELOPE.format(url=url, action='downloadSubtitles', params=params)
        headers = {
            'User-Agent': 'BSPlayer/2.x (1022.12362)',
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': f'"{url}#downloadSubtitles"',
            'Connection': 'close',
        }

        try:
            res = client.post(url, data=body, headers=headers, timeout=timeout)
            if not res or res.status_code != 200:
                return None

            tree = ET.fromstring(res.text.strip())
            data_el = tree.find('.//data')
            if data_el is not None and data_el.text:
                decoded = base64.b64decode(data_el.text)
                try:
                    return gzip.decompress(decoded)
                except Exception:
                    return decoded
        except Exception as e:
            control.log(f"BSPlayer download error: {e}", 'error')

        return None
