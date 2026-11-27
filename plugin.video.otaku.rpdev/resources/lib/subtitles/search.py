"""search.py - Multi-Threaded Subtitle Search & Intelligent Ranking Orchestrator
=============================================================================
"""

# -*- coding: utf-8 -*-

import concurrent.futures
import functools
import re
from typing import List, Dict, Any, Optional
from contextlib import nullcontext
from resources.lib.ui import client, control, domains, source_utils
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles.services import ALL_SERVICES
from resources.lib.subtitles import languages


_TITLE_NOISE_RE = re.compile(
    r'\b(?:season\s*\d+|s\d{1,2}(?:e\d{1,4})?|part\s*\d+|cour\s*\d+|'
    r'1080p|720p|480p|2160p|4k|web[\-.]?dl|webrip|bluray|bdrip|x264|x265|hevc|aac|flac|'
    r'the|a|an|of|and|in|on|to)\b',
    re.IGNORECASE,
)


def title_overlap_ratio(target_title: str, candidate_name: str) -> float:
    """Return fraction [0.0..1.0] of significant target title tokens present in candidate_name."""
    if not target_title or not candidate_name:
        return 0.0
    t_clean = _TITLE_NOISE_RE.sub(' ', re.sub(r'[^\w\s]', ' ', target_title.lower()))
    c_clean = re.sub(r'[^\w\s]', ' ', candidate_name.lower())
    t_tokens = [tok for tok in t_clean.split() if len(tok) >= 2 or tok.isdigit()]
    if not t_tokens:
        t_tokens = [tok for tok in re.sub(r'[^\w\s]', ' ', target_title.lower()).split() if tok]
    if not t_tokens:
        return 0.0
    c_tokens = set(c_clean.split())
    matched = sum(1 for tok in t_tokens if tok in c_tokens)
    return matched / float(len(t_tokens))


@functools.lru_cache(maxsize=128)
def _get_episode_patterns(target_s: int, target_e: int):
    s_e_pattern = re.compile(rf'(?:^|[._\s\-\[])s0*{target_s}e0*{target_e}(?:[._\s\-\]]|$)', re.IGNORECASE)
    alt_pattern = re.compile(rf'(?:^|[._\s\-\[])0*{target_s}x0*{target_e}(?:[._\s\-\]]|$)', re.IGNORECASE)
    single_ep_pattern = re.compile(rf'(?:^|[._\s\-\[])e0*{target_e}(?:[._\s\-\]]|$)', re.IGNORECASE)
    anime_dash_ep_pattern = re.compile(rf'(?:^|[\s._])-\s*0*{target_e}(?:v\d)?(?:[\s._\-\[\(]|$)', re.IGNORECASE)
    return s_e_pattern, alt_pattern, single_ep_pattern, anime_dash_ep_pattern


