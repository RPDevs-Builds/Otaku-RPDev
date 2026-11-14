from resources.lib.ui import source_utils
"""
database.py - Otaku Database & Caching Layer
=============================================
Clean, organized caching and metadata storage.

Architecture
------------
SQL          - Lock-free SQLite context manager (WAL mode concurrent access)
Memory Cache - Window-property RAM cache with expiry
General Cache- 3-tier caching: RAM → SQLite → fresh API call
Shows        - Anime show / meta / episode CRUD
Mappings     - Cross-service ID lookups
Watchlist    - Per-service watchlist cache with activity invalidation
Enrichment   - AniList supplementary metadata cache
History      - Per-category search history
Maintenance  - Cache clearing helpers
"""

import ast
import atexit
import builtins
import hashlib
import io
import json
import os
import pickle
import random
import re
import threading
import time

import xbmcgui
import xbmcvfs

from sqlite3 import OperationalError, dbapi2
from resources.lib.ui import control


# ═══════════════════════════════════════════════════════════════════════════
#  Safe Serialization (JSON Primary + Restricted Unpickler Legacy Fallback)
# ═══════════════════════════════════════════════════════════════════════════

_SAFE_PICKLE_BUILTINS = frozenset({
    'set', 'frozenset', 'slice', 'complex', 'bytearray', 'bytes',
    'dict', 'list', 'tuple', 'str', 'int', 'float', 'bool',
})


class _SafeUnpickler(pickle.Unpickler):
    """Restricted unpickler for legacy SQLite blobs that blocks arbitrary code execution."""

    def find_class(self, module, name):
        if module in ('builtins', '__builtin__') and name in _SAFE_PICKLE_BUILTINS:
            return getattr(builtins, name)
        raise pickle.UnpicklingError(f"Blocked unsafe pickle global: {module}.{name}")


def _json_default(obj):
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def dumps(obj):
    """Serialize *obj* to UTF-8 JSON bytes for SQLite storage."""
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj)
    try:
        return json.dumps(obj, ensure_ascii=False, default=_json_default).encode('utf-8')
    except (TypeError, ValueError):
        return pickle.dumps(obj)


_JSON_PARSE_MISS = object()


def loads(blob):
    """Safely deserialize a SQLite blob (UTF-8 JSON or legacy restricted pickle)."""
    if blob is None or blob == b'' or blob == '':
        return {}
    if isinstance(blob, (dict, list)):
        return blob
    if isinstance(blob, (bytes, bytearray)):
        # Pickle protocols 2..5 start with 0x80
        if blob[:1] == b'\x80':
            return _SafeUnpickler(io.BytesIO(blob)).load()
        try:
            decoded = blob.decode('utf-8')
        except UnicodeDecodeError:
            return _SafeUnpickler(io.BytesIO(blob)).load()
        parsed = control.loads_json(decoded, default=_JSON_PARSE_MISS)
        if parsed is not _JSON_PARSE_MISS:
            return parsed
        return _SafeUnpickler(io.BytesIO(blob)).load()
    if isinstance(blob, str):
        parsed = control.loads_json(blob, default=_JSON_PARSE_MISS)
        if parsed is not _JSON_PARSE_MISS:
            return parsed
        return _SafeUnpickler(io.BytesIO(blob.encode('latin-1'))).load()
    return {}


# ═══════════════════════════════════════════════════════════════════════════
#  SQL - Thread-Local Pooled SQLite Context Manager (WAL-mode concurrent)
# ═══════════════════════════════════════════════════════════════════════════

_thread_local = threading.local()
_conns_lock = threading.RLock()
_all_thread_conns = {}


