# -*- coding: utf-8 -*-
"""jimaku.py - Jimaku.cc Native Japanese Anime Subtitle Provider
================================================================
Queries https://jimaku.cc/api/ for Japanese (.ass/.srt/.vtt/.zip/.gz/.xz)
anime subtitles using AniList -> MAL -> Kitsu -> fuzzy title resolution.

Invariants:
  - Zero network calls when `subtitles.jimaku.apikey` is blank.
  - Zero network calls when requested languages do not include Japanese.
  - Authorization header carries the user's API key (never logged).
  - HTTP 429 respects Retry-After capped <= 3.0s via waitForAbort() and retries once.
  - Defensive JSON parsing via control.safe_json(); rejects HTML error payloads.
"""

import random
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from resources.lib.subtitles import languages
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.ui import client, control, source_utils

BASE_URL = 'https://jimaku.cc/api'
_ALLOWED_SUB_EXTS = ('.ass', '.ssa', '.srt', '.vtt', '.sub', '.zip', '.gz', '.xz')
_HTML_HEAD_RE = re.compile(rb'^\s*(?:<!doctype\s+html|<html\b|<head\b|<body\b)', re.IGNORECASE)
_SIGNS_KW = ('signs', 'songs', 'forced', 'title', 'caption')


def _requests_japanese(meta: VideoMeta) -> bool:
    """Return True if Japanese (ja/jpn/japanese) is among requested or preferred languages."""
    candidates = list(meta.languages or [])
    if meta.preferred_lang and meta.preferred_lang != 'none':
        candidates.append(meta.preferred_lang)
    for lang in candidates:
        if not lang:
            continue
        norm = str(lang).strip().lower()
        if norm in ('ja', 'jp', 'jpn', 'japanese', '日本語'):
            return True
        if languages.is_language_match(norm, 'ja'):
            return True
    return False


def _parse_retry_after(resp) -> float:
    """Parse Retry-After header capped to 3.0s with small jitter."""
    headers = getattr(resp, 'headers', None) or {}
    raw = headers.get('Retry-After') or headers.get('retry-after') or ''
    try:
        delay = float(str(raw).strip())
    except (ValueError, TypeError):
        delay = 1.0
    delay = max(0.25, min(3.0, delay))
    return min(3.0, delay + random.uniform(0.0, 0.25))


def _get_with_429_retry(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]], timeout: float):
    """Issue GET request with a single capped <=3.0s HTTP 429 backoff retry on waitForAbort.

    Returns ``(response, aborted)``.
    """
    if control.monitor.abortRequested():
        return None, True
    res = client.get(url, params=params, headers=headers, timeout=float(timeout))
    status = getattr(res, 'status_code', None) if res is not None else None
    if isinstance(status, int) and status == 429:
        delay = _parse_retry_after(res)
        control.log(f"Jimaku: HTTP 429 rate-limited; backing off {delay:.2f}s before retry", 'warning')
        if control.monitor.waitForAbort(delay):
            return None, True
        res = client.get(url, params=params, headers=headers, timeout=float(timeout))
    return res, False


def _extract_subtitle_format(filename: str) -> str:
    low = str(filename or '').lower()
    for comp in ('.xz', '.gz', '.zip'):
        if low.endswith(comp):
            low = low[:-len(comp)]
    for ext in ('.ass', '.ssa', '.srt', '.vtt', '.sub'):
        if low.endswith(ext):
            return ext.lstrip('.')
    return ''


def _is_html_payload(raw_bytes: bytes) -> bool:
    if not raw_bytes:
        return True
    return bool(_HTML_HEAD_RE.match(raw_bytes[:256]))


def _parse_json_response(res) -> Any:
    if res is None:
        return None
    raw_text = getattr(res, 'text', None)
    if isinstance(raw_text, str):
        parsed = control.safe_json(raw_text, default=None)
        if parsed is not None:
            return parsed
    if hasattr(res, 'json'):
        try:
            return res.json(default=None)
        except TypeError:
            try:
                return res.json()
            except Exception:
                return None
    return None


