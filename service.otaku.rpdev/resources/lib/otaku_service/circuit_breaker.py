# -*- coding: utf-8 -*-
"""Unified Adaptive Provider Circuit Breaker (NF-04) shared leaf module (zero plugin dependencies)."""

import json
import threading
import time

import xbmc
import xbmcgui

from otaku_service import connectivity, safe_json


def _default_get_prop(key):
    try:
        return xbmcgui.Window(10000).getProperty(key)
    except Exception:
        return ''


def _default_set_prop(key, value):
    try:
        xbmcgui.Window(10000).setProperty(key, str(value))
    except Exception:
        pass


def _default_clear_prop(key):
    try:
        xbmcgui.Window(10000).clearProperty(key)
    except Exception:
        pass


def _default_log(msg, level='debug'):
    lvl_map = {
        'info': xbmc.LOGINFO,
        'warning': xbmc.LOGWARNING,
        'error': xbmc.LOGERROR,
        'debug': xbmc.LOGDEBUG,
    }
    try:
        xbmc.log(f"OTAKU RPDEV SERVICE (0): {msg}", lvl_map.get(level, xbmc.LOGDEBUG))
    except Exception:
        pass


class AdaptiveCircuitBreaker:
    """Unified adaptive circuit breaker across torrent, embed, subtitle, metadata, and debrid providers.

    Uses exponential cooldowns (300s -> 900s -> 3600s), half-open recovery probes,
    and Kodi Window(10000) persistence.
    """

    _PROP_KEY = 'otaku.circuit_breaker'
    _COOLDOWN_TIERS = (300, 900, 3600)

    def __init__(
        self,
        failure_threshold=3,
        cooldown_seconds=300,
        get_prop_fn=None,
        set_prop_fn=None,
        clear_prop_fn=None,
        log_fn=None,
        loads_fn=None,
        is_drop_fn=None,
        is_gate_tripped_fn=None,
    ):
        self.failure_threshold = int(failure_threshold or 3)
        self.cooldown_seconds = int(cooldown_seconds or 300)
        self._get_prop_fn = get_prop_fn
        self._set_prop_fn = set_prop_fn
        self._clear_prop_fn = clear_prop_fn
        self._log_fn = log_fn
        self._loads_fn = loads_fn
        self._is_drop_fn = is_drop_fn
        self._is_gate_tripped_fn = is_gate_tripped_fn
        self._failures = {}
        self._cooldown_until = {}
        self._trip_counts = {}
        self._categories = {}
        self._half_open = set()
        self._lock = threading.Lock()

    def _log(self, msg, level='debug'):
        fn = self._log_fn or _default_log
        try:
            fn(msg, level)
        except Exception:
            pass

    def _load_locked(self):
        try:
            get_prop = self._get_prop_fn or _default_get_prop
            raw = get_prop(self._PROP_KEY)
            if not raw:
                return
            loads_fn = self._loads_fn or safe_json.loads_json
            data = loads_fn(raw, default={})
            if not isinstance(data, dict):
                return
            now = time.time()
            persisted_failures = data.get('failures') or {}
            persisted_cooldowns = data.get('cooldowns') or {}
            persisted_trips = data.get('trips') or {}
            persisted_cats = data.get('categories') or {}
            for k, v in persisted_failures.items():
                if k not in self._failures and isinstance(v, (int, float)):
                    self._failures[k] = int(v)
            for k, exp in persisted_cooldowns.items():
                if k not in self._cooldown_until and isinstance(exp, (int, float)) and exp > now:
                    self._cooldown_until[k] = float(exp)
            for k, tc in persisted_trips.items():
                if k not in self._trip_counts and isinstance(tc, (int, float)):
                    self._trip_counts[k] = int(tc)
            for k, cat in persisted_cats.items():
                if k not in self._categories and isinstance(cat, str):
                    self._categories[k] = cat
        except Exception:
            pass

    def _save_locked(self):
        try:
            now = time.time()
            active_cooldowns = {k: v for k, v in self._cooldown_until.items() if isinstance(v, (int, float)) and v > now}
            self._cooldown_until = active_cooldowns
            if self._failures or active_cooldowns or self._trip_counts:
                payload = json.dumps(
                    {
                        'failures': self._failures,
                        'cooldowns': active_cooldowns,
                        'trips': self._trip_counts,
                        'categories': self._categories,
                    },
                    separators=(',', ':'),
                )
                set_prop = self._set_prop_fn or _default_set_prop
                set_prop(self._PROP_KEY, payload)
            else:
                clear_prop = self._clear_prop_fn or _default_clear_prop
                clear_prop(self._PROP_KEY)
        except Exception:
            pass

    def is_tripped(self, provider: str, category: str = None) -> bool:
        with self._lock:
            self._load_locked()
            if category and provider not in self._categories:
                self._categories[provider] = str(category)
            now = time.time()
            cooldown = self._cooldown_until.get(provider, 0)
            if now < cooldown:
                return True
            if cooldown != 0:
                del self._cooldown_until[provider]
                self._failures[provider] = max(0, self.failure_threshold - 1)
                self._half_open.add(provider)
                self._save_locked()
            return False

    def is_half_open(self, provider: str) -> bool:
        with self._lock:
            self._load_locked()
            now = time.time()
            cooldown = self._cooldown_until.get(provider, 0)
            if cooldown != 0 and now >= cooldown:
                del self._cooldown_until[provider]
                self._failures[provider] = max(0, self.failure_threshold - 1)
                self._half_open.add(provider)
                self._save_locked()
            return provider in self._half_open

    def record_success(self, provider: str, category: str = None):
        with self._lock:
            self._load_locked()
            if category:
                self._categories[provider] = str(category)
            self._failures.pop(provider, None)
            self._cooldown_until.pop(provider, None)
            self._trip_counts.pop(provider, None)
            self._half_open.discard(provider)
            self._save_locked()

    def record_failure(self, provider: str, category: str = None, status_code: int = None, is_connectivity_drop: bool = False, exc: BaseException = None):
        drop = bool(is_connectivity_drop)
        if not drop and exc is not None:
            try:
                is_drop = self._is_drop_fn or connectivity.is_dns_or_network_drop
                drop = bool(getattr(exc, 'is_connectivity_drop', False)) or is_drop(exc)
            except Exception:
                drop = bool(getattr(exc, 'is_connectivity_drop', False))
        if not drop:
            try:
                is_gate = self._is_gate_tripped_fn or connectivity.is_connectivity_gate_tripped
                drop = bool(is_gate())
            except Exception:
                pass
        if drop:
            self._log(
                f"CircuitBreaker: Skipping cooldown escalation for '{provider}' due to transient DNS/connectivity drop",
                'debug',
            )
            return

        with self._lock:
            self._load_locked()
            if category:
                self._categories[provider] = str(category)
            count = self._failures.get(provider, 0) + 1
            self._failures[provider] = count
            in_half_open = provider in self._half_open
            if in_half_open or count >= self.failure_threshold or status_code == 429:
                self._half_open.discard(provider)
                trip_idx = self._trip_counts.get(provider, 0)
                self._trip_counts[provider] = trip_idx + 1
                if self.cooldown_seconds != 300 and trip_idx == 0:
                    ttl = self.cooldown_seconds
                else:
                    tier_pos = min(trip_idx, len(self._COOLDOWN_TIERS) - 1)
                    ttl = self._COOLDOWN_TIERS[tier_pos] if self.cooldown_seconds == 300 else (self.cooldown_seconds * (3 ** tier_pos))
                self._cooldown_until[provider] = time.time() + ttl
                self._log(
                    f"CircuitBreaker: Provider '{provider}' ({self._categories.get(provider, 'general')}) "
                    f"tripped for {ttl}s ({count} errors, tier={trip_idx + 1})",
                    'warning',
                )
            self._save_locked()

    def get_snapshot(self) -> dict:
        with self._lock:
            self._load_locked()
            now = time.time()
            providers = set(self._failures.keys()) | set(self._cooldown_until.keys()) | set(self._trip_counts.keys())
            snapshot = {}
            for p in sorted(providers):
                exp = self._cooldown_until.get(p, 0)
                rem = max(0, int(exp - now)) if exp > now else 0
                state = 'OPEN' if rem > 0 else ('HALF_OPEN' if p in self._half_open else 'CLOSED')
                snapshot[p] = {
                    'state': state,
                    'failures': int(self._failures.get(p, 0)),
                    'trips': int(self._trip_counts.get(p, 0)),
                    'remaining_s': rem,
                    'category': self._categories.get(p, 'general'),
                }
            return snapshot

    def reset(self, provider: str = None):
        with self._lock:
            if provider:
                self._load_locked()
                self._failures.pop(provider, None)
                self._cooldown_until.pop(provider, None)
                self._trip_counts.pop(provider, None)
                self._half_open.discard(provider)
            else:
                self._failures.clear()
                self._cooldown_until.clear()
                self._trip_counts.clear()
                self._categories.clear()
                self._half_open.clear()
            self._save_locked()
