"""download.py - Subtitle Downloader, Archive Extractor & Storage Manager
========================================================================
"""

# -*- coding: utf-8 -*-

import os
import re
import time
from typing import Optional, Dict, Any
import xbmc
import xbmcvfs
from resources.lib.ui import control, embed_extractor
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.subtitles.services import ALL_SERVICES
from resources.lib.subtitles.archive import extract_subtitle_from_archive, ArchiveEpisodeMismatchError
from resources.lib.subtitles.encoding import fix_subtitle_encoding

SUBTITLE_TEMP_DIR = os.path.join(control.dataPath, 'temp', 'subtitles')


def _strip_sdh_text_segment(text: str) -> str:
    """Strip SDH bracketed/parenthesized cues and ALL-CAPS speaker prefixes while protecting ASS {...} tags."""
    if not text:
        return text
    placeholders = {}

    def _protect_tag(m):
        key = f'\x00ASSTAG{len(placeholders)}\x00'
        placeholders[key] = m.group(0)
        return key

    cleaned = re.sub(r'\{[^}\n]*\}', _protect_tag, text)
    cleaned = re.sub(r'\[[^\]\n]{1,48}\]', '', cleaned)
    cleaned = re.sub(r'\([^\)\n]{1,48}\)', '', cleaned)
    cleaned = re.sub(
        r'^((?:[ \t]*\x00ASSTAG\d+\x00)*)[ \t]*[A-Z][A-Z0-9 _\-\.]{1,20}:\s*',
        r'\1',
        cleaned,
    )
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned).strip()
    for key, val in placeholders.items():
        cleaned = cleaned.replace(key, val)
    return cleaned


def strip_sdh_hearing_impaired_tags(sub_text: str) -> str:
    """Strip SDH hearing-impaired bracketed sound effects ([sighs], (applause)) and speaker prefixes.

    For ASS/SSA scripts, operates strictly on the dialogue text field (after the 9th comma
    on ``Dialogue:`` lines) while preserving ``[Section]`` headers, ``Style:`` definitions,
    and all ``{...}`` override tags intact.
    """
    if not sub_text:
        return sub_text

    # Detect ASS/SSA content: restrict SDH stripping strictly to Dialogue text field (col 10+)
    if re.search(r'(?mi)^\[(?:Script Info|V4\+? Styles|Events)\][ \t]*$', sub_text) or re.search(r'(?m)^Dialogue:', sub_text):
        out_lines = []
        for raw_line in sub_text.splitlines():
            if raw_line.startswith('Dialogue:'):
                parts = raw_line.split(',', 9)
                if len(parts) == 10:
                    prefix = ','.join(parts[:9])
                    cleaned_text = _strip_sdh_text_segment(parts[9])
                    out_lines.append(f"{prefix},{cleaned_text}")
                    continue
            out_lines.append(raw_line)
        result = '\n'.join(out_lines)
        if sub_text.endswith('\n'):
            result += '\n'
        return result

    cleaned = re.sub(r'\[[^\]\n]{1,48}\]', '', sub_text)
    cleaned = re.sub(r'\([^\)\n]{1,48}\)', '', cleaned)
    cleaned = re.sub(
        r'(?m)^[ \t]*[A-Z][A-Z0-9 _\-\.]{1,20}:\s*',
        '',
        cleaned,
    )
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    return cleaned


def sanitize_filename(name: str) -> str:
    """Strip illegal filesystem characters from a subtitle filename."""
    clean = re.sub(r'[\\/*?:"<>|]', '_', name)
    clean = re.sub(r'\s+', '_', clean)
    return clean.strip('_')


def purge_temp_subtitles(target_dir: Optional[str] = None):
    """Wipes all cached temporary subtitles from addon temp directory."""
    purge_dir = target_dir or SUBTITLE_TEMP_DIR
    try:
        if os.path.exists(purge_dir):
            for fname in os.listdir(purge_dir):
                fpath = os.path.join(purge_dir, fname)
                try:
                    if os.path.isfile(fpath):
                        if hasattr(xbmcvfs, 'delete'):
                            xbmcvfs.delete(fpath)
                        if os.path.exists(fpath):
                            os.remove(fpath)
                except Exception:
                    pass
    except Exception as e:
        control.log(f"Failed to purge temp subtitles: {e}", 'warning')