def _dict_factory(cursor, row):
    """Row factory that returns dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _get_thread_conns():
    tid = threading.get_ident()
    conns = getattr(_thread_local, 'conns', None)
    if conns is None:
        conns = {}
        _thread_local.conns = conns
    with _conns_lock:
        _all_thread_conns[tid] = conns
    return conns


def prune_dead_thread_connections():
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
                control.log(f"dead thread db close error: {e}", 'debug')
        conns.clear()


def close_thread_connections(path=None):
    """Close cached SQLite connections for the current thread and prune dead worker threads."""
    tid = threading.get_ident()
    conns = getattr(_thread_local, 'conns', None)
    if conns:
        if path is not None:
            target = os.path.abspath(path)
            for key in ((target, True), (target, False), (target, 'ro'), (target, 'rw'), target, f"{target}:ro"):
                entry = conns.pop(key, None)
                if entry:
                    try:
                        entry[0].close()
                    except (dbapi2.Error, OSError) as e:
                        control.log(f"database close error: {e}", 'debug')
            if not conns:
                with _conns_lock:
                    _all_thread_conns.pop(tid, None)
        else:
            for _, (conn, _) in list(conns.items()):
                try:
                    conn.close()
                except (dbapi2.Error, OSError) as e:
                    control.log(f"database pool close error: {e}", 'debug')
            conns.clear()
            with _conns_lock:
                _all_thread_conns.pop(tid, None)
    prune_dead_thread_connections()


def close_all_connections(path=None):
    """Close cached SQLite connections across all threads in this interpreter."""
    with _conns_lock:
        all_items = list(_all_thread_conns.items())
        if path is None:
            _all_thread_conns.clear()
    target = os.path.abspath(path) if path is not None else None
    for tid, conns in all_items:
        if target is not None:
            for key in ((target, True), (target, False), (target, 'ro'), (target, 'rw'), target, f"{target}:ro"):
                entry = conns.pop(key, None)
                if entry:
                    try:
                        entry[0].close()
                    except (dbapi2.Error, OSError) as e:
                        control.log(f"database close error: {e}", 'debug')
            if not conns:
                with _conns_lock:
                    _all_thread_conns.pop(tid, None)
        else:
            for _, (conn, _) in list(conns.items()):
                try:
                    conn.close()
                except (dbapi2.Error, OSError) as e:
                    control.log(f"database pool close error: {e}", 'debug')
            conns.clear()
    # Ensure current thread local dict is also closed if not yet registered
    cur_conns = getattr(_thread_local, 'conns', None)
    if cur_conns:
        if target is not None:
            for key in ((target, True), (target, False), (target, 'ro'), (target, 'rw'), target, f"{target}:ro"):
                entry = cur_conns.pop(key, None)
                if entry:
                    try:
                        entry[0].close()
                    except (dbapi2.Error, OSError):
                        pass
        else:
            for _, (conn, _) in list(cur_conns.items()):
                try:
                    conn.close()
                except (dbapi2.Error, OSError):
                    pass
            cur_conns.clear()


atexit.register(close_all_connections)


def _is_db_corruption_error(exc):
    if not exc:
        return False
    msg = str(exc).lower()
    return any(p in msg for p in ('malformed', 'not a database', 'disk image is malformed', 'file is encrypted'))


def _quarantine_and_recover_db(path):
    if not path:
        return
    abs_path = os.path.abspath(path)
    close_thread_connections(abs_path)
    ts = int(time.time())
    control.log(f"CRITICAL: SQLite database corruption detected on {abs_path}. Quarantining database.", level='error')
    for ext in ('', '-wal', '-shm', '-journal'):
        f = abs_path + ext
        if os.path.exists(f):
            try:
                os.rename(f, f"{f}.corrupt.{ts}")
            except OSError as oe:
                control.log(f"Failed to quarantine {f}: {oe}", level='warning')

    cache_path = os.path.abspath(control.cacheFile) if getattr(control, 'cacheFile', None) else ''
    search_path = os.path.abspath(control.searchHistoryDB) if getattr(control, 'searchHistoryDB', None) else ''
    malsync_path = os.path.abspath(control.malSyncDB) if getattr(control, 'malSyncDB', None) else ''
    mapping_path = os.path.abspath(control.mappingDB) if getattr(control, 'mappingDB', None) else ''

    try:
        if abs_path == cache_path:
            _tables_ready.discard(f"{control.cacheFile}:cache")
            _init_cache_table()
            control.log("Auto-recovery: Re-initialized cache.db schema", level='info')
        elif abs_path == search_path:
            _tables_ready.discard(f"{control.searchHistoryDB}:search_tables")
            _ensure_search_tables()
            control.log("Auto-recovery: Re-initialized search.db schema", level='info')
        elif abs_path == malsync_path:
            from resources.lib.ui.database_sync import OtakuDatabase
            OtakuDatabase.create_tables()
            control.log("Auto-recovery: Re-initialized malSync.db schema", level='info')
        elif abs_path == mapping_path:
            control.log("Auto-recovery: mappings.db quarantined; will be restored on next service sync", level='info')
    except Exception as re:
        control.log(f"Auto-recovery schema recreation error for {abs_path}: {re}", level='error')


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


class SQL:
    """Thread-local pooled SQLite context manager with optimized PRAGMAs.

    WAL journal mode allows concurrent readers without locking.
    isolation_level=None enables autocommit for faster writes.

    Usage::

        with SQL(db_path) as cursor:
            cursor.execute('SELECT ...')
            cursor.connection.commit()   # needed for writes
    """

    def __init__(self, path, timeout=30, is_readonly=None):
        self.path = path
        self.timeout = timeout
        self._conn = None
        self._cursor = None
        abs_path = os.path.abspath(self.path) if self.path else ''
        info_path = os.path.abspath(control.infoDB) if getattr(control, 'infoDB', None) else ''
        mapping_path = os.path.abspath(control.mappingDB) if getattr(control, 'mappingDB', None) else ''
        self.is_readonly = (abs_path in (info_path, mapping_path)) if is_readonly is None else bool(is_readonly)

    def __enter__(self):
        abs_path = os.path.abspath(self.path)
        info_path = os.path.abspath(control.infoDB) if getattr(control, 'infoDB', None) else ''
        mapping_path = os.path.abspath(control.mappingDB) if getattr(control, 'mappingDB', None) else ''
        if not self.is_readonly and abs_path in (info_path, mapping_path):
            self.is_readonly = True
        is_readonly = self.is_readonly

        if not is_readonly and not xbmcvfs.exists(control.dataPath):
            xbmcvfs.mkdirs(control.dataPath)

        cache_key = (abs_path, is_readonly)

        for attempt in range(2):
            conns = _get_thread_conns()
            st_ino = None
            if os.path.exists(abs_path):
                try:
                    st_ino = os.stat(abs_path).st_ino
                except OSError:
                    st_ino = None

            if cache_key in conns:
                cached_conn, cached_ino = conns[cache_key]
                if st_ino is None or (cached_ino is not None and st_ino != cached_ino):
                    try:
                        cached_conn.close()
                    except (dbapi2.Error, OSError) as e:
                        control.log(f"cached db close error: {e}", 'debug')
                    conns.pop(cache_key, None)

            try:
                if cache_key not in conns:
                    if self.is_readonly and os.path.exists(self.path):
                        try:
                            conn = dbapi2.connect(
                                f"file:{abs_path}?mode=ro",
                                uri=True,
                                timeout=float(self.timeout),
                                isolation_level=None,
                                check_same_thread=False
                            )
                        except Exception:
                            conn = dbapi2.connect(
                                self.path,
                                timeout=float(self.timeout),
                                isolation_level=None,
                                check_same_thread=False
                            )
                    else:
                        conn = dbapi2.connect(
                            self.path,
                            timeout=float(self.timeout),
                            isolation_level=None,
                            check_same_thread=False
                        )
                    conn.row_factory = _dict_factory
                    if not is_readonly:
                        conn.execute("PRAGMA foreign_keys = ON")
                        # Synchronous setting (0=OFF, 1=NORMAL, 2=FULL)
                        sync_val = control.getSetting('db.sqlite.synchronous')
                        sync_modes = {'0': 'OFF', '1': 'NORMAL', '2': 'FULL'}
                        sync_mode = sync_modes.get(str(sync_val), 'NORMAL')
                        conn.execute(f"PRAGMA synchronous = {sync_mode}")
                        try:
                            conn.execute("PRAGMA journal_mode = WAL")
                        except dbapi2.DatabaseError:
                            pass
                        # Cache size setting (negative value in KiB)
                        cache_mb = control.getInt('db.sqlite.cache_size_mb') or (16 if control.is_low_memory() else 32)
                        if cache_mb > 0:
                            conn.execute(f"PRAGMA cache_size = -{cache_mb * 1024}")
                        # Memory map size setting
                        mmap_setting_mb = control.getInt('db.sqlite.mmap_size_mb') or 32
                        if control.is_low_memory():
                            mmap_size = min(4194304, mmap_setting_mb * 1048576)
                        else:
                            mmap_size = mmap_setting_mb * 1048576
                        conn.execute(f"PRAGMA mmap_size = {mmap_size}")
                        # Temp store in RAM
                        if control.getBool('db.sqlite.temp_store_ram', default=True):
                            conn.execute("PRAGMA temp_store = MEMORY")
                    if os.path.exists(abs_path):
                        try:
                            st_ino = os.stat(abs_path).st_ino
                        except OSError:
                            st_ino = None
                    conns[cache_key] = (conn, st_ino)

                self._conn = conns[cache_key][0]
                self._cursor = self._conn.cursor()
                return self._cursor
            except Exception as exc:
                close_thread_connections(self.path)
                self._conn = None
                if attempt == 0 and _is_db_corruption_error(exc):
                    _quarantine_and_recover_db(self.path)
                    continue
                raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._cursor is not None:
                self._cursor.close()
        except dbapi2.Error as e:
            control.log(f"cursor close error: {e}", 'debug')

        if exc_type:
            try:
                if self._conn is not None and getattr(self._conn, 'in_transaction', False):
                    self._conn.rollback()
            except dbapi2.Error as e:
                control.log(f"db rollback error: {e}", 'debug')
            close_thread_connections(self.path)

            if _is_db_corruption_error(exc_val):
                _quarantine_and_recover_db(self.path)

            if exc_type is OperationalError:
                import traceback
                control.log('database OperationalError', level='error')
                control.log(''.join(traceback.format_exception(
                    exc_type, exc_val, exc_tb)), level='error')
                if 'no such table' in str(exc_val).lower():
                    return True
                return False
            import traceback
            control.log('database error', level='error')
            control.log(''.join(traceback.format_exception(
                exc_type, exc_val, exc_tb)), level='error')
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  Memory Cache - Kodi Window Properties with Expiry & Generation Counter
# ═══════════════════════════════════════════════════════════════════════════

_window = control.homeWindow
_MEM_GEN_PROP = f'{control.ADDON_ID}_cache_gen'
_MEM_KEYS_PROP = f'{control.ADDON_ID}_cache_keys'
_MAX_MEM_CACHE_BYTES = 65536  # 64 KB ceiling to prevent Kodi GUI memory bloat


def _get_mem_prefix():
    gen = _window.getProperty(_MEM_GEN_PROP) or '0'
    return f'{control.ADDON_ID}_c{gen}_'


def _register_mem_key(full_key):
    """Keep track of active window property keys for generational garbage collection."""
    try:
        existing = _window.getProperty(_MEM_KEYS_PROP) or ''
        keys = set(existing.split(',')) if existing else set()
        if full_key not in keys:
            keys.add(full_key)
            if len(keys) > 500:
                keys = set(list(keys)[-250:])
            _window.setProperty(_MEM_KEYS_PROP, ','.join(keys))
    except Exception:
        pass


def _bump_mem_generation():
    """Increment generation counter and purge window properties from previous generation."""
    try:
        registered = _window.getProperty(_MEM_KEYS_PROP) or ''
        if registered:
            for k in registered.split(','):
                if k:
                    _window.clearProperty(k)
            _window.clearProperty(_MEM_KEYS_PROP)
    except Exception:
        pass

    try:
        gen = int(_window.getProperty(_MEM_GEN_PROP) or '0') + 1
    except ValueError:
        gen = int(time.time())
    _window.setProperty(_MEM_GEN_PROP, str(gen))


def _mem_get(key):
    """Return parsed data or *None* if missing / expired."""
    prefix = _get_mem_prefix()
    raw = _window.getProperty(prefix + key)
    if not raw:
        return None
    try:
        sep = raw.index('|')
        if int(raw[:sep]) > int(time.time()):
            return ast.literal_eval(raw[sep + 1:])
    except (ValueError, SyntaxError) as e:
        control.log(f"_mem_get parse error for {key}: {e}", 'debug')
    _window.clearProperty(prefix + key)
    return None


def _mem_set(key, value_repr, hours):
    """Store *value_repr* (a ``repr()`` string) with an expiry of *hours*. Payloads >64KB bypass RAM window cache."""
    if not value_repr or len(value_repr) > _MAX_MEM_CACHE_BYTES:
        return
    expires = int(time.time() + hours * 3600)
    full_key = _get_mem_prefix() + key
    _window.setProperty(full_key, f"{expires}|{value_repr}")
    _register_mem_key(full_key)


def _mem_del(key):
    """Remove a single key from the RAM cache."""
    _window.clearProperty(_get_mem_prefix() + key)


# ═══════════════════════════════════════════════════════════════════════════
#  Lazy Table Initialization (once per session)
# ═══════════════════════════════════════════════════════════════════════════

_tables_ready = set()


def _ensure_table(db_path, name, ddl):
    """Run *ddl* only the first time (*db_path*, *name*) is seen."""
    tag = f"{db_path}:{name}"
    if tag in _tables_ready:
        return
    with SQL(db_path) as cur:
        cur.execute(ddl)
        cur.connection.commit()
    _tables_ready.add(tag)


def _init_cache_table():
    _ensure_table(
        control.cacheFile, 'cache',
        'CREATE TABLE IF NOT EXISTS cache '
        '(key TEXT UNIQUE, value TEXT, date INTEGER)'
    )
    # Index once at init; avoid running DDL on every cache write (hot path).
    _ensure_table(
        control.cacheFile, 'cache_ix_key',
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_cache ON cache (key)'
    )
    _ensure_table(
        control.cacheFile, 'cache_ix_date',
        'CREATE INDEX IF NOT EXISTS ix_cache_date ON cache (date)'
    )


# ═══════════════════════════════════════════════════════════════════════════
#  General Cache - 3-Tier: RAM → SQLite → Fresh API Call
# ═══════════════════════════════════════════════════════════════════════════

def _is_empty_result(val):
    """Detect empty results that should not poison the cache.
    Includes None, empty sequences, empty dicts, or torrent dicts with empty buckets."""
    if not val:
        return True
    if isinstance(val, dict):
        if not any(val.values()):
            return True
        if all(isinstance(v, (list, tuple, set, dict)) and not v for v in val.values()):
            return True
    return False



# ═══════════════════════════════════════════════════════════════════════════

def get(function, duration, *args, **kwargs):
    """Cached function call with 3-tier lookup.

    :param function:  Callable to execute on cache miss.
    :param duration:  Cache validity in **hours**.
    :param args/kwargs:  Forwarded to *function* on miss.
        Special kwarg ``key`` is popped and appended to the cache key.
    """
    if duration == 24:
        configured_ttl = control.getInt('cache.metadata.ttl')
        if configured_ttl:
            duration = configured_ttl
    elif duration == 8:
        configured_ttl = control.getInt('cache.scrapers.ttl')
        if configured_ttl:
            duration = configured_ttl

    key = _hash_function(function, args, kwargs)
    if 'key' in kwargs:
        key += kwargs.pop('key')

    # --- Tier 1: RAM (instant) ---
    mem = _mem_get(key)
    if mem is not None and not _is_empty_result(mem):
        return mem

    # --- Tier 2: SQLite ---
    _init_cache_table()
    row = None
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
        row = cur.fetchone()

    if row and is_cache_valid(row['date'], duration):
        try:
            data = ast.literal_eval(row['value'])
            if data is not None and not _is_empty_result(data):
                _mem_set(key, row['value'], duration)
                return data
        except Exception:
            control.log(
                f"Cache corrupt for key {key}, fetching fresh data",
                level='warning')

    # --- Tier 3: Fresh call ---
    result = function(*args, **kwargs)
    if result is None or _is_empty_result(result):
        return result
    result_repr = repr(result)
    _cache_write(key, result_repr)
    _mem_set(key, result_repr, duration)
    return result


_coalesce_locks = {}
_coalesce_meta_lock = threading.Lock()
_legacy_build_cleaned = False


def get_coalesced(function, duration, *args, **kwargs):
    """Share overlapping progress / metadata calls across concurrent Kodi threads.

    Uses an in-process per-key threading.Lock() guarded by _coalesce_meta_lock,
    double-checking RAM and SQLite caches before executing function(*args, **kwargs).
    """
    global _legacy_build_cleaned
    if duration == 24:
        configured_ttl = control.getInt('cache.metadata.ttl')
        if configured_ttl:
            duration = configured_ttl
    elif duration == 8:
        configured_ttl = control.getInt('cache.scrapers.ttl')
        if configured_ttl:
            duration = configured_ttl

    key = _hash_function(function, args, kwargs)
    if 'key' in kwargs:
        key += kwargs.get('key')

    # Tier 1: RAM cache check (instant)
    mem = _mem_get(key)
    if mem is not None and not _is_empty_result(mem):
        return mem

    # Clean up any legacy .build-* SQLite files if present
    if not _legacy_build_cleaned and getattr(control, 'dataPath', None) and os.path.isdir(control.dataPath):
        _legacy_build_cleaned = True
        try:
            for fname in os.listdir(control.dataPath):
                if '.build-' in fname:
                    try:
                        os.remove(os.path.join(control.dataPath, fname))
                    except OSError:
                        pass
        except OSError:
            pass

    with _coalesce_meta_lock:
        key_lock = _coalesce_locks.get(key)
        if key_lock is None:
            key_lock = threading.Lock()
            _coalesce_locks[key] = key_lock

    with key_lock:
        # Double-check Tier 1: RAM
        mem = _mem_get(key)
        if mem is not None and not _is_empty_result(mem):
            return mem

        # Double-check Tier 2: SQLite and Tier 3: Fresh call via get()
        return get(function, duration, *args, **kwargs)


def remove(function, *args, **kwargs):
    """Remove the cached value for a function call."""
    try:
        key = _hash_function(function, args, kwargs)
        _cache_delete(key)
        _mem_del(key)
        return True
    except Exception:
        return False


def peek(function, duration=24, *args, **kwargs):
    """Non-blocking check of RAM window cache and SQLite cache.db.

    Returns deserialized cached value on hit, None on miss without calling function.
    """
    if not isinstance(duration, (int, float)):
        args = (duration,) + args
        duration = 24

    if duration == 24:
        configured_ttl = control.getInt('cache.metadata.ttl')
        if configured_ttl:
            duration = configured_ttl
    elif duration == 8:
        configured_ttl = control.getInt('cache.scrapers.ttl')
        if configured_ttl:
            duration = configured_ttl

    if isinstance(function, str):
        key = function
    else:
        kwargs_copy = dict(kwargs)
        extra_key = kwargs_copy.pop('key', '')
        key = _hash_function(function, args, kwargs_copy) + extra_key

    # --- Tier 1: RAM (instant) ---
    mem = _mem_get(key)
    if mem is not None and not _is_empty_result(mem):
        return mem

    # --- Tier 2: SQLite ---
    _init_cache_table()
    row = None
    try:
        with SQL(control.cacheFile) as cur:
            cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
            row = cur.fetchone()
    except Exception as e:
        control.log(f"peek SQL error: {e}", level='debug')
        return None

    if row and is_cache_valid(row['date'], duration):
        try:
            data = ast.literal_eval(row['value'])
        except Exception:
            try:
                data = control.loads_json(row['value'], None)
            except Exception:
                data = None

        if data is not None and not _is_empty_result(data):
            _mem_set(key, row['value'], duration)
            return data

    return None


# — helpers ------------------------------------------------------------------

def _hash_function(func, args, kwargs):
    name = re.sub(
        r'.+\smethod\s|.+function\s|\sat\s.+|\sof\s.+', '', repr(func))
    return name + generate_md5((args, kwargs))


def generate_md5(*args):
    """MD5 hex-digest of the string representation of *args*."""
    md5 = hashlib.md5()
    for arg in args:
        md5.update(str(arg).encode())
    return md5.hexdigest()


def is_cache_valid(cached_time, hours):
    """True when *cached_time* (epoch) is younger than *hours*."""
    return (int(time.time()) - cached_time) < (hours * 3600)


def _cache_write(key, value_repr):
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        execute_write_with_retry(
            cur,
            'REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)',
            (key, value_repr, int(time.time())))
        cur.connection.commit()


def _cache_delete(key):
    with SQL(control.cacheFile) as cur:
        execute_write_with_retry(
            cur,
            'DELETE FROM cache WHERE key=?',
            (key,))
        cur.connection.commit()


# — backward-compat aliases (kept for any external callers) -----------------

def hash_function(function_instance, *args):
    function_name = re.sub(
        r'.+\smethod\s|.+function\s|\sat\s.+|\sof\s.+', '',
        repr(function_instance))
    return function_name + generate_md5(args)


def cache_get(key):
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT * FROM cache WHERE key=?', (key,))
        return cur.fetchone()


def cache_insert(key, value):
    _cache_write(key, value)


def cache_remove(key):
    _cache_delete(key)


def cache_clear():
    """Wipe general cache, debrid cache, watchlist cache, activity, and enrichment data."""
    _bump_mem_generation()
    with SQL(control.cacheFile) as cur:
        cur.execute("DROP TABLE IF EXISTS cache")
        cur.execute("VACUUM")
        cur.connection.commit()
    _tables_ready.discard(f"{control.cacheFile}:cache")
    _tables_ready.discard(f"{control.cacheFile}:cache_ix_key")
    _tables_ready.discard(f"{control.cacheFile}:cache_ix_date")

    # Clear debrid cache as well
    try:
        from resources.lib.debrid import debrid_cache
        debrid_cache.clear_debrid_cache()
    except Exception as e:
        control.log(f"Error clearing debrid cache: {e}", 'debug')

    # Reset circuit breaker
    try:
        from resources.lib.pages import circuit_breaker
        circuit_breaker.reset()
    except Exception:
        pass

    control.setSetting('last_played_source', str(None))

    clear_watchlist_cache()
    clear_watchlist_activity()
    clear_anilist_enrichment()

    control.notify(
        f'{control.ADDON_NAME}: {control.lang(30086)}',
        control.lang(30087), time=5000, sound=False)


def cache_clear_providers():
    """Purge provider and scraper cache (torrents, embeds, season packs, debrid hash cache).

    Guarantees a clean, fresh scrape on next playback without touching
    user watchlist, show/episode metadata, or account databases.
    """
    _bump_mem_generation()
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        # 1. Purge season pack torrent listings and last played sources
        cur.execute("DELETE FROM cache WHERE key LIKE 'season_pack_%'")
        cur.execute("DELETE FROM cache WHERE key LIKE 'episode_sources_%'")
        cur.execute("DELETE FROM cache WHERE key LIKE 'last_played_%'")

        # 2. Purge cached scraper results for all providers (torrents, embeds, hosters)
        provider_tokens = [
            'nyaa', 'animetosho', 'nekobt', 'torrentio', 'bitsearch', 'piratebay', 'easynews',
            'animepahe', 'animix', 'aniwave', 'hianime', 'animekai',
            'anikoto', 'watchnixtoons2', 'gogoanime', 'kaido', 'kissanime',
            'tokyotosho'
        ]
        for token in provider_tokens:
            cur.execute("DELETE FROM cache WHERE key LIKE ?", (f'%{token}%',))

        # 3. Purge generic get_sources function hashes
        cur.execute("DELETE FROM cache WHERE key LIKE '%get_sources%'")
        cur.connection.commit()

    # 4. Clear debrid hash availability cache (so hashes are re-checked fresh)
    try:
        from resources.lib.debrid import debrid_cache
        debrid_cache.clear_debrid_cache()
    except Exception as e:
        control.log(f"Error clearing debrid hash cache: {e}", 'warning')

    # 5. Reset scraper circuit breaker so any temporarily tripped scrapers can retry
    try:
        from resources.lib.pages import circuit_breaker
        circuit_breaker.reset()
    except Exception as e:
        control.log(f"Error resetting scraper circuit breaker: {e}", 'debug')

    # 6. Reset last played source setting
    control.setSetting('last_played_source', str(None))

    control.notify(
        f'{control.ADDON_NAME}: Provider Cache',
        'Torrents, embeds & debrid cache cleared for clean rescan.',
        time=4000, sound=False
    )


# Alias for compatibility with settings.xml action
cache_clear_scrapers = cache_clear_providers


def cache_clear_metadata():
    """Purge metadata provider caches (AniList, MAL, Kitsu, Simkl, MDBList, TVDB, AniSkip)."""
    _bump_mem_generation()
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        metadata_tokens = [
            'anilist', 'myanimelist', 'mal', 'kitsu', 'simkl', 'mdblist',
            'tvdb', 'aniskip', 'jikan', 'anidb', 'anizip', 'fanart',
            'get_base_res', 'get_anime_init', 'get_reviews', 'get_media'
        ]
        for token in metadata_tokens:
            cur.execute("DELETE FROM cache WHERE key LIKE ?", (f'%{token}%',))
        cur.connection.commit()

    control.notify(
        f'{control.ADDON_NAME}: Metadata Cache',
        'Metadata cache successfully cleared.',
        time=4000, sound=False
    )


def prune_expired_cache(max_age_days=30):
    """Purge stale cache.db entries older than max_age_days to bound disk growth."""
    _init_cache_table()
    cutoff = int(time.time()) - (max_age_days * 86400)
    deleted = 0
    with SQL(control.cacheFile) as cur:
        cur.execute('DELETE FROM cache WHERE date < ?', (cutoff,))
        deleted = cur.rowcount
        cur.connection.commit()
    if deleted > 0:
        control.log(f"Database: Pruned {deleted} stale cache entries older than {max_age_days} days", level='info')
    return deleted


def checkpoint_databases(truncate=True):
    """Run PRAGMA wal_checkpoint(TRUNCATE) and PRAGMA optimize across all databases.

    Flushes the SQLite write-ahead log to disk and truncates the .db-wal file to
    0 bytes, preventing disk bloat on low-flash Android TV devices.
    """
    db_paths = [
        getattr(control, 'cacheFile', None),
        getattr(control, 'malSyncDB', None),
        getattr(control, 'searchHistoryDB', None),
        getattr(control, 'mappingDB', None),
    ]
    mode = "TRUNCATE" if truncate else "PASSIVE"
    for path in db_paths:
        if path and os.path.exists(path):
            try:
                with SQL(path) as cur:
                    cur.execute(f"PRAGMA wal_checkpoint({mode})")
                    cur.execute("PRAGMA optimize")
            except Exception as e:
                control.log(f"Failed to checkpoint {path}: {e}", 'warning')


# ═══════════════════════════════════════════════════════════════════════════
#  Show Operations
# ═══════════════════════════════════════════════════════════════════════════

def get_show(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM shows WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def update_show(mal_id, kodi_meta, anime_schedule_route=''):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'INSERT INTO shows (mal_id, kodi_meta, anime_schedule_route) VALUES (?, ?, ?) '
            'ON CONFLICT(mal_id) DO UPDATE SET kodi_meta=excluded.kodi_meta, anime_schedule_route=excluded.anime_schedule_route',
            (mal_id, kodi_meta, anime_schedule_route))
        cur.connection.commit()


def get_show_meta(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM shows_meta WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


_VALID_SYNC_TABLES = frozenset({'shows', 'episodes', 'shows_meta', 'show_data'})
_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_identifier(name):
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def update_show_meta(mal_id, meta_ids, art):
    with SQL(control.malSyncDB) as cur:
        cur.execute('PRAGMA foreign_keys=OFF')
        cur.execute(
            'REPLACE INTO shows_meta (mal_id, meta_ids, art) VALUES (?, ?, ?)',
            (mal_id, dumps(meta_ids), dumps(art)))
        cur.execute('PRAGMA foreign_keys=ON')
        cur.connection.commit()


def update_kodi_meta(mal_id, kodi_meta):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'UPDATE shows SET kodi_meta=? WHERE mal_id=?',
            (dumps(kodi_meta), mal_id))
        cur.connection.commit()


def add_mapping_id(mal_id, column, value):
    _validate_identifier(column)
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            f'UPDATE shows SET {column}=? WHERE mal_id=?', (value, mal_id))
        cur.connection.commit()


def get_show_data(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM show_data WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def update_show_data(mal_id, data, last_updated=''):
    with SQL(control.malSyncDB) as cur:
        cur.execute('PRAGMA foreign_keys=OFF')
        cur.execute(
            'REPLACE INTO show_data '
            '(mal_id, data, last_updated) VALUES (?, ?, ?)',
            (mal_id, dumps(data), last_updated))
        cur.execute('PRAGMA foreign_keys=ON')
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Episode Operations
# ═══════════════════════════════════════════════════════════════════════════

def get_episode(mal_id, episode=None):
    with SQL(control.malSyncDB) as cur:
        if episode:
            cur.execute(
                'SELECT * FROM episodes WHERE mal_id=? AND number=?',
                (mal_id, episode))
        else:
            cur.execute(
                'SELECT * FROM episodes WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def get_episode_list(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM episodes WHERE mal_id=?', (mal_id,))
        return cur.fetchall()


def update_episode(mal_id, season, number, update_time, kodi_meta,
                   filler='', anidb_ep_id=''):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'REPLACE INTO episodes '
            '(mal_id, season, kodi_meta, last_updated, number, filler, anidb_ep_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (mal_id, season, kodi_meta, update_time, number, filler, anidb_ep_id))
        cur.connection.commit()


def update_episode_column(mal_id, episode, column, value):
    _validate_identifier(column)
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            f'UPDATE episodes SET {column}=? WHERE mal_id=? AND number=?',
            (value, mal_id, episode))
        cur.connection.commit()


def update_episode_batch(episode_batch):
    """Batch insert/replace episodes in a single transaction using executemany."""
    if not episode_batch:
        return
    with SQL(control.malSyncDB) as cur:
        cur.executemany(
            'REPLACE INTO episodes '
            '(mal_id, season, kodi_meta, last_updated, number, filler, anidb_ep_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            episode_batch)
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Mapping & Info Lookups
# ═══════════════════════════════════════════════════════════════════════════

def get_mappings(anime_id, send_id):
    if not anime_id or not send_id:
        return {}
    try:
        _validate_identifier(send_id)
        with SQL(control.mappingDB, is_readonly=True) as cur:
            cur.execute(
                f'SELECT * FROM anime WHERE {send_id}=?', (anime_id,))
            rows = cur.fetchall()
            return rows[0] if rows else {}
    except Exception:
        pass
    return {}


def get_unique_ids(anime_id, send_id):
    if not anime_id or not send_id:
        return {}
    try:
        _validate_identifier(send_id)
        with SQL(control.mappingDB, is_readonly=True) as cur:
            cur.execute(
                f'SELECT mal_id, mal_dub_id, anilist_id, kitsu_id, anidb_id, '
                f'simkl_id, thetvdb_id, themoviedb_id, imdb_id, trakt_id '
                f'FROM anime WHERE {send_id}=?', (anime_id,))
            row = cur.fetchone()
            if not row:
                return {}
            return {
                'mal_id':     row.get('mal_id'),
                'mal_dub_id': row.get('mal_dub_id'),
                'anilist_id': row.get('anilist_id'),
                'kitsu_id':   row.get('kitsu_id'),
                'anidb':      row.get('anidb_id'),
                'simkl':      row.get('simkl_id'),
                'tvdb':       row.get('thetvdb_id'),
                'tmdb':       row.get('themoviedb_id'),
                'imdb':       row.get('imdb_id'),
                'trakt':      row.get('trakt_id'),
            }
    except Exception:
        pass
    return {}


def get_mal_ids(anime_id, send_id):
    if not anime_id or not send_id:
        return []
    try:
        _validate_identifier(send_id)
        with SQL(control.mappingDB, is_readonly=True) as cur:
            cur.execute(
                f'SELECT * FROM anime WHERE {send_id}=?', (anime_id,))
            return cur.fetchall() or []
    except Exception:
        pass
    return []


_BUILTIN_API_INFO = {
    'Simkl': {'api_name': 'Simkl', 'api_key': '', 'client_id': '59dfdc579d244e1edf6f89874d521d37a69a95a1abd349910cb056a1872ba2c8', 'client_secret': '', 'description': 'Simkl API'},
    'MyAnimeList': {'api_name': 'MyAnimeList', 'api_key': '', 'client_id': 'a8d85a4106b259b8c9470011ce2f76bc', 'client_secret': '', 'description': 'MyAnimeList API'},
    'Real-Debrid': {'api_name': 'Real-Debrid', 'api_key': '', 'client_id': 'X245A4XAIBGVM', 'client_secret': '', 'description': 'Real-Debrid API'},
    'Premiumize': {'api_name': 'Premiumize', 'api_key': '', 'client_id': '807831898', 'client_secret': '', 'description': 'Premiumize API'},
    'Debrid-Link': {'api_name': 'Debrid-Link', 'api_key': '', 'client_id': 'sdpBuYFQo6L53s3B4apluw', 'client_secret': '', 'description': 'Debrid-Link API'},
    'Fanart-TV': {'api_name': 'Fanart-TV', 'api_key': 'dfe6380e34f49f9b2b9518184922b49c', 'client_id': '', 'client_secret': '', 'description': 'Fanart-TV API'},
    'Anime-Skip': {'api_name': 'Anime-Skip', 'api_key': '', 'client_id': 'buT57NJMu4G65vxGJWdj4UXgnq65Agfi', 'client_secret': '', 'description': 'Anime-Skip API'},
    'AniDB': {'api_name': 'AniDB', 'api_key': '', 'client_id': 'otakukodi', 'client_secret': '', 'description': 'AniDB API'},
    'TMDB': {'api_name': 'TMDB', 'api_key': '6974ec27debf5cce1218136e2a36f64b', 'client_id': '', 'client_secret': '', 'description': 'The Movie Database API'},
    'Teamup': {'api_name': 'Teamup', 'api_key': '7d05c918d14d9a89347492f8916e3a76457de61dd3303e9a31aecb971d6c8149', 'client_id': '', 'client_secret': '', 'description': 'Teamup API'},
    'AnimeSchedule': {'api_name': 'AnimeSchedule', 'api_key': '', 'client_id': '2zuyXQUF6qxMqaEXZ6nP', 'client_secret': 'mSFcWD3lXURQXPAoKHKI5qpV42x6oq', 'description': 'AnimeSchedule API'},
    'MDBList': {'api_name': 'MDBList', 'api_key': '7zya5tee3ruf73cubnb85dsyr', 'client_id': '', 'client_secret': '', 'description': 'MDBList API'},
    'TVDB': {'api_name': 'TVDB', 'api_key': 'edae60dc-1b44-4bac-8db7-65c0aaf5258b', 'client_id': '', 'client_secret': '', 'description': 'TheTVDB API'},
    'Trakt': {'api_name': 'Trakt', 'api_key': '', 'client_id': 'e6a379effbda0b40f5ae06d39336b3c716c7fb86562327a0125f29959b5d5c79', 'client_secret': '0bf24cdc6a51673f23ce065738f9cd35d87196f129ea8836f6372a53fa5d5b76', 'description': 'Trakt API'}
}


def get_info(api_name):
    row = None
    try:
        if getattr(control, 'infoDB', None) and os.path.exists(control.infoDB):
            with SQL(control.infoDB, is_readonly=True) as cur:
                cur.execute('SELECT * FROM info WHERE api_name=?', (api_name,))
                row = cur.fetchone()
    except (dbapi2.DatabaseError, dbapi2.OperationalError) as e:
        control.log(f"get_info error for {api_name}: {e}", 'debug')
    if row and (row.get('client_id') or row.get('api_key')):
        return row
    fallback = _BUILTIN_API_INFO.get(api_name)
    if fallback:
        return dict(fallback)
    return row or {'api_name': api_name, 'client_id': '', 'client_secret': '', 'api_key': ''}


def remove_from_database(table, mal_id):
    if table not in _VALID_SYNC_TABLES:
        raise ValueError(f"Invalid sync table: {table!r}")
    with SQL(control.malSyncDB) as cur:
        cur.execute(f'DELETE FROM {table} WHERE mal_id=?', (mal_id,))
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Watchlist Cache
# ═══════════════════════════════════════════════════════════════════════════

_WATCHLIST_SORT_COLUMNS = {
    'title': 'title_en COLLATE NOCASE',
    'title_en': 'title_en COLLATE NOCASE',
    'name': 'title_en COLLATE NOCASE',
    'title_romaji': 'title_romaji COLLATE NOCASE',
    'score': 'score',
    'episodes': 'total_episodes',
    'total_episodes': 'total_episodes',
    'watched': 'episodes_watched',
    'progress': 'episodes_watched',
    'episodes_watched': 'episodes_watched',
    'remaining': 'episodes_remaining',
    'episodes_remaining': 'episodes_remaining',
    'date': 'release_date',
    'release_date': 'release_date',
    'updated': 'updated_at',
    'updated_at': 'updated_at',
    'order': 'item_order',
    'item_order': 'item_order',
    'default': 'item_order'
}


def get_watchlist_cache(service, status, limit=None, offset=0, sort_by=None, order='asc'):
    """Cached watchlist items, optionally sorted and paginated."""
    order_clause = 'DESC' if str(order).upper() == 'DESC' else 'ASC'
    col = _WATCHLIST_SORT_COLUMNS.get(sort_by, 'item_order') if sort_by else 'item_order'

    query = (
        f'SELECT * FROM v_watchlist_items '
        f'WHERE service=? AND status=? '
        f'ORDER BY {col} {order_clause}, id ASC'
    )
    params = [service, status]
    if limit is not None and int(limit) > 0:
        query += ' LIMIT ? OFFSET ?'
        params.extend([int(limit), int(offset)])

    def _exec():
        with SQL(control.malSyncDB) as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()

    res = None
    try:
        res = _exec()
    except Exception:
        pass

    if res is None:
        # View might not exist yet on legacy DBs; build it and retry once
        try:
            from resources.lib.ui.database_sync import SyncDatabase
            SyncDatabase._build_watchlist_view()
            res = _exec()
        except Exception:
            res = None

    if res is None:
        fallback_query = 'SELECT * FROM watchlist_cache WHERE service=? AND status=? ORDER BY item_order ASC, id ASC'
        fparams = [service, status]
        if limit is not None and int(limit) > 0:
            fallback_query += ' LIMIT ? OFFSET ?'
            fparams.extend([int(limit), int(offset)])
        with SQL(control.malSyncDB) as cur:
            cur.execute(fallback_query, tuple(fparams))
            fres = cur.fetchall()
            return fres if fres is not None else []

    return res


def get_watchlist_cache_count(service, status):
    """Count of cached items for a service / status pair."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT COUNT(*) as count FROM watchlist_cache '
            'WHERE service=? AND status=?', (service, status))
        row = cur.fetchone()
        return row['count'] if row else 0


