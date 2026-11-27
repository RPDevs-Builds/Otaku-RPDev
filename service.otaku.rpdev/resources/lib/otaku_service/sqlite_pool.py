# -*- coding: utf-8 -*-
"""Thread-local pooled SQLite connection utilities (zero plugin dependencies)."""

import os
import random
import threading
import time
import urllib.parse
from sqlite3 import OperationalError, dbapi2

_thread_local = threading.local()
_conns_lock = threading.RLock()
_all_thread_conns = {}

_SYNC_MODES = {'0': 'OFF', '1': 'NORMAL', '2': 'FULL'}


def dict_factory(cursor, row):
    """Row factory that returns dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_thread_conns():
    """Return per-thread connection cache keyed by ``(abs_path, is_readonly)``."""
    tid = threading.get_ident()
    conns = getattr(_thread_local, 'conns', None)
    if conns is None:
        conns = {}
        _thread_local.conns = conns
    with _conns_lock:
        _all_thread_conns[tid] = conns
    return conns


def prune_dead_thread_connections(log_fn=None):
    """Close and remove SQLite connections belonging to worker threads that have exited."""
    alive_tids = {t.ident for t in threading.enumerate() if t.ident is not None}
    with _conns_lock:
        dead_tids = [tid for tid in list(_all_thread_conns.keys()) if tid not in alive_tids]
        dead_dicts = [_all_thread_conns.pop(tid, {}) for tid in dead_tids]
    for conns in dead_dicts:
        for _, (conn, _) in list(conns.items()):
            try:
                conn.close()
            except (dbapi2.Error, OSError) as e:
                if log_fn:
                    log_fn(f"dead thread db close error: {e}", 'debug')
        conns.clear()


def _pop_path_entries(conns, target):
    for key in ((target, True), (target, False), (target, 'ro'), (target, 'rw'), target, f"{target}:ro"):
        entry = conns.pop(key, None)
        if entry:
            yield entry[0]


def close_thread_connections(path=None, log_fn=None):
    """Close cached SQLite connections for the current thread and prune dead worker threads."""
    tid = threading.get_ident()
    conns = getattr(_thread_local, 'conns', None)
    if conns:
        if path is not None:
            target = os.path.abspath(path)
            for conn in _pop_path_entries(conns, target):
                try:
                    conn.close()
                except (dbapi2.Error, OSError) as e:
                    if log_fn:
                        log_fn(f"database close error: {e}", 'debug')
            if not conns:
                with _conns_lock:
                    _all_thread_conns.pop(tid, None)
        else:
            for _, (conn, _) in list(conns.items()):
                try:
                    conn.close()
                except (dbapi2.Error, OSError) as e:
                    if log_fn:
                        log_fn(f"database pool close error: {e}", 'debug')
            conns.clear()
            with _conns_lock:
                _all_thread_conns.pop(tid, None)
    prune_dead_thread_connections(log_fn=log_fn)


def close_all_connections(path=None, log_fn=None):
    """Close cached SQLite connections across all threads in this interpreter."""
    with _conns_lock:
        all_items = list(_all_thread_conns.items())
        if path is None:
            _all_thread_conns.clear()
    target = os.path.abspath(path) if path is not None else None
    for tid, conns in all_items:
        if target is not None:
            for conn in _pop_path_entries(conns, target):
                try:
                    conn.close()
                except (dbapi2.Error, OSError) as e:
                    if log_fn:
                        log_fn(f"database close error: {e}", 'debug')
            if not conns:
                with _conns_lock:
                    _all_thread_conns.pop(tid, None)
        else:
            for _, (conn, _) in list(conns.items()):
                try:
                    conn.close()
                except (dbapi2.Error, OSError) as e:
                    if log_fn:
                        log_fn(f"database pool close error: {e}", 'debug')
            conns.clear()
    cur_conns = getattr(_thread_local, 'conns', None)
    if cur_conns:
        if target is not None:
            for conn in _pop_path_entries(cur_conns, target):
                try:
                    conn.close()
                except (dbapi2.Error, OSError):
                    pass
        else:
            for _, (conn, _) in list(cur_conns.items()):
                try:
                    conn.close()
                except (dbapi2.Error, OSError):
                    pass
            cur_conns.clear()


def is_db_corruption_error(exc):
    """Return True if *exc* looks like SQLite file corruption."""
    if not exc:
        return False
    msg = str(exc).lower()
    return any(p in msg for p in ('malformed', 'not a database', 'disk image is malformed', 'file is encrypted'))


def execute_write_with_retry(cur, sql, params=(), max_retries=3):
    """Execute a write statement with exponential backoff and jitter on database lock."""
    for attempt in range(max_retries):
        try:
            return cur.execute(sql, params)
        except (dbapi2.OperationalError, OperationalError) as e:
            if 'locked' in str(e).lower() or 'busy' in str(e).lower():
                if attempt == max_retries - 1:
                    raise
                jitter = random.uniform(0.01, 0.04)
                backoff = (0.05 * (2 ** attempt)) + jitter
                time.sleep(backoff)
            else:
                raise


def open_sqlite_connection(
    path,
    timeout=30,
    is_readonly=False,
    synchronous='1',
    cache_mb=16,
    mmap_size_bytes=0,
    temp_store_ram=True,
    low_memory=False,
    log_fn=None,
):
    """Open a pooled SQLite connection enforcing ?mode=ro URI on readonly paths and WAL/memory PRAGMAs on RW."""
    abs_path = os.path.abspath(path)
    if is_readonly and os.path.exists(path):
        safe_chars = '/:\\'
        ro_uri = f"file:{urllib.parse.quote(abs_path, safe=safe_chars)}?mode=ro"
        try:
            conn = dbapi2.connect(
                ro_uri,
                uri=True,
                timeout=float(timeout),
                isolation_level=None,
                check_same_thread=False,
            )
        except Exception as ro_exc:
            if log_fn:
                log_fn(f"SQL read-only URI fallback for {abs_path}: {ro_exc}", 'warning')
            conn = dbapi2.connect(
                f"file:{abs_path}?mode=ro",
                uri=True,
                timeout=float(timeout),
                isolation_level=None,
                check_same_thread=False,
            )
    else:
        conn = dbapi2.connect(
            path,
            timeout=float(timeout),
            isolation_level=None,
            check_same_thread=False,
        )

    conn.row_factory = dict_factory
    if not is_readonly:
        conn.execute("PRAGMA foreign_keys = ON")
        sync_mode = _SYNC_MODES.get(str(synchronous), 'NORMAL')
        conn.execute(f"PRAGMA synchronous = {sync_mode}")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except dbapi2.DatabaseError:
            pass
        if cache_mb and int(cache_mb) > 0:
            conn.execute(f"PRAGMA cache_size = -{int(cache_mb) * 1024}")
        conn.execute(f"PRAGMA mmap_size = {max(0, int(mmap_size_bytes))}")
        if temp_store_ram:
            conn.execute("PRAGMA temp_store = MEMORY")
    elif low_memory:
        try:
            conn.execute("PRAGMA mmap_size = 0")
        except dbapi2.DatabaseError:
            pass
    return conn