_SRT_VTT_TS_RE = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})([,\.])(\d{3})')
_ASS_TS_RE = re.compile(r'(\d+):(\d{2}):(\d{2})\.(\d{2})')


def _fmt_srt_vtt(sec: float, sep: str) -> str:
    ms_total = max(0, int(round(sec * 1000.0)))
    hh, rem = divmod(ms_total, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ms:03d}"


def _fmt_ass(sec: float) -> str:
    cs_total = max(0, int(round(sec * 100.0)))
    hh, rem = divmod(cs_total, 360000)
    mm, rem = divmod(rem, 6000)
    ss, cs = divmod(rem, 100)
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"


def _max_subtitle_timestamp_seconds(sub_text: str, ext: str) -> float:
    max_s = 0.0
    if ext in ('.ass', '.ssa'):
        for m in _ASS_TS_RE.finditer(sub_text):
            s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100.0
            if s > max_s:
                max_s = s
    else:
        for m in _SRT_VTT_TS_RE.finditer(sub_text):
            s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(5)) / 1000.0
            if s > max_s:
                max_s = s
    return max_s


def rescale_subtitle_timestamps(sub_text: str, ext: str, ratio: float) -> str:
    """Rescale subtitle cue timestamps by *ratio* (e.g., 23.976 / 25.000) for FPS-matched sync."""
    if not sub_text or abs(ratio - 1.0) < 1e-5:
        return sub_text
    if ext in ('.ass', '.ssa'):
        def _rep_ass(m):
            s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100.0
            return _fmt_ass(s * ratio)
        return _ASS_TS_RE.sub(_rep_ass, sub_text)

    def _rep_srt(m):
        s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(5)) / 1000.0
        return _fmt_srt_vtt(s * ratio, m.group(4))
    return _SRT_VTT_TS_RE.sub(_rep_srt, sub_text)


def shift_subtitle_timestamps(sub_text: str, ext: str, offset_ms: int) -> str:
    """Shift all subtitle cue timestamps uniformly by *offset_ms* milliseconds, clamping >= 0."""
    if not sub_text or not offset_ms:
        return sub_text
    delta_s = float(offset_ms) / 1000.0
    if abs(delta_s) < 1e-4:
        return sub_text
    if str(ext or '').lower() in ('.ass', '.ssa'):
        def _shift_ass(m):
            s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100.0
            return _fmt_ass(max(0.0, s + delta_s))
        return _ASS_TS_RE.sub(_shift_ass, sub_text)

    def _shift_srt(m):
        s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(5)) / 1000.0
        return _fmt_srt_vtt(max(0.0, s + delta_s), m.group(4))
    return _SRT_VTT_TS_RE.sub(_shift_srt, sub_text)


_ASS_DRAW_POS_RE = re.compile(r'\\(?:pos|move|org|clip|iclip|fad|fade|p[1-9]\d*)\b', re.IGNORECASE)
_SIGN_STYLE_WORDS = ('sign', 'title', 'op', 'ed', 'lyric', 'kara', 'note', 'typeset', 'caption')