def score_result(sub: SubtitleResult, meta: VideoMeta, settings: Dict[str, Any]) -> float:
    """
    Computes ranking score and auto-identification match metadata for a subtitle result.
    Higher score = better rank.
    """
    score = 0.0
    name_lower = sub.name.lower()
    pref_lang = meta.preferred_lang.lower()
    sub_lang = (sub.lang_code or sub.lang).lower()

    lang_matched = bool(pref_lang and languages.is_language_match(sub_lang, pref_lang))
    exact_ep_match = False
    season_pack_match = False
    ep_mismatch = False
    hash_match = bool(sub.sync and meta.filehash)
    release_match = bool(
        (sub.sync and not meta.filehash)
        or (meta.filename_without_ext and meta.filename_without_ext.lower() in name_lower)
    )

    # 1. Language Preference & Title Relevance
    if lang_matched:
        score += 1.0
    elif sub_lang:
        score -= 1.0

    target_title = (meta.tvshow or meta.title or '').strip()
    title_mismatch = False
    is_anime_native = bool(getattr(sub, 'is_anime_native', False) or sub.service_name in ('jimaku', 'animetosho'))
    native_exact_id = bool(is_anime_native and sub.auto_identified)
    if target_title and not hash_match and not native_exact_id:
        overlap = title_overlap_ratio(target_title, sub.name)
        if overlap >= 0.5:
            score += 0.8
        elif overlap > 0.0:
            score += 0.2
        elif not release_match:
            score -= 2.5
            title_mismatch = True

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
                score += 1.2
                exact_ep_match = True
            elif sub.season == target_s and sub.episode is None:
                # Season pack
                score += 0.4
                season_pack_match = True
            elif sub.episodes_range and target_e in sub.episodes_range:
                # Episode range (e.g. 01-12)
                score += 0.6
                season_pack_match = True
            elif sub.season is not None and sub.episode is not None:
                if sub.season != target_s or sub.episode != target_e:
                    # Mismatched episode/season: strong penalty
                    score -= 1.0
                    ep_mismatch = True

            # Detect explicit conflicting SxxEyy in filename (e.g. S01E33 returned for S01E05)
            explicit_se = re.search(r'(?:^|[._\s\-\[])s0*(\d{1,2})e0*(\d{1,4})(?:[._\s\-\]]|$)', name_lower)
            if explicit_se:
                fn_s, fn_e = int(explicit_se.group(1)), int(explicit_se.group(2))
                if fn_s != target_s or fn_e != target_e:
                    score -= 1.5
                    exact_ep_match = False
                    ep_mismatch = True

            # Regex search in filename
            s_e_pattern, alt_pattern, single_ep_pattern, anime_dash_ep_pattern = _get_episode_patterns(target_s, target_e)

            if not ep_mismatch:
                if s_e_pattern.search(name_lower) or alt_pattern.search(name_lower):
                    score += 0.8
                    exact_ep_match = True
                elif single_ep_pattern.search(name_lower):
                    score += 0.6
                    exact_ep_match = True
                elif f"s{target_s:02d}" in name_lower and f"e{target_e:02d}" in name_lower:
                    score += 0.7
                    exact_ep_match = True
                elif not explicit_se and anime_dash_ep_pattern.search(name_lower):
                    score += 0.6
                    exact_ep_match = True

    # 3. Filename / Hash match
    if sub.sync:
        score += 0.5
    elif release_match:
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
    has_forced_marker = (
        sub.forced
        or bool(getattr(sub, 'is_signs_only', False))
        or any(kw in name_lower for kw in ('forced', 'signs', 'songs'))
    )
    if prefer_forced:
        if has_forced_marker:
            score += 0.3
        else:
            score -= 0.2
    else:
        if has_forced_marker:
            score -= 0.8 if getattr(sub, 'is_signs_only', False) else 0.3
        else:
            score += 0.2

    # 5b. Anime-Native Provider Trust, Styled .ass Preference & Release-Group Match
    group_matched = False
    if not title_mismatch and not ep_mismatch:
        if is_anime_native:
            score += 0.75
        sub_fmt = str(getattr(sub, 'subtitle_format', '') or '').lower()
        if not sub_fmt:
            low_clean = name_lower
            for comp in ('.xz', '.gz', '.zip'):
                if low_clean.endswith(comp):
                    low_clean = low_clean[:-len(comp)]
            if low_clean.endswith(('.ass', '.ssa')):
                sub_fmt = 'ass'
        if sub_fmt in ('ass', 'ssa') and not has_forced_marker:
            score += 0.55

        sub_group = source_utils.normalize_release_group(
            getattr(sub, 'release_group', '') or source_utils.extract_release_group(sub.name)
        )
        target_groups = set()
        for g in (
            source_utils.normalize_release_group(getattr(meta, 'release_group', '')),
            source_utils.normalize_release_group(source_utils.extract_release_group(meta.filename)),
        ):
            if g:
                target_groups.add(g)
        target_groups.update(source_utils.parse_release_group_set(getattr(meta, 'preferred_group', '')))
        if not getattr(meta, 'preferred_group', ''):
            target_groups.update(
                source_utils.parse_release_group_set(control.getSetting('general.release_group.preferred') or '')
            )
        if sub_group and sub_group in target_groups:
            score += 1.2
            group_matched = True
            sub.sync = True

    # 6. Provider Quality Rating
    if sub.rating > 0:
        score += (sub.rating / 10.0)

    # 7. Auto-Identification Classification & Reason Badge
    if title_mismatch:
        sub.auto_identified = False
        sub.match_confidence = 'low'
        sub.match_reason = 'Title Mismatch'
    elif ep_mismatch:
        sub.auto_identified = False
        sub.match_confidence = 'low'
        sub.match_reason = 'Mismatch'
    elif hash_match:
        sub.auto_identified = True
        sub.match_confidence = 'exact'
        sub.match_reason = 'Hash Match'
    elif group_matched and (not meta.is_tvshow or exact_ep_match or native_exact_id or not meta.episode):
        sub.auto_identified = True
        sub.match_confidence = 'exact'
        sub.match_reason = 'Release Group'
    elif release_match and (not meta.is_tvshow or exact_ep_match or not meta.episode):
        sub.auto_identified = True
        sub.match_confidence = 'exact'
        sub.match_reason = 'Release Match'
    elif native_exact_id:
        sub.auto_identified = True
        sub.match_confidence = 'exact'
        sub.match_reason = sub.match_reason or sub.display_name
    elif not meta.is_manual_search and exact_ep_match:
        sub.auto_identified = True
        sub.match_confidence = 'exact' if meta.imdb_id else 'high'
        sub.match_reason = 'Exact Ep'
    elif not meta.is_manual_search and season_pack_match:
        sub.auto_identified = True
        sub.match_confidence = 'high'
        sub.match_reason = 'Season Pack'
    elif not meta.is_manual_search and meta.is_movie and meta.imdb_id and lang_matched:
        sub.auto_identified = True
        sub.match_confidence = 'high'
        sub.match_reason = 'IMDb Match'
    elif meta.is_manual_search:
        if exact_ep_match:
            sub.auto_identified = True
            sub.match_confidence = 'high'
            sub.match_reason = 'Exact Ep'
        else:
            sub.auto_identified = False
            sub.match_confidence = 'manual'
            sub.match_reason = 'Manual'
    else:
        sub.auto_identified = False
        sub.match_confidence = 'medium' if score >= 1.0 else 'low'
        sub.match_reason = ''

    sub.score = score
    return score


