# -*- coding: utf-8 -*-
"""Shared 15s DNS/connectivity gate preventing false circuit-breaker escalation (zero plugin dependencies)."""

from contextlib import contextmanager
import errno
import socket
import threading
import time

import xbmcgui

from otaku_service import metrics

_DNS_ERROR_SUBSTRINGS = (
    'temporary failure in name resolution',
    'name or service not known',
    'getaddrinfo failed',
    'nodename nor servname',
    'network is unreachable',
    'no route to host',
    'host is down',
)
_DNS_ERRNOS = frozenset(
    getattr(errno, name, None)
    for name in ('ENETUNREACH', 'EHOSTUNREACH', 'ENETDOWN', 'EHOSTDOWN', 'EAI_AGAIN')
) | {-2, -3, -5}

_tls_req_state = threading.local()


class ConnectivityGatedError(OSError):
    """Raised or tagged when outbound calls fail fast during an active 15s DNS/connectivity gate."""

    def __init__(self, message="Outbound request paused by shared connectivity/DNS gate"):
        super().__init__(message)
        self.is_connectivity_drop = True


def is_dns_or_network_drop(exc) -> bool:
    """Return True if *exc* (or its URLError reason/cause chain) represents a local DNS/network drop."""
    visited = set()
    curr = exc
    while curr is not None and id(curr) not in visited:
        visited.add(id(curr))
        if isinstance(curr, (ConnectivityGatedError, socket.gaierror)):
            return True
        err_no = getattr(curr, 'errno', None)
        if err_no is not None and err_no in _DNS_ERRNOS:
            return True
        msg = str(curr).lower()
        if any(sub in msg for sub in _DNS_ERROR_SUBSTRINGS):
            return True
        next_reason = getattr(curr, 'reason', None)
        if next_reason is not None and next_reason is not curr:
            if isinstance(next_reason, BaseException):
                curr = next_reason
                continue
            reason_msg = str(next_reason).lower()
            if any(sub in reason_msg for sub in _DNS_ERROR_SUBSTRINGS):
                return True
        curr = getattr(curr, '__cause__', None) or getattr(curr, '__context__', None)
    return False


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


def default_probe_connectivity(timeout=1.0) -> bool:
    """Lightweight port-443/53 TCP connectivity check (zero plugin dependencies)."""
    sock_timeout = min(float(timeout), 2.0) if timeout else 1.0
    probes = (
        ('cloudflare-dns.com', 443),
        ('www.gstatic.com', 443),
        ('1.1.1.1', 443),
        ('1.1.1.1', 53),
    )
    for host, port in probes:
        try:
            sock = socket.create_connection((host, port), timeout=sock_timeout)
            sock.close()
            return True
        except (OSError, socket.timeout):
            continue
    return False


