# -*- coding: utf-8 -*-
"""Structured single-line OTAKU_METRIC telemetry formatting and logging (zero plugin dependencies)."""

import re

import xbmc

_METRIC_TOKEN_RE = re.compile(r'[^A-Za-z0-9_.\-/:]+')


def format_metric_line(event, **fields):
    """Format a sanitized single-line ``OTAKU_METRIC event=<name> ...`` log payload."""
    clean_event = _METRIC_TOKEN_RE.sub('_', str(event or 'unknown').strip()) or 'unknown'
    parts = [f"OTAKU_METRIC event={clean_event}"]
    for k in sorted(fields.keys()):
        v = fields[k]
        if v is None:
            continue
        clean_k = _METRIC_TOKEN_RE.sub('_', str(k).strip())
        if not clean_k:
            continue
        if isinstance(v, bool):
            clean_v = 'true' if v else 'false'
        elif isinstance(v, float):
            clean_v = f"{v:.3f}".rstrip('0').rstrip('.') if '.' in f"{v:.3f}" else str(v)
        else:
            raw_v = str(v).replace('\r', ' ').replace('\n', ' ').strip()
            clean_v = _METRIC_TOKEN_RE.sub('_', raw_v) if raw_v else 'none'
        parts.append(f"{clean_k}={clean_v}")
    return ' '.join(parts)


def log_metric(event, level='info', logger_fn=None, **fields):
    """Emit a single-line structured OTAKU_METRIC key=value telemetry marker."""
    line = format_metric_line(event, **fields)
    if logger_fn is not None:
        logger_fn(line, level=level)
        return line

    lvl_map = {
        'info': xbmc.LOGINFO,
        'warning': xbmc.LOGWARNING,
        'error': xbmc.LOGERROR,
        'debug': xbmc.LOGDEBUG,
    }
    try:
        xbmc.log(f"OTAKU RPDEV SERVICE (0): {line}", lvl_map.get(level, xbmc.LOGNONE))
    except Exception:
        pass
    return line