def search_all_services(meta: VideoMeta, settings: Dict[str, Any]) -> List[SubtitleResult]:
    """
    Queries all enabled subtitle services in parallel, applies intelligent scoring,
    and returns sorted results with auto-identified matches prioritized first.
    """
    if not meta.is_manual_search and (not meta.preferred_lang or meta.preferred_lang.lower() == 'none'):
        control.log("Native Subtitles: Preferred subtitle language is 'none', skipping external provider queries", 'info')
        return []

    timeout = float(settings.get('subtitles.timeout', 15) or 15)
    results_limit = int(settings.get('subtitles.results_limit', 20) or 20)

    enabled_services = []
    for service_name, service_cls in ALL_SERVICES.items():
        # Check setting: subtitles.provider.<service_name>
        setting_key = f"subtitles.provider.{service_name}"
        if settings.get(setting_key, True):
            if domains.adaptive_circuit_breaker.is_tripped(f"sub_{service_name}", category="subtitle"):
                control.log(f"Native Subtitles: Skipping tripped provider {service_name}", 'debug')
                continue
            enabled_services.append((service_name, service_cls))

    if not enabled_services:
        control.log("Native Subtitles: No subtitle providers enabled in settings", 'info')
        return []

    all_results: List[SubtitleResult] = []

    def _query(svc_tuple):
        svc_name, svc_cls = svc_tuple
        gate_ctx = client.bypass_connectivity_gate() if hasattr(client, 'bypass_connectivity_gate') else nullcontext()
        try:
            with gate_ctx:
                # Query with primary title
                res = svc_cls.search(meta, settings)
                # If no results and an alternative original/romaji title exists, probe secondary title
                if not res and not meta.is_manual_search and meta.original_title and meta.original_title.lower() != (meta.tvshow or meta.title).lower():
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
                        mal_id=meta.mal_id,
                        anilist_id=getattr(meta, 'anilist_id', ''),
                        anidb_id=getattr(meta, 'anidb_id', ''),
                        anidb_ep_id=getattr(meta, 'anidb_ep_id', ''),
                        kitsu_id=getattr(meta, 'kitsu_id', ''),
                        release_group=getattr(meta, 'release_group', ''),
                        preferred_group=getattr(meta, 'preferred_group', ''),
                    )
                    res = svc_cls.search(alt_meta, settings)
            domains.adaptive_circuit_breaker.record_success(f"sub_{svc_name}", category="subtitle")
            return res
        except Exception as e:
            domains.adaptive_circuit_breaker.record_failure(f"sub_{svc_name}", category="subtitle")
            control.log(f"Native Subtitles provider {svc_name} error: {e}", 'warning')
            return []

    # Run in parallel across thread pool
    max_workers = min(len(enabled_services), 8)
    provider_counts: Dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_query, svc): svc[0] for svc in enabled_services}
        try:
            for future in concurrent.futures.as_completed(future_map, timeout=timeout + 5):
                svc_name = future_map[future]
                try:
                    sub_list = future.result()
                    provider_counts[svc_name] = len(sub_list) if sub_list else 0
                    if sub_list:
                        all_results.extend(sub_list)
                except Exception as e:
                    provider_counts[svc_name] = 0
                    control.log(f"Search future exception ({svc_name}): {e}", 'warning')
        except concurrent.futures.TimeoutError:
            control.log("Native Subtitles: search_all_services timeout exceeded", 'warning')

    if provider_counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(provider_counts.items()))
        control.log(f"Native Subtitles: Provider results: {summary}", 'info')

    if not all_results:
        return []

    # Filter to requested language(s):
    # - Multi-language Kodi DialogSubtitles queries (len(meta.languages) > 1): allow any requested language
    # - Single-language / automatic queries: filter strictly to preferred_lang
    allowed_langs = set()
    if meta.languages and len(meta.languages) > 1:
        for req_l in meta.languages:
            code = languages.to_iso639_1(req_l)
            if code:
                allowed_langs.add(code.lower())
    if meta.preferred_lang and meta.preferred_lang.lower() != 'none':
        allowed_langs.add(languages.to_iso639_1(meta.preferred_lang).lower())
    elif meta.languages:
        for req_l in meta.languages:
            code = languages.to_iso639_1(req_l)
            if code:
                allowed_langs.add(code.lower())

    if allowed_langs:
        filtered: List[SubtitleResult] = []
        for sub in all_results:
            sub_code = (sub.lang_code or languages.to_iso639_1(sub.lang)).lower()
            if any(languages.is_language_match(sub_code, target) for target in allowed_langs):
                filtered.append(sub)
        all_results = filtered

    if not all_results:
        control.log(f"Native Subtitles: Zero results matched requested languages '{sorted(allowed_langs)}'", 'info')
        return []

    # Compute scores & auto-identification flags for all results
    for sub in all_results:
        score_result(sub, meta, settings)

    # Drop explicit episode-mismatched results when at least one non-mismatched result exists
    non_mismatched = [s for s in all_results if getattr(s, 'match_reason', '') not in ('Mismatch', 'Title Mismatch')]
    if non_mismatched:
        all_results = non_mismatched

    # Sort descending: auto-identified matches first, then highest score
    all_results.sort(key=lambda x: (-int(x.auto_identified), -x.score))

    # Deduplicate results with identical name, language, and provider
    deduped: List[SubtitleResult] = []
    seen = set()
    for sub in all_results:
        key = (sub.name.lower(), sub.lang_code, sub.service_name)
        if key not in seen:
            seen.add(key)
            deduped.append(sub)

    return deduped[:results_limit]
