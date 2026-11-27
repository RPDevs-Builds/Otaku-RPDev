# -*- coding: utf-8 -*-
"""Defensive JSON decoding helpers shared across Otaku-RPDev add-ons (zero plugin dependencies)."""

import json

_JSON_DEFAULT_SENTINEL = object()


def safe_json(response, default=_JSON_DEFAULT_SENTINEL):
    """Safely parse a response object or string/bytes as JSON, returning ``default`` (or ``{}``) on failure."""
    def_val = {} if default is _JSON_DEFAULT_SENTINEL else default
    if not response:
        return def_val
    if hasattr(response, 'json'):
        try:
            res = response.json()
            return res if res is not None else def_val
        except (ValueError, AttributeError, TypeError, json.JSONDecodeError):
            return def_val
    if isinstance(response, (str, bytes)):
        try:
            res = json.loads(response)
            return res if res is not None else def_val
        except (ValueError, AttributeError, TypeError, json.JSONDecodeError):
            return def_val
    try:
        res = response.json()
        return res if res is not None else def_val
    except (ValueError, AttributeError, TypeError, json.JSONDecodeError):
        return def_val


def loads_json(text, default=None):
    """Safely parse a JSON string, returning ``default`` on error or empty input."""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default
