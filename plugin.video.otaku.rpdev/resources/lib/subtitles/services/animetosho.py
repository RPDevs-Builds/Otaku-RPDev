# -*- coding: utf-8 -*-
"""animetosho.py - AnimeTosho Native Standalone Subtitle Attachment Provider
============================================================================
Queries https://feed.animetosho.org/json for standalone fansub subtitle
attachments (.ass, .ssa, .srt, .vtt, .ass.xz, .srt.xz, .ass.gz, .srt.gz, .zip).

Invariants:
  - No API key required (default enabled via `subtitles.provider.animetosho`).
  - Query priority: eid (anidb_ep_id) -> aid (anidb_id) -> q (title + episode,
    strictly gated by source_utils.score_title_candidate >= 100).
  - Never issues unbounded sequential detail fetches inside the subtitle timeout:
    parses inline attachments first and caps optional detail lookups to <= 2
    candidates strictly while remaining budget > 2.0s.
  - Prioritizes styled Full Dialogue .ass attachments over Signs-only tracks.
  - HTTP 429 respects Retry-After capped <= 3.0s via waitForAbort() and retries once.
  - Rejects HTML error bodies on download.
"""

import random
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from resources.lib.subtitles import languages
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.ui import client, control, source_utils

FEED_BASE_URL = 'https://feed.animetosho.org/json'
_SUB_EXTS = ('.ass', '.ssa', '.srt', '.vtt', '.sub')
_COMP_EXTS = ('.xz', '.gz', '.zip')
_HTML_HEAD_RE = re.compile(rb'^\s*(?:<!doctype\s+html|<html\b|<head\b|<body\b)', re.IGNORECASE)
_SIGNS_KW = ('signs', 'songs', 'forced', 'title', 'caption', 'op/ed', 'oped')
_MAX_DETAIL_FETCHES = 2

_LANG_HINTS = {
    'en': ('eng', 'english', '.en.', '_en_', '[en]', '(en)'),
    'ja': ('jpn', 'japanese', '.ja.', '.jp.', '[ja]', '[jp]'),
    'es': ('spa', 'spanish', 'espanol', 'latino', '.es.'),
    'fr': ('fre', 'fra', 'french', 'francais', '.fr.'),
    'de': ('ger', 'deu', 'german', 'deutsch', '.de.'),
    'pt': ('por', 'portuguese', 'pt-br', 'ptbr', '.pt.'),
    'it': ('ita', 'italian', '.it.'),
    'ru': ('rus', 'russian', '.ru.'),
    'ar': ('ara', 'arabic', '.ar.'),
    'zh': ('chi', 'zho', 'chinese', 'chs', 'cht', '.zh.'),
    'ko': ('kor', 'korean', '.ko.'),
}


def _join_query(base_url: str, params: Dict[str, Any]) -> str:
    """Join query parameters safely without creating duplicate '?' characters."""
    if not params:
        return base_url
    sep = '&' if '?' in base_url else '?'
    return f"{base_url}{sep}{urlencode(params)}"


def _parse_retry_after(resp) -> float:
    headers = getattr(resp, 'headers', None) or {}
    raw = headers.get('Retry-After') or headers.get('retry-after') or ''
    try:
        delay = float(str(raw).strip())
    except (ValueError, TypeError):
        delay = 1.0
    delay = max(0.25, min(3.0, delay))
    return min(3.0, delay + random.uniform(0.0, 0.25))


def _get_with_429_retry(url: str, timeout: float):
    if control.monitor.abortRequested():
        return None, True
    res = client.get(url, timeout=float(timeout))
    status = getattr(res, 'status_code', None) if res is not None else None
    if isinstance(status, int) and status == 429:
        delay = _parse_retry_after(res)
        control.log(f"AnimeTosho Subs: HTTP 429 rate-limited; backing off {delay:.2f}s", 'warning')
        if control.monitor.waitForAbort(delay):
            return None, True
        res = client.get(url, timeout=float(timeout))
    return res, False


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


def _strip_comp_ext(name: str) -> str:
    low = str(name or '')
    for ce in _COMP_EXTS:
        if low.lower().endswith(ce):
            return low[:-len(ce)]
    return low


def _subtitle_format(filename: str) -> str:
    inner = _strip_comp_ext(filename).lower()
    for ext in _SUB_EXTS:
        if inner.endswith(ext):
            return ext.lstrip('.')
    return ''