def get_watchlist_cache_last_updated(service, status):
    """Oldest update timestamp for a service / status pair."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT MIN(last_updated) as last_updated FROM watchlist_cache '
            'WHERE service=? AND status=?', (service, status))
        row = cur.fetchone()
        return row['last_updated'] if row else None


def save_watchlist_cache(service, status, items):
    """Replace all cache entries for a service / status pair."""
    now = int(time.time())
    rows = [
        (service, status, _extract_mal_id(service, item), idx, dumps(item), now)
        for idx, item in enumerate(items)
    ]
    with SQL(control.malSyncDB) as cur:
        cur.execute('BEGIN IMMEDIATE')
        cur.execute(
            'DELETE FROM watchlist_cache WHERE service=? AND status=?',
            (service, status))
        if rows:
            cur.executemany(
                'INSERT INTO watchlist_cache '
                '(service, status, mal_id, item_order, data, last_updated) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                rows)
        cur.execute('COMMIT')


def _extract_mal_id(service, item):
    """Pull MAL ID from a watchlist item based on service structure."""
    extractors = {
        'simkl':   lambda i: i.get('show', {}).get('ids', {}).get('mal'),
        'kitsu':   lambda i: i.get('mal_id'),
        'mal':     lambda i: i.get('node', {}).get('id'),
        'anilist': lambda i: i.get('media', {}).get('idMal'),
    }
    fn = extractors.get(service)
    return fn(item) if fn else None


def clear_watchlist_cache(service=None, status=None):
    """Clear cache, optionally filtered by service and/or status."""
    with SQL(control.malSyncDB) as cur:
        if service and status:
            cur.execute(
                'DELETE FROM watchlist_cache WHERE service=? AND status=?',
                (service, status))
        elif service:
            cur.execute(
                'DELETE FROM watchlist_cache WHERE service=?', (service,))
        else:
            cur.execute('DELETE FROM watchlist_cache')
        cur.connection.commit()


def is_watchlist_cache_valid(service, status, cache_hours=24):
    """Safety-net fallback (primary invalidation is activity-based)."""
    last = get_watchlist_cache_last_updated(service, status)
    return is_cache_valid(last, cache_hours) if last else False


# ═══════════════════════════════════════════════════════════════════════════
#  Watchlist Activity  (activity-based cache invalidation)
# ═══════════════════════════════════════════════════════════════════════════

def get_watchlist_activity(service):
    """Stored activity record for a watchlist service."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT * FROM watchlist_activity WHERE service=?', (service,))
        return cur.fetchone()