class JimakuService:
    service_name = 'jimaku'
    display_name = 'Jimaku'

    @classmethod
    def _resolve_entry(
        cls,
        meta: VideoMeta,
        headers: Dict[str, str],
        timeout: float,
    ) -> tuple[Optional[int], str]:
        """Resolve a Jimaku entry ID via AniList -> MAL -> Kitsu -> fuzzy title."""
        search_url = f"{BASE_URL}/entries/search"
        id_lookups = [
            ('anilist_id', getattr(meta, 'anilist_id', '')),
            ('mal_id', getattr(meta, 'mal_id', '')),
            ('kitsu_id', getattr(meta, 'kitsu_id', '')),
        ]
        for param_key, param_val in id_lookups:
            val_s = str(param_val or '').strip()
            if not val_s or not val_s.isdigit():
                continue
            res, aborted = _get_with_429_retry(search_url, headers=headers, params={param_key: val_s}, timeout=timeout)
            if aborted:
                return None, ''
            status = getattr(res, 'status_code', None) if res is not None else None
            if not (isinstance(status, int) and status == 200):
                continue
            entries = _parse_json_response(res)
            if isinstance(entries, list) and entries:
                first = entries[0]
                if isinstance(first, dict) and first.get('id') is not None:
                    return int(first['id']), param_key

        # Fuzzy title fallback with strict candidate title scoring (>= 100, rejects derivatives <= 40)
        query_title = (meta.tvshow or meta.title or meta.search_string or '').strip()
        if not query_title:
            return None, ''
        res, aborted = _get_with_429_retry(search_url, headers=headers, params={'query': query_title}, timeout=timeout)
        if aborted:
            return None, ''
        status = getattr(res, 'status_code', None) if res is not None else None
        if not (isinstance(status, int) and status == 200):
            return None, ''
        entries = _parse_json_response(res)
        if not isinstance(entries, list) or not entries:
            return None, ''

        aliases = [a for a in (meta.original_title, meta.title, meta.tvshow) if a and a != query_title]
        best_id = None
        best_score = 0
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('id') is None:
                continue
            cand_titles = [
                str(entry.get(k) or '').strip()
                for k in ('name', 'english_name', 'japanese_name')
                if entry.get(k)
            ]
            cand_best = 0
            for ct in cand_titles:
                sc = source_utils.score_title_candidate(query_title, ct, aliases=aliases, year=meta.year or None)
                if sc > cand_best:
                    cand_best = sc
            if cand_best >= 100 and cand_best > best_score:
                best_score = cand_best
                best_id = int(entry['id'])
        return (best_id, 'title') if best_id is not None else (None, '')

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        # 1. Clean 0-network-call skip when API key is missing
        apikey = str(settings.get('subtitles.jimaku.apikey', '') or '').strip()
        if not apikey:
            return []

        # 2. Clean 0-network-call short-circuit when Japanese is not requested
        if not _requests_japanese(meta):
            return []

        timeout = float(settings.get('subtitles.timeout', 15) or 15)
        headers = {
            'Authorization': apikey,
            'Accept': 'application/json',
        }

        entry_id, matched_via = cls._resolve_entry(meta, headers=headers, timeout=timeout)
        if entry_id is None:
            return []

        files_url = f"{BASE_URL}/entries/{entry_id}/files"
        params: Dict[str, Any] = {}
        ep_int: Optional[int] = None
        if meta.is_tvshow and meta.episode and str(meta.episode).isdigit():
            ep_int = int(meta.episode)
            params['episode'] = str(ep_int)

        res, aborted = _get_with_429_retry(files_url, headers=headers, params=params or None, timeout=timeout)
        if aborted:
            return []
        status = getattr(res, 'status_code', None) if res is not None else None
        if not (isinstance(status, int) and status == 200):
            return []

        files = _parse_json_response(res)
        if not isinstance(files, list):
            return []

        season_int = int(meta.season) if meta.season and str(meta.season).isdigit() else None
        results: List[SubtitleResult] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            fname = str(item.get('name') or '').strip()
            dl_url = str(item.get('url') or '').strip()
            if not fname or not dl_url:
                continue
            if not fname.lower().endswith(_ALLOWED_SUB_EXTS):
                continue

            sub_fmt = _extract_subtitle_format(fname)
            rel_group = source_utils.extract_release_group(fname)
            is_signs = any(kw in fname.lower() for kw in _SIGNS_KW)
            exact_id_match = matched_via in ('anilist_id', 'mal_id', 'kitsu_id')

            results.append(
                SubtitleResult(
                    service_name=cls.service_name,
                    display_name=cls.display_name,
                    name=fname,
                    lang='Japanese',
                    lang_code='ja',
                    download_url=dl_url,
                    rating=4.5 if exact_id_match else 4.0,
                    sync=False,
                    impaired=False,
                    forced=is_signs,
                    color='hotpink',
                    action_args={'entry_id': entry_id, 'matched_via': matched_via},
                    season=season_int,
                    episode=ep_int,
                    auto_identified=exact_id_match,
                    match_confidence='exact' if exact_id_match else 'high',
                    match_reason=f"Jimaku ({matched_via})" if exact_id_match else 'Jimaku',
                    release_group=rel_group,
                    is_anime_native=True,
                    subtitle_format=sub_fmt,
                    is_signs_only=is_signs,
                )
            )
        return results

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        dl_url = str(result.download_url or '').strip()
        if not dl_url or not dl_url.startswith(('http://', 'https://')):
            return None

        timeout = float(settings.get('subtitles.timeout', 15) or 15)
        apikey = str(settings.get('subtitles.jimaku.apikey', '') or '').strip()
        headers: Dict[str, str] = {}
        try:
            host = (urlparse(dl_url).hostname or '').lower()
            if apikey and (host == 'jimaku.cc' or host.endswith('.jimaku.cc')):
                headers['Authorization'] = apikey
        except Exception:
            pass

        res, aborted = _get_with_429_retry(dl_url, headers=headers, params=None, timeout=timeout)
        if aborted:
            return None
        status = getattr(res, 'status_code', None) if res is not None else None
        if not (isinstance(status, int) and status == 200):
            return None

        raw = getattr(res, 'content', None)
        if isinstance(raw, str):
            raw = raw.encode('utf-8', errors='replace')
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return None
        raw_bytes = bytes(raw)
        if _is_html_payload(raw_bytes):
            control.log(f"Jimaku: Rejected HTML error payload for {result.name}", 'warning')
            return None
        return raw_bytes