def _parse_dialogue_cues_seconds(sub_text: str, ext: str):
    """Extract clean non-signs dialogue intervals as sorted [(start_s, end_s), ...]."""
    cues = []
    norm_ext = str(ext or '').lower()
    if norm_ext in ('.ass', '.ssa'):
        for raw_line in sub_text.splitlines():
            line = raw_line.strip()
            if not line.startswith('Dialogue:'):
                continue
            parts = line[9:].split(',', 9)
            if len(parts) < 10:
                continue
            style = parts[3].strip().lower()
            text_body = parts[9]
            if any(w in style for w in _SIGN_STYLE_WORDS):
                continue
            if _ASS_DRAW_POS_RE.search(text_body):
                continue
            m_s = _ASS_TS_RE.search(parts[1])
            m_e = _ASS_TS_RE.search(parts[2])
            if not (m_s and m_e):
                continue
            s_val = int(m_s.group(1)) * 3600 + int(m_s.group(2)) * 60 + int(m_s.group(3)) + int(m_s.group(4)) / 100.0
            e_val = int(m_e.group(1)) * 3600 + int(m_e.group(2)) * 60 + int(m_e.group(3)) + int(m_e.group(4)) / 100.0
            plain = re.sub(r'\{[^}]*\}', '', text_body).strip()
            if plain and e_val > s_val:
                cues.append((s_val, e_val))
    else:
        ts_line_re = re.compile(
            r'(\d{1,2}):(\d{2}):(\d{2})([,\.])(\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})([,\.])(\d{3})'
        )
        blocks = re.split(r'\r?\n\s*\r?\n', sub_text.strip())
        for blk in blocks:
            m = ts_line_re.search(blk)
            if not m:
                continue
            s_val = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(5)) / 1000.0
            e_val = int(m.group(6)) * 3600 + int(m.group(7)) * 60 + int(m.group(8)) + int(m.group(10)) / 1000.0
            if (e_val - s_val) < 0.4:
                continue
            body_lines = [ln.strip() for ln in blk[m.end():].splitlines() if ln.strip()]
            body = re.sub(r'<[^>]+>', '', ' '.join(body_lines)).strip()
            if not body:
                continue
            if _ASS_DRAW_POS_RE.search(body):
                continue
            # Ignore bracketed sound/sign cues if enclosed
            if body.startswith('[') and body.endswith(']'):
                continue
            if e_val > s_val:
                cues.append((s_val, e_val))
    cues.sort(key=lambda item: item[0])
    return cues


def _parse_ass_sign_title_cues_seconds(sub_text: str, ext: str):
    """Extract non-dialogue ASS/SSA Title/Sign intervals as sorted [(start_s, end_s), ...]
    for post-OP title card false-positive guards."""
    norm_ext = str(ext or '').lower()
    if norm_ext not in ('.ass', '.ssa') or not sub_text:
        return []
    sign_cues = []
    for raw_line in sub_text.splitlines():
        line = raw_line.strip()
        if not line.startswith('Dialogue:'):
            continue
        parts = line[9:].split(',', 9)
        if len(parts) < 10:
            continue
        style = parts[3].strip().lower()
        text_body = parts[9]
        if not (any(w in style for w in ('sign', 'title', 'caption')) or _ASS_DRAW_POS_RE.search(text_body)):
            continue
        m_s = _ASS_TS_RE.search(parts[1])
        m_e = _ASS_TS_RE.search(parts[2])
        if not (m_s and m_e):
            continue
        s_val = int(m_s.group(1)) * 3600 + int(m_s.group(2)) * 60 + int(m_s.group(3)) + int(m_s.group(4)) / 100.0
        e_val = int(m_e.group(1)) * 3600 + int(m_e.group(2)) * 60 + int(m_e.group(3)) + int(m_e.group(4)) / 100.0
        plain = re.sub(r'\{[^}]*\}', '', text_body).strip()
        if plain and e_val > s_val:
            sign_cues.append((s_val, e_val))
    sign_cues.sort(key=lambda item: item[0])
    return sign_cues


def _scene_marker_kind(marker) -> str:
    """Return normalized scene marker kind/type across both player.py ('kind') and legacy ('type') schemas."""
    if not isinstance(marker, dict):
        return ''
    return str(marker.get('type') or marker.get('kind') or '').strip().lower()


