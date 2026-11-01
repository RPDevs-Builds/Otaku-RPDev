"""search.py - Multi-Threaded Subtitle Search & Intelligent Ranking Orchestrator
=============================================================================
"""

# -*- coding: utf-8 -*-

import concurrent.futures
import re
from typing import List, Dict, Any, Optional
from resources.lib.ui import control
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles.services import ALL_SERVICES
from resources.lib.subtitles import languages


def score_result(sub: SubtitleResult, meta: VideoMeta, settings: Dict[str, Any]) -> float:
    """
    Computes ranking score for a subtitle result.
    Higher score = better rank.
    """
    score = 0.0
    name_lower = sub.name.lower()
    pref_lang = meta.preferred_lang.lower()
    sub_lang = (sub.lang_code or sub.lang).lower()

    # 1. Language Preference
    if pref_lang and languages.is_language_match(sub_lang, pref_lang):
        score += 1.0
    elif sub_lang:
        score -= 1.0

    # 2. Episode & Season Matching Heuristics
    if meta.is_tvshow and meta.season and meta.episode:
        try:
            target_s = int(meta.season)
            target_e = int(meta.episode)
        except (ValueError, TypeError):
            target_s = None
            target_e = None

        if target_s is not None and target_e is not None:
            # Check parsed season & episode on the result object
            if sub.season == target_s and sub.episode == target_e:
                score += 0.8
            elif sub.season == target_s and sub.episode is None:
                # Season pack
                score += 0.4
            elif sub.episodes_range and target_e in sub.episodes_range:
                # Episode range (e.g. 01-12)
                score += 0.6
            elif sub.season is not None and sub.episode is not None:
                if sub.season != target_s or sub.episode != target_e:
                    # Mismatched episode/season: strong penalty
                    score -= 1.0

            # Regex search in filename
            s_e_pattern = re.compile(rf'[._\s\-\[]s0*{target_s}e0*{target_e}[._\s\-\]]', re.IGNORECASE)
            alt_pattern = re.compile(rf'[._\s\-\[]0*{target_s}x0*{target_e}[._\s\-\]]', re.IGNORECASE)
            single_ep_pattern = re.compile(rf'[._\s\-\[]e0*{target_e}[._\s\-\]]', re.IGNORECASE)

            if s_e_pattern.search(name_lower) or alt_pattern.search(name_lower):
                score += 0.8
            elif single_ep_pattern.search(name_lower):
                score += 0.6
            elif f"s{target_s:02d}" in name_lower and f"e{target_e:02d}" in name_lower:
                score += 0.7

    # 3. Filename / Hash match
    if sub.sync:
        score += 0.5
    elif meta.filename_without_ext and meta.filename_without_ext.lower() in name_lower:
        score += 0.4

    # 4. SDH / Hearing Impaired Preference
    prefer_sdh = settings.get('subtitles.prefer_sdh', False)
    if prefer_sdh:
        if sub.impaired or 'sdh' in name_lower or 'captions' in name_lower:
            score += 0.2
        else:
            score -= 0.1
    else:
        if sub.impaired or 'sdh' in name_lower or 'captions' in name_lower:
            score -= 0.2
        else:
            score += 0.1

    # 5. Forced / Signs & Songs Preference
    prefer_forced = settings.get('subtitles.prefer_forced', False)
    has_forced_marker = sub.forced or any(kw in name_lower for kw in ('forced', 'signs', 'songs'))
    if prefer_forced:
        if has_forced_marker:
            score += 0.3
        else:
            score -= 0.2
    else:
        if has_forced_marker:
            score -= 0.3
        else:
            score += 0.2

    # 6. Provider Quality Rating
    if sub.rating > 0:
        score += (sub.rating / 10.0)

    sub.score = score
    return score


def search_all_services(meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
    """
    Queries all enabled subtitle services in parallel, applies intelligent scoring,
    and returns sorted results.
    """
    if not meta.preferred_lang or meta.preferred_lang.lower() == 'none':
        control.log("Native Subtitles: Preferred subtitle language is 'none', skipping external provider queries", 'info')
        return []

    timeout = int(settings.get('subtitles.timeout', 15))
    results_limit = int(settings.get('subtitles.results_limit', 20))

    enabled_services = []
    for service_name, service_cls in ALL_SERVICES.items():
        # Check setting: subtitles.provider.<service_name>
        setting_key = f"subtitles.provider.{service_name}"
        if settings.get(setting_key, True):
            enabled_services.append((service_name, service_cls))

    if not enabled_services:
        control.log("Native Subtitles: No subtitle providers enabled in settings", 'info')
        return []

    all_results: List[SubtitleResult] = []

    def _query(svc_tuple):
        svc_name, svc_cls = svc_tuple
        try:
            # Query with primary title
            res = svc_cls.search(meta, settings)
            # If no results and an alternative original/romaji title exists, probe secondary title
            if not res and meta.original_title and meta.original_title.lower() != (meta.tvshow or meta.title).lower():
                alt_meta = VideoMeta(
                    title=meta.original_title if meta.is_movie else meta.title,
                    tvshow=meta.original_title if meta.is_tvshow else '',
                    original_title='',
                    season=meta.season,
                    episode=meta.episode,
                    year=meta.year,
                    imdb_id=meta.imdb_id,
                    filename=meta.filename,
                    languages=meta.languages,
                    preferred_lang=meta.preferred_lang,
                    filehash=meta.filehash,
                    filesize=meta.filesize,
                    is_tvshow=meta.is_tvshow,
                )
                res = svc_cls.search(alt_meta, settings)
            return res
        except Exception as e:
            control.log(f"Native Subtitles provider {svc_name} error: {e}", 'warning')
            return []

    # Run in parallel across thread pool
    max_workers = min(len(enabled_services), 8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_query, svc): svc[0] for svc in enabled_services}
        for future in concurrent.futures.as_completed(future_map, timeout=timeout + 5):
            try:
                sub_list = future.result()
                if sub_list:
                    all_results.extend(sub_list)
            except Exception as e:
                control.log(f"Search future exception: {e}", 'warning')

    if not all_results:
        return []

    # Filter strictly to the preferred language
    if meta.preferred_lang and meta.preferred_lang.lower() != 'none':
        filtered: List[SubtitleResult] = []
        for sub in all_results:
            sub_code = (sub.lang_code or languages.to_iso639_1(sub.lang)).lower()
            if languages.is_language_match(sub_code, meta.preferred_lang):
                filtered.append(sub)
        all_results = filtered

    if not all_results:
        control.log(f"Native Subtitles: Zero results matched preferred language '{meta.preferred_lang}'", 'info')
        return []

    # Compute scores for all results
    for sub in all_results:
        score_result(sub, meta, settings)

    # Sort descending by score
    all_results.sort(key=lambda x: -x.score)

    # Deduplicate results with identical name and language
    deduped: List[SubtitleResult] = []
    seen = set()
    for sub in all_results:
        key = (sub.name.lower(), sub.lang_code, sub.service_name)
        if key not in seen:
            seen.add(key)
            deduped.append(sub)

    return deduped[:results_limit]
