import json
import os

from resources.lib.ui import control, database

# Cache the mal_dub JSON in memory so it's only read from disk once
_mal_dub_cache = None


class _MalDubMap(dict):
    """Dictionary backed by mal_dub.json with read-only mappings.db mal_dub_id fallback."""

    def __init__(self, initial=None):
        super().__init__(initial or {})
        self._miss_cache = set()

    def _lookup_db(self, key):
        s_key = str(key or '').strip()
        if not s_key or not s_key.isdigit() or s_key in self._miss_cache:
            return None
        row = database.get_mappings(int(s_key), 'mal_id')
        dub_id = row.get('mal_dub_id') if isinstance(row, dict) else None
        if dub_id:
            self[s_key] = dub_id
            return dub_id
        self._miss_cache.add(s_key)
        return None

    def get(self, key, default=None):
        val = super().get(key)
        if val is not None:
            return val
        found = self._lookup_db(key)
        return found if found is not None else default

    def __contains__(self, key):
        if super().__contains__(key):
            return True
        return self._lookup_db(key) is not None


def _get_mal_dub():
    global _mal_dub_cache
    if _mal_dub_cache is None:
        raw = None
        try:
            with open(control.maldubFile) as file:
                raw = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = None
        if isinstance(raw, dict) and raw:
            _mal_dub_cache = _MalDubMap(raw)
        else:
            # Prefer mappings.db mal_dub_id directly when mal_dub.json is retired/absent
            db_dubs = {}
            try:
                if getattr(control, 'mappingDB', None) and os.path.exists(control.mappingDB):
                    with database.SQL(control.mappingDB, is_readonly=True) as cur:
                        rows = cur.execute('SELECT mal_id, mal_dub_id FROM anime WHERE mal_dub_id IS NOT NULL').fetchall() or []
                        for r in rows:
                            db_dubs[str(r['mal_id'])] = r['mal_dub_id']
            except Exception:
                db_dubs = {}
            _mal_dub_cache = _MalDubMap(db_dubs)
    return _mal_dub_cache


def div_flavor(f):
    def wrapper(*args, **kwargs):
        if control.getBool('divflavors.dubonly') or control.getBool('divflavors.showdub'):
            return f(*args, **kwargs, mal_dub=_get_mal_dub())
        return f(*args, **kwargs)
    return wrapper