def save_watchlist_activity(service, activity_timestamp):
    """Save the last known activity timestamp for a service."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'REPLACE INTO watchlist_activity '
            '(service, activity_timestamp, last_checked) VALUES (?, ?, ?)',
            (service, str(activity_timestamp), int(time.time())))
        cur.connection.commit()


def clear_watchlist_activity(service=None):
    """Clear stored activity timestamps."""
    try:
        with SQL(control.malSyncDB) as cur:
            if service:
                cur.execute(
                    'DELETE FROM watchlist_activity WHERE service=?',
                    (service,))
            else:
                cur.execute('DELETE FROM watchlist_activity')
            cur.connection.commit()
    except (dbapi2.DatabaseError, dbapi2.OperationalError):
        pass  # table may not exist on first run


# ═══════════════════════════════════════════════════════════════════════════
#  AniList Enrichment Cache
# ═══════════════════════════════════════════════════════════════════════════

def get_all_watchlist_mal_ids():
    """All unique MAL IDs across every cached watchlist entry."""
    rows = []
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT DISTINCT mal_id FROM watchlist_cache '
            'WHERE mal_id IS NOT NULL')
        rows = cur.fetchall() or []
    result = []
    for row in rows:
        try:
            result.append(int(row['mal_id']))
        except (ValueError, TypeError):
            pass
    return result


def save_anilist_enrichment_batch(data_list):
    """Save AniList media objects keyed by ``idMal``."""
    if not data_list:
        return
    now = int(time.time())
    rows = [
        (int(item['idMal']), dumps(item), now)
        for item in data_list if item.get('idMal')
    ]
    if not rows:
        return
    with SQL(control.malSyncDB) as cur:
        cur.execute('BEGIN IMMEDIATE')
        cur.executemany(
            'REPLACE INTO anilist_enrichment '
            '(mal_id, data, last_updated) VALUES (?, ?, ?)',
            rows)
        cur.execute('COMMIT')


def get_anilist_enrichment_batch(mal_ids, max_age_hours=168):
    """Cached AniList enrichment for given MAL IDs (default 7 days max)."""
    if not mal_ids:
        return {}
    cutoff = int(time.time()) - (max_age_hours * 3600)
    result = {}
    with SQL(control.malSyncDB) as cur:
        ph = ','.join('?' for _ in mal_ids)
        cur.execute(
            f'SELECT * FROM anilist_enrichment '
            f'WHERE mal_id IN ({ph}) AND last_updated > ?',
            [int(m) for m in mal_ids] + [cutoff])
        for row in cur.fetchall():
            try:
                result[row['mal_id']] = loads(row['data'])
            except (pickle.UnpicklingError, EOFError, AttributeError, ValueError) as e:
                control.log(f"get_show_data unpickle error: {e}", 'debug')
    return result


def clear_anilist_enrichment():
    """Clear all AniList enrichment data."""
    with SQL(control.malSyncDB) as cur:
        cur.execute('DELETE FROM anilist_enrichment')
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Search History
# ═══════════════════════════════════════════════════════════════════════════

_SEARCH_TYPES = (
    'anime', 'movie', 'tv_show', 'tv_short',
    'special', 'ova', 'ona', 'music',
)


def _validate_search_type(media_type):
    if media_type not in _SEARCH_TYPES:
        raise ValueError(f"Invalid search history table: {media_type!r}")
    return media_type


def _ensure_search_tables(cur):
    tag = f"{control.searchHistoryDB}:search_tables"
    if tag in _tables_ready:
        return
    for t in _SEARCH_TYPES:
        cur.execute(f'CREATE TABLE IF NOT EXISTS {t} (value TEXT UNIQUE)')
    _tables_ready.add(tag)


def getSearchHistory(media_type):
    _validate_search_type(media_type)
    with SQL(control.searchHistoryDB) as cur:
        _ensure_search_tables(cur)
        cur.execute(f'SELECT value FROM {media_type} ORDER BY rowid DESC LIMIT 50')
        rows = cur.fetchall()
    return [row['value'] for row in rows]


def addSearchHistory(search_string, media_type):
    _validate_search_type(media_type)
    with SQL(control.searchHistoryDB) as cur:
        _ensure_search_tables(cur)
        cur.execute(
            f'REPLACE INTO {media_type} VALUES (?)', (search_string,))
        cur.connection.commit()


def clearSearchHistory():
    if not control.yesno_dialog(
            control.ADDON_NAME, "Clear all search history?"):
        return
    with SQL(control.searchHistoryDB) as cur:
        for t in _SEARCH_TYPES:
            cur.execute(f'DROP TABLE IF EXISTS {t}')
        cur.execute("VACUUM")
        cur.connection.commit()
    _tables_ready.discard(f"{control.searchHistoryDB}:search_tables")
    control.refresh()
    control.notify(
        control.ADDON_NAME, "Search History has been cleared", time=5000)


def clearSearchCatagory(media_type):
    _validate_search_type(media_type)
    if not control.yesno_dialog(
            control.ADDON_NAME, "Clear search history?"):
        return
    with SQL(control.searchHistoryDB) as cur:
        cur.execute(f'DROP TABLE IF EXISTS {media_type}')
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS {media_type} (value TEXT UNIQUE)')
        cur.connection.commit()
    control.refresh()
    control.notify(
        control.ADDON_NAME, "Search History has been cleared", time=5000)


def remove_search(table, value):
    _validate_search_type(table)
    norm = value.strip()
    deleted = 0
    try:
        with SQL(control.searchHistoryDB) as cur:
            _ensure_search_tables(cur)
            cur.execute(f'DELETE FROM {table} WHERE value=?', (norm,))
            deleted = cur.rowcount
            cur.connection.commit()
    except Exception:
        deleted = 0
    control.refresh()
    if deleted == 0:
        control.notify(
            control.ADDON_NAME,
            f"Search item not found: '{norm}'", time=3000)

# ═══════════════════════════════════════════════════════════════════════════
#  Season Pack & Playback Continuity Caching
# ═══════════════════════════════════════════════════════════════════════════

def set_season_pack(mal_id, season, source):
    """Cache the selected season pack source for subsequent episode playback."""
    if not source or not mal_id:
        return
    key = f"season_pack_{mal_id}_{season or 1}"
    source_copy = dict(source)
    source_repr = repr(source_copy)
    duration = 720  # 30 days
    _cache_write(key, source_repr)
    _mem_set(key, source_repr, duration)


def get_season_pack(mal_id, season=1):
    """Retrieve the cached season pack source for this show and season."""
    if not mal_id:
        return None
    key = f"season_pack_{mal_id}_{season or 1}"
    mem = _mem_get(key)
    if mem is not None:
        return mem
    _init_cache_table()
    row = None
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
        row = cur.fetchone()
    if row and is_cache_valid(row['date'], 720):
        try:
            data = ast.literal_eval(row['value'])
            if data:
                _mem_set(key, row['value'], 720)
                return data
        except (ValueError, SyntaxError) as e:
            control.log(f"cache_get parse error for {key}: {e}", 'debug')
    return None


def clear_season_pack(mal_id=None, season=None):
    """Purge cached season packs from SQLite and memory cache."""
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        if mal_id and season:
            key = f"season_pack_{mal_id}_{season}"
            cur.execute('DELETE FROM cache WHERE key=?', (key,))
            _mem_del(key)
        elif mal_id:
            cur.execute("DELETE FROM cache WHERE key LIKE ?", (f"season_pack_{mal_id}_%",))
            for s in range(1, 10):
                _mem_del(f"season_pack_{mal_id}_{s}")
        else:
            cur.execute("DELETE FROM cache WHERE key LIKE 'season_pack_%'")
            _bump_mem_generation()
        cur.connection.commit()


def set_episode_sources(mal_id, episode, sources):
    """Cache the scraped/sorted sources list for an episode (e.g. from background pre-scraping)."""
    if not sources or not mal_id:
        return
    key = f"episode_sources_{mal_id}_{episode}"
    sources_repr = repr(sources)
    duration = 4  # 4 hours cache for pre-scraped sources
    _cache_write(key, sources_repr)
    _mem_set(key, sources_repr, duration)


def get_episode_sources(mal_id, episode):
    """Retrieve pre-scraped sources for an episode if valid."""
    if not mal_id:
        return None
    key = f"episode_sources_{mal_id}_{episode}"
    mem = _mem_get(key)
    if mem is not None:
        return mem
    _init_cache_table()
    row = None
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
        row = cur.fetchone()
    if row and is_cache_valid(row['date'], 4):
        try:
            data = ast.literal_eval(row['value'])
            if data:
                _mem_set(key, row['value'], 4)
                return data
        except (ValueError, SyntaxError) as e:
            control.log(f"cache_get parse error for {key}: {e}", 'debug')
    return None


def clear_episode_sources(mal_id=None, episode=None):
    """Purge cached episode sources from SQLite and memory cache."""
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        if mal_id and episode:
            key = f"episode_sources_{mal_id}_{episode}"
            cur.execute('DELETE FROM cache WHERE key=?', (key,))
            _mem_del(key)
        elif mal_id:
            cur.execute("DELETE FROM cache WHERE key LIKE ?", (f"episode_sources_{mal_id}_%",))
            _bump_mem_generation()
        else:
            cur.execute("DELETE FROM cache WHERE key LIKE 'episode_sources_%'")
            _bump_mem_generation()
        cur.connection.commit()


def save_last_played_source(mal_id, source):
    """Save structured metadata of the last played source for smart scoring."""
    if not source or not mal_id:
        return
    key = f"last_played_{mal_id}"
    payload = {
        'release_title': source.get('release_title') or source.get('name') or '',
        'release_group': source_utils.extract_release_group(source.get('release_title') or source.get('name') or ''),
        'quality': source.get('quality', 0),
        'provider': source.get('provider', ''),
        'debrid_provider': source.get('debrid_provider', ''),
        'channel': source.get('channel', ''),
        'lang': source.get('lang', 0),
        'sub': source.get('sub', ''),
        'type': source.get('type', ''),
        'package': source_utils.is_season_pack(source),
        'hash': source.get('hash', '')
    }
    _cache_write(key, repr(payload))
    _mem_set(key, repr(payload), 720)


def get_last_played_source(mal_id):
    """Retrieve the last successfully played source profile for a show."""
    if not mal_id:
        return None
    key = f"last_played_{mal_id}"
    mem = _mem_get(key)
    if mem is not None:
        return mem
    _init_cache_table()
    row = None
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
        row = cur.fetchone()
    if row and is_cache_valid(row['date'], 720):
        try:
            data = ast.literal_eval(row['value'])
            if data:
                _mem_set(key, row['value'], 720)
                return data
        except (ValueError, SyntaxError) as e:
            control.log(f"cache_get parse error for {key}: {e}", 'debug')
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Database & Scraper Maintenance & Telemetry
# ═══════════════════════════════════════════════════════════════════════════

def _format_db_bytes(bytes_count):
    """Format byte count into human-readable string (B, KB, MB, GB)."""
    try:
        b = float(bytes_count or 0)
    except (ValueError, TypeError):
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024.0:
            return f"{b:.2f} {unit}"
        b /= 1024.0
    return f"{b:.2f} TB"


def get_database_stats():
    """
    Generate structured telemetry report on all Otaku SQLite databases,
    table row counts, page allocations, and storage footprint.
    """
    db_paths = [
        ('Cache Database', getattr(control, 'cacheFile', None)),
        ('Watchlist & Metadata Sync', getattr(control, 'malSyncDB', None)),
        ('Search History', getattr(control, 'searchHistoryDB', None)),
        ('Anime ID Mappings', getattr(control, 'mappingDB', None)),
    ]

    lines = []
    lines.append("═══════════════════════════════════════════════════════════════════")
    lines.append("       OTAKU DATABASE & STORAGE TELEMETRY REPORT")
    lines.append("═══════════════════════════════════════════════════════════════════")
    lines.append("")

    total_storage = 0

    for db_label, db_path in db_paths:
        lines.append(f"▶ {db_label}")
        if not db_path:
            lines.append("   Path: [Not Configured]")
            lines.append("")
            continue
        lines.append(f"   Path: {db_path}")
        if not os.path.exists(db_path):
            lines.append("   Status: File does not exist yet (created on first write)")
            lines.append("")
            continue

        try:
            main_size = os.path.getsize(db_path)
            wal_path = f"{db_path}-wal"
            shm_path = f"{db_path}-shm"
            wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
            shm_size = os.path.getsize(shm_path) if os.path.exists(shm_path) else 0
            db_total = main_size + wal_size + shm_size
            total_storage += db_total

            lines.append(f"   Storage: {_format_db_bytes(main_size)} (Main) | {_format_db_bytes(wal_size)} (WAL) | {_format_db_bytes(shm_size)} (SHM)")
            lines.append(f"   Total Footprint: {_format_db_bytes(db_total)}")

            with SQL(db_path, is_readonly=True) as cur:
                cur.execute("PRAGMA journal_mode")
                j_mode = (cur.fetchone() or {}).get('journal_mode', 'unknown')
                cur.execute("PRAGMA page_count")
                p_count = (cur.fetchone() or {}).get('page_count', 0)
                cur.execute("PRAGMA page_size")
                p_size = (cur.fetchone() or {}).get('page_size', 0)
                cur.execute("PRAGMA freelist_count")
                f_count = (cur.fetchone() or {}).get('freelist_count', 0)

                lines.append(f"   Engine: Journal={str(j_mode).upper()} | PageSize={p_size} B | Pages={p_count:,} (Free: {f_count:,})")

                # Table row counts
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
                tables = [r['name'] for r in cur.fetchall()]
                if tables:
                    table_summaries = []
                    for tbl in tables:
                        try:
                            cur.execute(f"SELECT COUNT(*) as c FROM \"{tbl}\"")
                            cnt = (cur.fetchone() or {}).get('c', 0)
                            table_summaries.append(f"{tbl}: {cnt:,} rows")
                        except Exception:
                            table_summaries.append(f"{tbl}: ?")
                    lines.append(f"   Tables ({len(tables)}): " + " | ".join(table_summaries))
                else:
                    lines.append("   Tables: None")
        except Exception as e:
            lines.append(f"   Error reading telemetry: {e}")
        lines.append("")

    lines.append("───────────────────────────────────────────────────────────────────")
    lines.append(f"Total Otaku Database Footprint: {_format_db_bytes(total_storage)}")
    lines.append("═══════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def get_scraper_metrics_report():
    """
    Generate telemetry dashboard report for scrapers, circuit breakers,
    and provider cache health.
    """
    lines = []
    lines.append("═══════════════════════════════════════════════════════════════════")
    lines.append("       OTAKU SCRAPER HEALTH & LATENCY DASHBOARD")
    lines.append("═══════════════════════════════════════════════════════════════════")
    lines.append("")

    # 1. Scraper Circuit Breaker Status
    try:
        from resources.lib.pages import circuit_breaker
        with circuit_breaker._lock:
            failures = dict(circuit_breaker._failures)
            cooldowns = dict(circuit_breaker._cooldown_until)

        lines.append("▶ Scraper Circuit Breaker Status")
        now = time.time()
        active_cooldowns = {p: int(cd - now) for p, cd in cooldowns.items() if cd > now}

        if active_cooldowns:
            lines.append("   ⚠️ Tripped Scrapers (Cooling Down):")
            for provider, rem_sec in sorted(active_cooldowns.items()):
                fail_cnt = failures.get(provider, 0)
                lines.append(f"      • {provider}: {rem_sec}s remaining ({fail_cnt} consecutive errors)")
        else:
            lines.append("   ✓ All Scraper Circuits Healthy (No Active Tripped Breakers)")

        if failures:
            lines.append("   Current Failure Counters:")
            for p, cnt in sorted(failures.items()):
                lines.append(f"      • {p}: {cnt} error(s)")
        else:
            lines.append("   Failure Counters: All zero")
    except Exception as e:
        lines.append(f"   Circuit Breaker Telemetry Error: {e}")
    lines.append("")

    # 2. Dynamic Domain Mirrors Status
    lines.append("▶ Dynamic Domain Mirrors")
    try:
        from resources.lib.ui import domains
        active_domains = domains.get_all_domains()
        if active_domains:
            for scraper_name, d_url in sorted(active_domains.items()):
                lines.append(f"   • {scraper_name}: {d_url}")
        else:
            lines.append("   Using default hardcoded scraper domains")
    except Exception as e:
        lines.append(f"   Domain Mirror Error: {e}")
    lines.append("")

    # 3. Provider Cache Statistics
    lines.append("▶ Scraper & Provider Cache Health")
    try:
        if control.cacheFile and os.path.exists(control.cacheFile):
            with SQL(control.cacheFile) as cur:
                cur.execute("SELECT COUNT(*) as c FROM cache")
                total_cache = (cur.fetchone() or {}).get('c', 0)

                cur.execute("SELECT COUNT(*) as c FROM cache WHERE key LIKE 'show_sources_%' OR key LIKE 'show_scrapers_%' OR key LIKE 'last_played_%'")
                provider_entries = (cur.fetchone() or {}).get('c', 0)

                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='debrid_cache'")
                has_debrid = cur.fetchone()
                debrid_entries = 0
                if has_debrid:
                    cur.execute("SELECT COUNT(*) as c FROM debrid_cache")
                    debrid_entries = (cur.fetchone() or {}).get('c', 0)

                lines.append(f"   • Total Cache Rows: {total_cache:,}")
                lines.append(f"   • Provider Source Cache Rows: {provider_entries:,}")
                lines.append(f"   • Debrid Hash Availability Cache Rows: {debrid_entries:,}")
        else:
            lines.append("   • Cache database not yet created")
    except Exception as e:
        lines.append(f"   Provider Cache Error: {e}")

    lines.append("")
    lines.append("───────────────────────────────────────────────────────────────────")
    lines.append("Tip: Use 'Clear Scraper Telemetry' in Settings to reset all circuit")
    lines.append("breakers and clear stale scraper result caches.")
    lines.append("═══════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def clear_scraper_metrics():
    """Reset scraper circuit breakers and clear scraper cache entries."""
    try:
        from resources.lib.pages import circuit_breaker
        circuit_breaker.reset()
        control.log("ScraperCircuitBreaker: All circuits and counters reset", 'info')
    except Exception as e:
        control.log(f"Error resetting scraper circuit breaker: {e}", 'warning')

    cache_clear_providers()


def vacuum_all_databases():
    """
    Run SQLite VACUUM and WAL checkpoints across all Otaku databases,
    reclaiming fragmented space and returning the total bytes reclaimed.
    """
    db_paths = [
        getattr(control, 'cacheFile', None),
        getattr(control, 'malSyncDB', None),
        getattr(control, 'searchHistoryDB', None),
        getattr(control, 'mappingDB', None),
    ]

    total_reclaimed = 0

    for path in db_paths:
        if path and os.path.exists(path):
            try:
                wal_path = f"{path}-wal"
                size_before = os.path.getsize(path) + (os.path.getsize(wal_path) if os.path.exists(wal_path) else 0)

                with SQL(path) as cur:
                    cur.execute("VACUUM")
                    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    cur.execute("PRAGMA optimize")

                size_after = os.path.getsize(path) + (os.path.getsize(wal_path) if os.path.exists(wal_path) else 0)
                reclaimed = max(0, size_before - size_after)
                total_reclaimed += reclaimed
                control.log(f"Vacuumed {os.path.basename(path)}: reclaimed {_format_db_bytes(reclaimed)}", 'info')
            except Exception as e:
                control.log(f"Failed to vacuum {path}: {e}", 'warning')

    return total_reclaimed


def check_database_integrity():
    """
    Run PRAGMA quick_check / integrity_check across all databases.
    Returns (all_ok: bool, results: dict of {db_name: status_str}).
    """
    db_paths = [
        ('Cache Database', getattr(control, 'cacheFile', None)),
        ('Watchlist & Metadata Sync', getattr(control, 'malSyncDB', None)),
        ('Search History', getattr(control, 'searchHistoryDB', None)),
        ('Anime ID Mappings', getattr(control, 'mappingDB', None)),
    ]

    results = {}
    all_ok = True

    for name, path in db_paths:
        if not path or not os.path.exists(path):
            results[name] = "Not initialized"
            continue
        try:
            with SQL(path, is_readonly=True) as cur:
                cur.execute("PRAGMA integrity_check")
                row = cur.fetchone()
                status = row.get('integrity_check', 'ok') if row else 'ok'
                results[name] = status
                if str(status).lower() != 'ok':
                    all_ok = False
        except Exception as e:
            results[name] = f"Error: {e}"
            all_ok = False

    return all_ok, results


# ═══════════════════════════════════════════════════════════════════════════
#  Multipage Pre-Caching Job Queue (multipage_jobs table in cache.db)
# ═══════════════════════════════════════════════════════════════════════════

def _init_multipage_jobs_table():
    _ensure_table(
        control.cacheFile, 'multipage_jobs',
        'CREATE TABLE IF NOT EXISTS multipage_jobs ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, '
        'job_key TEXT UNIQUE, '
        'provider TEXT, '
        'browser_method TEXT, '
        'url_path TEXT, '
        'route TEXT, '
        'params TEXT, '
        'current_page INTEGER, '
        'target_page INTEGER, '
        'status TEXT, '
        'priority INTEGER DEFAULT 0, '
        'error_count INTEGER DEFAULT 0, '
        'last_error TEXT, '
        'created_at INTEGER, '
        'updated_at INTEGER)'
    )
    _ensure_table(
        control.cacheFile, 'multipage_jobs_ix_status',
        'CREATE INDEX IF NOT EXISTS ix_multipage_jobs_status '
        'ON multipage_jobs (status, priority DESC, created_at ASC)'
    )
    _ensure_table(
        control.cacheFile, 'multipage_jobs_ix_updated',
        'CREATE INDEX IF NOT EXISTS ix_multipage_jobs_updated '
        'ON multipage_jobs (updated_at)'
    )


def enqueue_multipage_job(provider, browser_method, url_path, request_params, target_page=20, priority=0, current_page=2):
    """Idempotently enqueue a multipage pre-cache job into multipage_jobs table.

    Returns job_id (str) or None on failure.
    """
    _init_multipage_jobs_table()
    now = int(time.time())

    if isinstance(request_params, (dict, list)):
        params_str = json.dumps(request_params, sort_keys=True)
    else:
        params_str = str(request_params or '')

    route = str(url_path or browser_method or '')
    job_key = f"{provider}:{browser_method}:{url_path}:{generate_md5(params_str)}"

    try:
        with SQL(control.cacheFile) as cur:
            cur.execute(
                "SELECT id, status, current_page, target_page FROM multipage_jobs WHERE job_key=?",
                (job_key,)
            )
            existing = cur.fetchone()
            if existing:
                job_id = existing['id']
                existing_target = existing['target_page'] or 0
                existing_status = existing['status']

                if existing_status in ('pending', 'running'):
                    if target_page > existing_target:
                        cur.execute(
                            "UPDATE multipage_jobs SET target_page=?, updated_at=? WHERE id=?",
                            (int(target_page), now, job_id)
                        )
                        cur.connection.commit()
                    return str(job_id)
                elif existing_status in ('completed', 'failed'):
                    cur_page = existing['current_page'] or 1
                    if target_page > cur_page or existing_status == 'failed':
                        cur.execute(
                            "UPDATE multipage_jobs SET status='pending', target_page=?, error_count=0, last_error=NULL, updated_at=? WHERE id=?",
                            (int(target_page), now, job_id)
                        )
                        cur.connection.commit()
                    return str(job_id)
                return str(job_id)

            cur.execute(
                "INSERT INTO multipage_jobs "
                "(job_key, provider, browser_method, url_path, route, params, current_page, target_page, status, priority, error_count, last_error, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, NULL, ?, ?)",
                (job_key, str(provider), str(browser_method), str(url_path), route, params_str, int(current_page), int(target_page), int(priority), now, now)
            )
            cur.connection.commit()
            return str(cur.lastrowid)
    except Exception as e:
        control.log(f"enqueue_multipage_job error: {e}", level='error')
        return None


def dequeue_multipage_job(provider=None):
    """Atomically transitions highest priority pending job to 'running' with timestamp.

    Returns job dict or None.
    """
    _init_multipage_jobs_table()
    now = int(time.time())
    try:
        with SQL(control.cacheFile) as cur:
            if provider:
                cur.execute(
                    "SELECT * FROM multipage_jobs WHERE status='pending' AND provider=? ORDER BY priority DESC, created_at ASC LIMIT 1",
                    (provider,)
                )
            else:
                cur.execute(
                    "SELECT * FROM multipage_jobs WHERE status='pending' ORDER BY priority DESC, created_at ASC LIMIT 1"
                )
            job = cur.fetchone()
            if not job:
                return None

            job_id = job['id']
            cur.execute(
                "UPDATE multipage_jobs SET status='running', updated_at=? WHERE id=? AND status='pending'",
                (now, job_id)
            )
            if cur.rowcount > 0:
                cur.connection.commit()
                job_dict = dict(job)
                job_dict['status'] = 'running'
                job_dict['updated_at'] = now
                if 'job_id' not in job_dict and 'id' in job_dict:
                    job_dict['job_id'] = job_dict['id']
                if 'request_params' not in job_dict and 'params' in job_dict:
                    job_dict['request_params'] = job_dict['params']
                return job_dict
            cur.connection.commit()
    except Exception as e:
        control.log(f"dequeue_multipage_job error: {e}", level='error')
    return None


def update_multipage_job_progress(job_id, current_page):
    """Update current_page and updated_at heartbeat for job."""
    _init_multipage_jobs_table()
    now = int(time.time())
    try:
        with SQL(control.cacheFile) as cur:
            cur.execute(
                "UPDATE multipage_jobs SET current_page=?, updated_at=? WHERE id=?",
                (int(current_page), now, int(job_id))
            )
            cur.connection.commit()
            return cur.rowcount > 0
    except Exception as e:
        control.log(f"update_multipage_job_progress error: {e}", level='error')
        return False


def mark_multipage_job_done(job_id):
    """Mark job status as 'completed'."""
    _init_multipage_jobs_table()
    now = int(time.time())
    try:
        with SQL(control.cacheFile) as cur:
            cur.execute(
                "UPDATE multipage_jobs SET status='completed', updated_at=? WHERE id=?",
                (now, int(job_id))
            )
            cur.connection.commit()
            return cur.rowcount > 0
    except Exception as e:
        control.log(f"mark_multipage_job_done error: {e}", level='error')
        return False


def mark_multipage_job_failed(job_id, error=None, max_retries=3):
    """Increment error count. If error_count >= max_retries, mark 'failed', else reset to 'pending'."""
    _init_multipage_jobs_table()
    now = int(time.time())
    try:
        with SQL(control.cacheFile) as cur:
            cur.execute("SELECT error_count FROM multipage_jobs WHERE id=?", (int(job_id),))
            row = cur.fetchone()
            if not row:
                return False
            error_count = (row['error_count'] or 0) + 1
            new_status = 'failed' if error_count >= max_retries else 'pending'
            err_str = str(error) if error is not None else None
            cur.execute(
                "UPDATE multipage_jobs SET status=?, error_count=?, last_error=?, updated_at=? WHERE id=?",
                (new_status, error_count, err_str, now, int(job_id))
            )
            cur.connection.commit()
            return cur.rowcount > 0
    except Exception as e:
        control.log(f"mark_multipage_job_failed error: {e}", level='error')
        return False


def prune_stale_multipage_jobs(max_age_seconds=86400, running_timeout=300):
    """Reset stale running jobs (>running_timeout) to 'pending' and delete completed/failed jobs older than max_age_seconds.

    Returns total affected rows count.
    """
    _init_multipage_jobs_table()
    now = int(time.time())
    stale_running_cutoff = now - int(running_timeout)
    stale_purge_cutoff = now - int(max_age_seconds)
    total_affected = 0
    try:
        with SQL(control.cacheFile) as cur:
            cur.execute(
                "UPDATE multipage_jobs SET status='pending', updated_at=? WHERE status='running' AND updated_at < ?",
                (now, stale_running_cutoff)
            )
            total_affected += cur.rowcount

            cur.execute(
                "DELETE FROM multipage_jobs WHERE status IN ('completed', 'failed') AND updated_at < ?",
                (stale_purge_cutoff,)
            )
            total_affected += cur.rowcount
            cur.connection.commit()
    except Exception as e:
        control.log(f"prune_stale_multipage_jobs error: {e}", level='error')
    return total_affected


