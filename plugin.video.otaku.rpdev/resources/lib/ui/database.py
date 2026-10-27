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
            return json.loads(blob.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _SafeUnpickler(io.BytesIO(blob)).load()
    if isinstance(blob, str):
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return _SafeUnpickler(io.BytesIO(blob.encode('latin-1'))).load()
    return {}


# ═══════════════════════════════════════════════════════════════════════════
#  SQL - Thread-Local Pooled SQLite Context Manager (WAL-mode concurrent)
# ═══════════════════════════════════════════════════════════════════════════

_thread_local = threading.local()


def _dict_factory(cursor, row):
    """Row factory that returns dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _get_thread_conns():
    conns = getattr(_thread_local, 'conns', None)
    if conns is None:
        conns = {}
        _thread_local.conns = conns
    return conns


def close_thread_connections(path=None):
    """Close cached SQLite connections for the current thread."""
    conns = getattr(_thread_local, 'conns', None)
    if not conns:
        return
    if path is not None:
        target = os.path.abspath(path)
        entry = conns.pop(target, None)
        if entry:
            try:
                entry[0].close()
            except (dbapi2.Error, OSError) as e:
                control.log(f"database close error: {e}", 'debug')
    else:
        for _, (conn, _) in list(conns.items()):
            try:
                conn.close()
            except (dbapi2.Error, OSError) as e:
                control.log(f"database pool close error: {e}", 'debug')
        conns.clear()


atexit.register(close_thread_connections)


class SQL:
    """Thread-local pooled SQLite context manager with optimized PRAGMAs.

    WAL journal mode allows concurrent readers without locking.
    isolation_level=None enables autocommit for faster writes.

    Usage::

        with SQL(db_path) as cursor:
            cursor.execute('SELECT ...')
            cursor.connection.commit()   # needed for writes
    """

    def __init__(self, path, timeout=30):
        self.path = path
        self.timeout = timeout
        self._conn = None
        self._cursor = None

    def __enter__(self):
        abs_path = os.path.abspath(self.path)
        info_path = os.path.abspath(control.infoDB) if getattr(control, 'infoDB', None) else ''
        is_readonly = (abs_path == info_path)

        if not is_readonly and not xbmcvfs.exists(control.dataPath):
            xbmcvfs.mkdirs(control.dataPath)

        conns = _get_thread_conns()
        st_ino = None
        if os.path.exists(abs_path):
            try:
                st_ino = os.stat(abs_path).st_ino
            except OSError:
                st_ino = None

        if abs_path in conns:
            cached_conn, cached_ino = conns[abs_path]
            if st_ino is None or (cached_ino is not None and st_ino != cached_ino):
                try:
                    cached_conn.close()
                except (dbapi2.Error, OSError) as e:
                    control.log(f"cached db close error: {e}", 'debug')
                conns.pop(abs_path, None)

        try:
            if abs_path not in conns:
                conn = dbapi2.connect(self.path, timeout=self.timeout, isolation_level=None)
                conn.row_factory = _dict_factory
                if not is_readonly:
                    conn.execute("PRAGMA foreign_keys = ON")
                    conn.execute("PRAGMA synchronous = NORMAL")
                    try:
                        conn.execute("PRAGMA journal_mode = WAL")
                    except dbapi2.DatabaseError:
                        pass
                    mmap_size = 4194304 if control.is_low_memory() else 16777216
                    conn.execute(f"PRAGMA mmap_size = {mmap_size}")
                if os.path.exists(abs_path):
                    try:
                        st_ino = os.stat(abs_path).st_ino
                    except OSError:
                        st_ino = None
                conns[abs_path] = (conn, st_ino)

            self._conn = conns[abs_path][0]
            self._cursor = self._conn.cursor()
            return self._cursor
        except Exception:
            close_thread_connections(self.path)
            self._conn = None
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

            if exc_type is OperationalError:
                import traceback
                control.log('database OperationalError', level='error')
                control.log(''.join(traceback.format_exception(
                    exc_type, exc_val, exc_tb)), level='error')
                return True
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


def _get_mem_prefix():
    gen = _window.getProperty(_MEM_GEN_PROP) or '0'
    return f'{control.ADDON_ID}_c{gen}_'


def _bump_mem_generation():
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
    """Store *value_repr* (a ``repr()`` string) with an expiry of *hours*."""
    expires = int(time.time() + hours * 3600)
    _window.setProperty(_get_mem_prefix() + key, f"{expires}|{value_repr}")


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


def remove(function, *args, **kwargs):
    """Remove the cached value for a function call."""
    try:
        key = _hash_function(function, args, kwargs)
        _cache_delete(key)
        _mem_del(key)
        return True
    except Exception:
        return False


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
        cur.execute(
            'REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)',
            (key, value_repr, int(time.time())))
        cur.connection.commit()


def _cache_delete(key):
    with SQL(control.cacheFile) as cur:
        cur.execute('DELETE FROM cache WHERE key=?', (key,))
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
        cur.execute("DELETE FROM cache WHERE key LIKE 'last_played_%'")

        # 2. Purge cached scraper results for all providers (torrents, embeds, hosters)
        provider_tokens = [
            'nyaa', 'animetosho', 'nekobt', 'torrentio', 'easynews',
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
        with SQL(control.mappingDB) as cur:
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
        with SQL(control.mappingDB) as cur:
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
        with SQL(control.mappingDB) as cur:
            cur.execute(
                f'SELECT * FROM anime WHERE {send_id}=?', (anime_id,))
            return cur.fetchall() or []
    except Exception:
        pass
    return []


def get_info(api_name):
    row = None
    try:
        with SQL(control.infoDB) as cur:
            cur.execute('SELECT * FROM info WHERE api_name=?', (api_name,))
            row = cur.fetchone()
    except (dbapi2.DatabaseError, dbapi2.OperationalError) as e:
        control.log(f"get_info error for {api_name}: {e}", 'debug')
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

            with SQL(db_path) as cur:
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
        active_domains = getattr(domains, 'DOMAINS', {})
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
            with SQL(path) as cur:
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