def detect_chapter_aligned_subtitle_offset_ms(
    sub_text: str,
    ext: str,
    scene_markers=None,
    video_total_s: float = 0.0,
) -> int:
    """
    Detect bounded broadcast-vs-BD/commercial-bumper shift (+-3s..+-12s) requiring
    multi-boundary corroboration between dialogue silence gaps and Kodi 22 / AniSkip chapter markers.
    Also handles OP-at-0s episodes (intro_start <= 2.0s) via leading OP-end gap alignment while
    preserving false-positive protection against silent post-OP title cards.
    Returns 0 cleanly when ambiguous, out-of-range, or uncorroborated.
    """
    if not sub_text:
        return 0
    if scene_markers is None:
        raw = control.playerWindow.getProperty('otaku.scene_markers')
        scene_markers = control.loads_json(raw, default=[]) if raw else []
    if not isinstance(scene_markers, list) or not scene_markers:
        return 0

    intro_marker = next(
        (m for m in scene_markers if _scene_marker_kind(m) in ('intro', 'op') and m.get('end')),
        None,
    )
    outro_marker = next(
        (m for m in scene_markers if _scene_marker_kind(m) in ('outro', 'ed') and m.get('start')),
        None,
    )
    if not intro_marker:
        return 0

    try:
        intro_start = float(intro_marker.get('start') or 0.0)
        intro_end = float(intro_marker.get('end') or 0.0)
    except (TypeError, ValueError):
        return 0
    intro_dur = intro_end - intro_start
    if intro_dur < 30.0:
        return 0

    cues = _parse_dialogue_cues_seconds(sub_text, ext)
    if len(cues) < 3:
        return 0

    outro_start = 0.0
    if outro_marker:
        try:
            outro_start = float(outro_marker.get('start') or 0.0)
        except (TypeError, ValueError):
            outro_start = 0.0

    try:
        vid_total = float(video_total_s or 0.0)
    except (TypeError, ValueError):
        vid_total = 0.0

    # Find OP-sized silence gaps in non-signs dialogue cues
    min_gap_s = max(30.0, intro_dur * 0.65)
    gap_windows = []
    if intro_start <= 2.0 and cues[0][0] >= min_gap_s:
        # Episode starts immediately with OP (e.g. intro 0-90s): evaluate leading OP-end gap
        gap_windows.append((0.0, cues[0][0], True))
    for idx in range(len(cues) - 1):
        gap_windows.append((cues[idx][1], cues[idx + 1][0], False))

    sign_cues = None
    candidates = []
    for pre_end, post_start, is_leading in gap_windows:
        gap_len = post_start - pre_end
        if gap_len < min_gap_s or post_start > (intro_end + 30.0) or pre_end < max(0.0, intro_start - 30.0):
            continue
        delta_s = intro_end - post_start
        delta_ms = int(round(delta_s * 1000.0))
        if not (3000 <= abs(delta_ms) <= 12000):
            continue

        post_aligned = abs((post_start + delta_s) - intro_end) <= 1.5
        outro_corroborated = False
        if outro_start > intro_end + 60.0:
            outro_corroborated = any(
                abs((c_end + delta_s) - outro_start) <= 1.5
                for c_end in (c[1] for c in cues)
            )

        if not is_leading:
            # Standard multi-boundary corroboration (tolerance +-1500 ms = 1.5s):
            # 1) intro_start + intro_end must both align with the shifted dialogue gap, OR
            # 2) outro_start corroborates the same delta_s.
            pre_aligned = abs((pre_end + delta_s) - intro_start) <= 1.5
            if (pre_aligned and post_aligned) or (post_aligned and outro_corroborated):
                candidates.append((abs(delta_ms), delta_ms))
        else:
            # Leading OP gap (intro_start <= 2.0s, no spoken dialogue before OP):
            # 1) Outro corroboration accepts both early (+) and late (-) shifts.
            # 2) Positive shift (delta_ms > 0, dialogue starts early inside OP music): safe directly,
            #    because a silent post-OP title card can only delay dialogue, never make it start early.
            # 3) Negative shift (delta_ms < 0, dialogue starts after intro_end) without outro:
            #    require duration-overflow corroboration and no synced ASS title/sign card at intro_end.
            if post_aligned and outro_corroborated:
                candidates.append((abs(delta_ms), delta_ms))
            elif post_aligned and delta_ms > 0:
                candidates.append((abs(delta_ms), delta_ms))
            elif post_aligned and delta_ms < 0 and vid_total > 300.0:
                if sign_cues is None:
                    sign_cues = _parse_ass_sign_title_cues_seconds(sub_text, ext)
                has_synced_title_card = any(
                    (intro_end - 1.5) <= s_start <= (intro_end + 2.5)
                    for s_start, _ in sign_cues
                )
                last_cue_end = cues[-1][1]
                duration_overflow_corroborated = (
                    last_cue_end > (vid_total + 1.5)
                    and (last_cue_end + delta_s) <= (vid_total + 2.0)
                )
                if duration_overflow_corroborated and not has_synced_title_card:
                    candidates.append((abs(delta_ms), delta_ms))

    if len(candidates) != 1:
        # Reject ambiguous/zero-match cases cleanly
        return 0
    return candidates[0][1]