def _is_subtitle_attachment(filename: str, att_type: str = '') -> bool:
    if _subtitle_format(filename):
        return True
    if str(att_type or '').lower() in ('subtitle', 'subtitles', 'sub'):
        return True
    return False


def _detect_attachment_lang(filename: str, meta_lang: str = '') -> tuple[str, str]:
    """Return (iso639_1, display_name) for an attachment; defaults to English for standard fansub .ass."""
    if meta_lang:
        code = languages.to_iso639_1(str(meta_lang).strip())
        if code and code != 'unknown':
            return code, languages.to_english_name(code)
    low = f" {str(filename or '').lower()} "
    for code, hints in _LANG_HINTS.items():
        if any(h in low for h in hints):
            return code, languages.to_english_name(code)
    return 'en', 'English'


def _lang_requested(lang_code: str, meta: VideoMeta) -> bool:
    targets = list(meta.languages or [])
    if meta.preferred_lang and meta.preferred_lang != 'none':
        targets.append(meta.preferred_lang)
    if not targets:
        return True
    return any(languages.is_language_match(lang_code, t) for t in targets if t)


def _extract_attachments_from_entry(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract normalized attachment dicts from an AnimeTosho JSON entry."""
    found: List[Dict[str, Any]] = []
    if not isinstance(entry, dict):
        return found

    for key in ('attachments', 'subtitles'):
        raw_list = entry.get(key)
        if isinstance(raw_list, list):
            for att in raw_list:
                if isinstance(att, dict):
                    url = str(att.get('url') or att.get('link') or '').strip()
                    fname = str(att.get('filename') or att.get('name') or '').strip()
                    if not fname and url:
                        fname = url.split('?')[0].rstrip('/').split('/')[-1]
                    if url and _is_subtitle_attachment(fname, str(att.get('type') or '')):
                        found.append({
                            'url': url,
                            'filename': fname,
                            'lang': str(att.get('language') or att.get('lang') or '').strip(),
                            'label': str(att.get('label') or att.get('title') or '').strip(),
                        })

    # Also support nested files[].attachments in show=torrent detail responses
    files_list = entry.get('files')
    if isinstance(files_list, list):
        for fobj in files_list:
            if isinstance(fobj, dict):
                for att in (fobj.get('attachments') or []):
                    if isinstance(att, dict):
                        url = str(att.get('url') or att.get('link') or '').strip()
                        fname = str(att.get('filename') or att.get('name') or '').strip()
                        if not fname and url:
                            fname = url.split('?')[0].rstrip('/').split('/')[-1]
                        if url and _is_subtitle_attachment(fname, str(att.get('type') or '')):
                            found.append({
                                'url': url,
                                'filename': fname,
                                'lang': str(att.get('language') or att.get('lang') or '').strip(),
                                'label': str(att.get('label') or att.get('title') or '').strip(),
                            })

    # Support top-level single subtitle_url if provided
    single_url = str(entry.get('subtitle_url') or '').strip()
    if single_url:
        fname = single_url.split('?')[0].rstrip('/').split('/')[-1]
        if _is_subtitle_attachment(fname, 'subtitle'):
            found.append({'url': single_url, 'filename': fname, 'lang': '', 'label': ''})

    return found


def _is_html_payload(raw_bytes: bytes) -> bool:
    if not raw_bytes:
        return True
    return bool(_HTML_HEAD_RE.match(raw_bytes[:256]))


class AnimetoshoSubtitleService:
    service_name = 'animetosho'
    display_name = 'AnimeTosho'

    @classmethod
    def _query_title_entries(cls, meta: VideoMeta, timeout: float) -> tuple[List[Dict[str, Any]], str]:
        """Query AnimeTosho JSON feed by title + episode and gate with score_title_candidate >= 100."""
        query_title = (meta.tvshow or meta.title or meta.search_string or '').strip()
        if not query_title:
            return [], ''
        if meta.is_tvshow and meta.episode and str(meta.episode).isdigit():
            q_str = f"{query_title} {int(meta.episode):02d}"
        else:
            q_str = query_title
        url = _join_query(FEED_BASE_URL, {'q': q_str})
        res, aborted = _get_with_429_retry(url, timeout=timeout)
        if aborted:
            return [], ''
        status = getattr(res, 'status_code', None) if res is not None else None
        if not (isinstance(status, int) and status == 200):
            return [], ''
        data = _parse_json_response(res)
        if not isinstance(data, list):
            return [], ''

        aliases = [a for a in (meta.original_title, meta.title, meta.tvshow) if a and a != query_title]
        filtered = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            etitle = str(entry.get('title') or '').strip()
            if not etitle:
                continue
            if source_utils.score_title_candidate(query_title, etitle, aliases=aliases, year=meta.year or None) >= 100:
                filtered.append(entry)
        return filtered, 'query'

    @classmethod
    def _query_entries(cls, meta: VideoMeta, timeout: float) -> tuple[List[Dict[str, Any]], str]:
        """Query AnimeTosho JSON feed by eid -> aid -> title+episode."""
        anidb_ep_id = str(getattr(meta, 'anidb_ep_id', '') or '').strip()
        anidb_id = str(getattr(meta, 'anidb_id', '') or '').strip()

        if anidb_ep_id and anidb_ep_id.isdigit():
            url = _join_query(FEED_BASE_URL, {'eid': anidb_ep_id})
            res, aborted = _get_with_429_retry(url, timeout=timeout)
            if aborted:
                return [], ''
            status = getattr(res, 'status_code', None) if res is not None else None
            if isinstance(status, int) and status == 200:
                data = _parse_json_response(res)
                if isinstance(data, list) and data:
                    return data, 'anidb_eid'

        if anidb_id and anidb_id.isdigit():
            url = _join_query(FEED_BASE_URL, {'aid': anidb_id})
            res, aborted = _get_with_429_retry(url, timeout=timeout)
            if aborted:
                return [], ''
            status = getattr(res, 'status_code', None) if res is not None else None
            if isinstance(status, int) and status == 200:
                data = _parse_json_response(res)
                if isinstance(data, list) and data:
                    return data, 'anidb_aid'

        return cls._query_title_entries(meta, timeout=timeout)

    @classmethod
    def _collect_results(
        cls,
        entries: List[Dict[str, Any]],
        matched_via: str,
        meta: VideoMeta,
        timeout: float,
        deadline: float,
        seen_urls: set,
        detail_budget: Optional[List[int]] = None,
    ) -> List[SubtitleResult]:
        target_group_norm = source_utils.normalize_release_group(
            getattr(meta, 'release_group', '') or getattr(meta, 'preferred_group', '')
        )
        season_int = int(meta.season) if meta.season and str(meta.season).isdigit() else None
        ep_int = int(meta.episode) if meta.episode and str(meta.episode).isdigit() else None

        # Prioritize entries matching target release_group first, then seeders descending
        def _entry_rank(e: Dict[str, Any]):
            grp = source_utils.normalize_release_group(
                source_utils.extract_release_group(str(e.get('title') or ''))
            )
            grp_hit = 1 if (target_group_norm and grp == target_group_norm) else 0
            seeders = int(e.get('seeders') or 0) if str(e.get('seeders') or '').isdigit() else 0
            return (-grp_hit, -seeders)

        ordered = sorted([e for e in entries if isinstance(e, dict)], key=_entry_rank)

        results: List[SubtitleResult] = []
        if detail_budget is None:
            detail_budget = [0]

        for entry in ordered:
            parent_title = str(entry.get('title') or '').strip()
            rel_group = source_utils.extract_release_group(parent_title)

            # For aid-level queries when episode is known, skip entries with explicit wrong episode number
            if matched_via == 'anidb_aid' and ep_int is not None and parent_title:
                ep_range = source_utils.extract_episode_range(parent_title)
                if ep_range is None:
                    ep_m = re.search(r'(?:^|[\s._\[-])(?:s\d{1,2}e|ep?\.?|-\s*)0*(\d{1,4})(?:v\d)?(?:[\s._\]\(-]|$)', parent_title, re.IGNORECASE)
                    if ep_m and int(ep_m.group(1)) != ep_int:
                        continue

            attachments = _extract_attachments_from_entry(entry)
            # Bounded optional detail lookup ONLY when inline attachments absent and time budget allows
            if (
                not attachments
                and detail_budget[0] < _MAX_DETAIL_FETCHES
                and entry.get('id') is not None
                and (deadline - time.monotonic()) > 2.0
                and not control.monitor.abortRequested()
            ):
                detail_budget[0] += 1
                rem_timeout = min(timeout, max(1.5, deadline - time.monotonic()))
                detail_url = _join_query(FEED_BASE_URL, {'show': 'torrent', 'id': str(entry['id'])})
                dres, daborted = _get_with_429_retry(detail_url, timeout=rem_timeout)
                if daborted:
                    break
                dstatus = getattr(dres, 'status_code', None) if dres is not None else None
                if isinstance(dstatus, int) and dstatus == 200:
                    detail_data = _parse_json_response(dres)
                    if isinstance(detail_data, dict):
                        attachments = _extract_attachments_from_entry(detail_data)

            for att in attachments:
                att_url = att['url']
                if att_url in seen_urls:
                    continue
                seen_urls.add(att_url)

                fname = att['filename'] or parent_title
                lang_code, lang_name = _detect_attachment_lang(f"{fname} {att.get('label', '')}", att.get('lang', ''))
                if not _lang_requested(lang_code, meta):
                    continue

                sub_fmt = _subtitle_format(fname)
                low_check = f"{fname} {att.get('label', '')}".lower()
                is_signs = any(kw in low_check for kw in _SIGNS_KW)
                display_fname = fname if (rel_group and rel_group.lower() in fname.lower()) else (
                    f"[{rel_group}] {fname}" if rel_group else fname
                )
                exact_id = matched_via == 'anidb_eid'
                grp_matched = bool(
                    target_group_norm
                    and rel_group
                    and source_utils.normalize_release_group(rel_group) == target_group_norm
                )

                results.append(
                    SubtitleResult(
                        service_name=cls.service_name,
                        display_name=cls.display_name,
                        name=display_fname,
                        lang=lang_name,
                        lang_code=lang_code,
                        download_url=att_url,
                        rating=5.0 if (sub_fmt in ('ass', 'ssa') and not is_signs) else 4.0,
                        sync=grp_matched,
                        impaired=False,
                        forced=is_signs,
                        color='deepskyblue',
                        action_args={
                            'torrent_id': entry.get('id'),
                            'matched_via': matched_via,
                            'parent_title': parent_title,
                        },
                        season=season_int,
                        episode=ep_int,
                        auto_identified=exact_id or grp_matched,
                        match_confidence='exact' if (exact_id or grp_matched) else 'high',
                        match_reason='Release Group' if grp_matched else ('AniDB Ep' if exact_id else 'AnimeTosho'),
                        release_group=rel_group,
                        is_anime_native=True,
                        subtitle_format=sub_fmt,
                        is_signs_only=is_signs,
                    )
                )
        return results

    @classmethod
    def search(cls, meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
        timeout = float(settings.get('subtitles.timeout', 15) or 15)
        deadline = time.monotonic() + max(3.0, timeout)

        entries, matched_via = cls._query_entries(meta, timeout=timeout)
        seen_urls = set()
        detail_budget = [0]
        results = (
            cls._collect_results(entries, matched_via, meta, timeout, deadline, seen_urls, detail_budget=detail_budget)
            if entries else []
        )

        # Long-running anime (e.g. Bleach aid=2369) return only recent batches/episodes on aid= queries;
        # fall back to title+episode query when aid yields 0 usable subtitle attachments.
        if (
            not results
            and matched_via == 'anidb_aid'
            and (deadline - time.monotonic()) > 2.0
            and not control.monitor.abortRequested()
        ):
            rem_timeout = min(timeout, max(1.5, deadline - time.monotonic()))
            q_entries, q_via = cls._query_title_entries(meta, timeout=rem_timeout)
            if q_entries:
                results.extend(
                    cls._collect_results(q_entries, q_via, meta, timeout, deadline, seen_urls, detail_budget=detail_budget)
                )

        return results

    @classmethod
    def download(cls, result: SubtitleResult, settings: Dict[str, Any]) -> Optional[bytes]:
        dl_url = str(result.download_url or '').strip()
        if not dl_url or not dl_url.startswith(('http://', 'https://')):
            return None

        timeout = float(settings.get('subtitles.timeout', 15) or 15)
        res, aborted = _get_with_429_retry(dl_url, timeout=timeout)
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
            control.log(f"AnimeTosho Subs: Rejected HTML error payload for {result.name}", 'warning')
            return None
        return raw_bytes