class ConnectivityGate:
    """Thread-safe 15s TTL shared DNS/connectivity gate protecting AdaptiveCircuitBreaker.

    Requires >= 2 distinct failing hostnames within 5s (or failed connectivity probe)
    so a single dead mirror never trips the global gate.
    """

    _PROP_KEY = 'otaku.dns_gate_until'

    def __init__(
        self,
        ttl_seconds=15.0,
        distinct_window_s=5.0,
        min_distinct_hosts=2,
        get_prop_fn=None,
        set_prop_fn=None,
        clear_prop_fn=None,
        metric_fn=None,
        verify_connectivity_fn=None,
    ):
        self.ttl_seconds = float(ttl_seconds)
        self.distinct_window_s = float(distinct_window_s)
        self.min_distinct_hosts = int(min_distinct_hosts)
        self._get_prop_fn = get_prop_fn
        self._set_prop_fn = set_prop_fn
        self._clear_prop_fn = clear_prop_fn
        self._metric_fn = metric_fn
        self._verify_connectivity_fn = verify_connectivity_fn
        self._lock = threading.Lock()
        self._gate_until = 0.0
        self._was_tripped = False
        self._recent_host_failures = {}
        self._probing_connectivity = False

    def _emit_metric(self, event, level='info', **fields):
        fn = self._metric_fn or metrics.log_metric
        try:
            fn(event, level=level, **fields)
        except Exception:
            pass

    def _get_prop(self, key):
        fn = self._get_prop_fn or _default_get_prop
        return fn(key)

    def _read_window_until(self, now):
        try:
            raw = self._get_prop(self._PROP_KEY)
            if not raw:
                return 0.0
            val = float(raw)
            if val > now + self.ttl_seconds:
                val = now + self.ttl_seconds
            return val
        except Exception:
            return 0.0

    def _write_window_until(self, until_ts):
        try:
            if until_ts > 0:
                fn = self._set_prop_fn or _default_set_prop
                fn(self._PROP_KEY, f"{until_ts:.3f}")
            else:
                fn = self._clear_prop_fn or _default_clear_prop
                fn(self._PROP_KEY)
        except Exception:
            pass

    def is_tripped(self) -> bool:
        now = time.time()
        emit_cleared = False
        with self._lock:
            win_until = self._read_window_until(now)
            effective_until = max(self._gate_until, win_until)
            if effective_until > now:
                self._gate_until = min(effective_until, now + self.ttl_seconds)
                self._was_tripped = True
                return True
            if self._was_tripped or win_until > 0:
                self._gate_until = 0.0
                if self._was_tripped:
                    self._was_tripped = False
                    emit_cleared = True
                self._write_window_until(0.0)
        if emit_cleared:
            self._emit_metric('dns_gate', level='info', state='cleared', reason='ttl_expired')
        return False

    def record_failure(self, hostname, exc, verify_connectivity_fn=None) -> bool:
        if not is_dns_or_network_drop(exc):
            return False
        host = str(hostname or '').lower().split(':', 1)[0].strip() or 'unknown'
        now = time.time()
        should_probe = False
        distinct_hosts = 0

        with self._lock:
            cutoff = now - self.distinct_window_s
            self._recent_host_failures = {
                h: ts for h, ts in self._recent_host_failures.items() if ts >= cutoff
            }
            self._recent_host_failures[host] = now
            distinct_hosts = len(self._recent_host_failures)
            if distinct_hosts < self.min_distinct_hosts and not self._probing_connectivity:
                self._probing_connectivity = True
                should_probe = True

        net_down = False
        if should_probe:
            try:
                probe = verify_connectivity_fn or self._verify_connectivity_fn or default_probe_connectivity
                net_down = not bool(probe())
            except Exception:
                net_down = False
            finally:
                with self._lock:
                    self._probing_connectivity = False

        if distinct_hosts < self.min_distinct_hosts and not net_down:
            return False

        trip_reason = 'distinct_dns_hosts' if distinct_hosts >= self.min_distinct_hosts else 'internet_probe_failed'
        emit_tripped = False
        with self._lock:
            until = min(now + self.ttl_seconds, now + 15.0)
            self._gate_until = until
            self._write_window_until(until)
            if not self._was_tripped:
                self._was_tripped = True
                emit_tripped = True
        if emit_tripped:
            self._emit_metric(
                'dns_gate',
                level='warning',
                state='tripped',
                ttl_s=int(self.ttl_seconds),
                hosts=distinct_hosts,
                reason=trip_reason,
            )
        return True

    def record_success(self):
        emit_cleared = False
        with self._lock:
            self._recent_host_failures.clear()
            was = self._was_tripped or (self._gate_until > 0) or bool(self._get_prop(self._PROP_KEY))
            self._gate_until = 0.0
            if self._was_tripped:
                self._was_tripped = False
                emit_cleared = True
            if was:
                self._write_window_until(0.0)
        if emit_cleared:
            self._emit_metric('dns_gate', level='info', state='cleared', reason='request_succeeded')

    def reset(self):
        with self._lock:
            self._recent_host_failures.clear()
            self._gate_until = 0.0
            self._was_tripped = False
            self._write_window_until(0.0)


_connectivity_gate = ConnectivityGate()


def is_connectivity_gate_tripped() -> bool:
    return _connectivity_gate.is_tripped()


def clear_connectivity_gate():
    _connectivity_gate.reset()


@contextmanager
def bypass_connectivity_gate():
    """Thread-local scope preventing non-critical parallel probes from tripping/hitting the global gate."""
    prev = getattr(_tls_req_state, 'bypass_dns_gate', False)
    _tls_req_state.bypass_dns_gate = True
    try:
        yield
    finally:
        _tls_req_state.bypass_dns_gate = prev