def _get_player_fps_and_duration():
    """Return (video_fps, total_seconds) for the active Kodi player, or (0.0, 0.0)."""
    try:
        player = xbmc.Player()
        if not player.isPlaying():
            return 0.0, 0.0
        total_s = float(player.getTotalTime() or 0.0)
        fps_str = str(xbmc.getInfoLabel('Player.Process(VideoFps)') or '').strip()
        fps = float(fps_str) if fps_str else 0.0
        return fps, total_s
    except Exception:
        return 0.0, 0.0


def download_and_prepare_subtitle(
    result: SubtitleResult,
    meta: VideoMeta,
    settings: Dict[str, Any],
    dest_dir: Optional[str] = None,
) -> Optional[str]:
    """
    Downloads, extracts from archive if needed, transcodes to UTF-8,
    and writes to isolated addon temp directory with Kodi VFS cache registration.
    Returns the absolute path of the local subtitle file, or None on failure.
    """
    service_cls = ALL_SERVICES.get(result.service_name)
    if not service_cls:
        control.log(f"Unknown subtitle provider: {result.service_name}", 'warning')
        return None

    target_dir = dest_dir or SUBTITLE_TEMP_DIR

    # Ensure temp dir exists via both xbmcvfs (updates Kodi VFS) and os.makedirs
    try:
        if hasattr(xbmcvfs, 'mkdirs'):
            xbmcvfs.mkdirs(target_dir)
    except Exception:
        pass
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    try:
        raw_bytes = service_cls.download(result, settings)
        if not raw_bytes:
            control.log(f"Provider {result.service_name} returned empty download content", 'warning')
            return None

        # Extract from archive if compressed (.zip / .gz) with strict episode matching
        sub_content, inner_filename = extract_subtitle_from_archive(
            raw_bytes,
            filename=result.name,
            episode_number=meta.episode,
            season_number=meta.season,
        )

        # Transcode encoding to UTF-8
        use_chardet = settings.get('subtitles.use_chardet', True)
        utf8_text, detected_enc = fix_subtitle_encoding(sub_content, use_chardet=use_chardet)

        if settings.get('subtitles.strip_sdh_tags', False) or control.getBool('subtitles.strip_sdh_tags', False):
            utf8_text = strip_sdh_hearing_impaired_tags(utf8_text)

        # Strip archive compression suffixes (.xz / .gz / .zip) before Kodi 22 cue validation
        validation_name = str(inner_filename or result.name or result.download_url or '')
        for _comp_ext in ('.xz', '.gz', '.zip'):
            if validation_name.lower().endswith(_comp_ext):
                validation_name = validation_name[:-len(_comp_ext)]

        # Validate & normalize against Kodi 22 CDVDFactorySubtitle::CreateParser() contract
        normalized_text, detected_ext, reject_reason = embed_extractor._validate_and_normalize_sub_content(
            utf8_text,
            validation_name,
            source_url=result.download_url,
        )
        if not normalized_text:
            control.log(
                f"Native Subtitles: Rejected invalid subtitle payload from {result.service_name} "
                f"({result.name}): {reject_reason}",
                'warning',
            )
            return None

        # Determine target extension (.ass, .ssa, .vtt, .srt)
        ext = detected_ext or '.srt'
        if not ext.startswith('.'):
            ext = f'.{ext}'

        # Prevent PAL 25fps speed-up drift when playing 25fps streams with 23.976fps external subs
        video_fps, total_time = _get_player_fps_and_duration()
        src_label_low = f"{inner_filename or ''} {result.name or ''}".lower()
        if 24.8 <= video_fps <= 25.2 and not any(tag in src_label_low for tag in ('25fps', '25.000', 'pal')):
            max_sub_s = _max_subtitle_timestamp_seconds(normalized_text, ext)
            if max_sub_s > 60.0 and total_time > 300.0 and max_sub_s > total_time * 1.03:
                ratio = 23.976 / video_fps
                normalized_text = rescale_subtitle_timestamps(normalized_text, ext, ratio)
                control.log(
                    f"Native Subtitles: Rescaled 23.976fps -> {video_fps:.3f}fps "
                    f"(ratio={ratio:.5f}, max_sub={max_sub_s:.1f}s, video={total_time:.1f}s)",
                    'info',
                )

        # WS-5: Apply persisted per-series sub_offset_ms or opt-in chapter-aligned calibration
        mal_id = getattr(meta, 'mal_id', None) or control.getGlobalProp('otaku.mal_id')
        persisted_offset_ms = 0
        if mal_id and str(mal_id).isdigit():
            try:
                from resources.lib.ui import database
                ov = database.get_series_override(mal_id)
                if isinstance(ov, dict):
                    persisted_offset_ms = int(ov.get('sub_offset_ms') or 0)
            except Exception:
                persisted_offset_ms = 0

        series_shift_ms = persisted_offset_ms
        if series_shift_ms == 0 and (
            settings.get('subtitles.auto_calibrate_chapters', False)
            or control.getBool('subtitles.auto_calibrate_chapters', False)
        ):
            calibrated_ms = detect_chapter_aligned_subtitle_offset_ms(
                normalized_text,
                ext,
                video_total_s=total_time,
            )
            if calibrated_ms:
                series_shift_ms = calibrated_ms
                if mal_id and str(mal_id).isdigit():
                    try:
                        from resources.lib.ui import database
                        database.update_series_sub_offset(mal_id, calibrated_ms)
                    except Exception:
                        pass
                control.log_metric(
                    'sub_calibrate',
                    level='info',
                    mal_id=mal_id or 0,
                    offset_ms=calibrated_ms,
                    source='chapter_align',
                )

        # Prevent double-shifting when Kodi already holds a per-file SubtitleDelay for this URL
        try:
            initial_kodi_delay_ms = int(control.playerWindow.getProperty('otaku.subtitle.initial_kodi_delay_ms') or 0)
        except (TypeError, ValueError):
            initial_kodi_delay_ms = 0
        effective_bake_ms = series_shift_ms - initial_kodi_delay_ms

        if effective_bake_ms != 0:
            normalized_text = shift_subtitle_timestamps(normalized_text, ext, effective_bake_ms)
            control.log(
                f"Native Subtitles: Applied {effective_bake_ms:+d}ms subtitle timing shift "
                f"(series_offset={series_shift_ms:+d}ms, kodi_delay={initial_kodi_delay_ms:+d}ms)",
                'info',
            )

        # Construct sanitized filename with unique per-download sub_tag nonce
        # to avoid Kodi 22 special://temp/ g_directoryCache stale-file collisions
        base_name = meta.filename_without_ext or sanitize_filename(result.name) or 'subtitle'
        lang_code = result.lang_code or 'en'
        sub_nonce = int(time.time() * 1000)
        target_filename = f"{sanitize_filename(base_name)}.{lang_code}.{sub_nonce}{ext}"
        dest_path = os.path.join(target_dir, target_filename)

        if control.atomic_write_text(dest_path, normalized_text) is False:
            control.log(f"Native Subtitles: Failed to atomically write {dest_path}", 'error')
            return None

        # Defensive VFS visibility check: if Kodi C++ g_directoryCache still hides
        # dest_path (e.g., cached by another addon), force CFile::OpenForWrite() so
        # g_directoryCache.AddFile(dest_path) runs before CFile::Open / OnDownloadComplete.
        try:
            if hasattr(xbmcvfs, 'exists') and not xbmcvfs.exists(dest_path):
                vfs_file = xbmcvfs.File(dest_path, 'w')
                try:
                    vfs_file.write(normalized_text.encode('utf-8'))
                finally:
                    vfs_file.close()
        except Exception as vfs_err:
            control.log(f"Native Subtitles: VFS visibility sync warning for {dest_path}: {vfs_err}", 'debug')

        try:
            control.playerWindow.setProperty('otaku.subtitle.external_attached', 'true')
            control.playerWindow.setProperty('otaku.subtitle.baked_offset_ms', str(effective_bake_ms))
        except Exception:
            pass

        control.log(f"Native Subtitles: Downloaded and prepared {dest_path} (enc={detected_enc})", 'info')
        return dest_path

    except ArchiveEpisodeMismatchError as e:
        control.log(f"Native Subtitles: Skipped {result.name} - {e}", 'debug')
        return None
    except Exception as e:
        control.log(f"Native Subtitles: Download/preparation error for {result.name}: {e}", 'error')
        return None
