"""
anime_skip.py - Anime-Skip Skip Times Endpoint
==============================================
Secondary fallback skip-time provider querying https://api.anime-skip.com/graphql
for anime titles missing from AniSkip.
"""

from resources.lib.ui import client, control, database


DEFAULT_CLIENT_ID = 'OyThx3MHD7dKuaNOk9c6N2LeR4fOmiRw'
ANIME_SKIP_GRAPHQL_URL = 'https://api.anime-skip.com/graphql'

ANIME_SKIP_TYPE_MAP = {
    '97e3629a-95e5-4b1a-9411-73a47c0d0e25': 'Branding',
    '9edc0037-fa4e-47a7-a29a-d9c43368daa8': 'Canon',
    '2a730a51-a601-439b-bc1f-7b94a640ffb9': 'Credits',
    'c48f1dce-1890-4394-8ce6-c3f5b2f95e5e': 'Filler',
    '14550023-2589-46f0-bfb4-152976506b4c': 'Intro',
    '6c4ade53-4fee-447f-89e4-3bb29184e87a': 'Mixed Credits',
    'cbb42238-d285-4c88-9e91-feab4bb8ae0a': 'Mixed Intro',
    'e384759b-3cd2-4824-9569-128363b4452b': 'Must Watch',
    'd839cdb1-21b3-455d-9c21-7ffeb37adbec': 'New Credits',
    '679fb610-ff3c-4cf4-83c0-75bcc7fe8778': 'New Intro',
    'c7b1eddb-defa-4bc6-a598-f143081cfe4b': 'Preview',
    'f38ac196-0d49-40a9-8fcf-f3ef2f40f127': 'Recap',
    '67321535-a4ea-4f21-8bed-fb3c8286b510': 'Title Card',
    '9f0c6532-ccae-4238-83ec-a2804fe5f7b0': 'Transition',
    'ae57fcf9-27b0-49a7-9a99-a91aa7518a29': 'Unknown'
}


def resolve_anilist_id(mal_id):
    """Resolve an AniList ID from local mappings.db, show_meta, or AniZip online mappings."""
    if not mal_id:
        return None

    try:
        mal_id_int = int(mal_id)
    except (ValueError, TypeError):
        mal_id_int = mal_id

    # 1. Primary lookup: SQLite mappings.db (instant local query)
    mapping = database.get_mappings(mal_id_int, 'mal_id') or {}
    anilist_id = mapping.get('anilist_id')

    # 2. Secondary lookup: local show_meta table
    if not anilist_id:
        show_meta = database.get_show_meta(mal_id_int)
        if show_meta and show_meta.get('meta_ids'):
            try:
                meta_ids = database.loads(show_meta['meta_ids'])
                anilist_id = meta_ids.get('anilist_id') or meta_ids.get('anilist')
            except Exception:
                pass

    # 3. Tertiary fallback: live AniZip/Simkl overlay via shared mappings resolver
    if not anilist_id:
        remote_map = database.resolve_mappings_with_fallback(
            mal_id_int, required_keys=('anilist_id',), require_all=False, fetch_remote=True
        ) or {}
        anilist_id = remote_map.get('anilist_id')

    return anilist_id or mal_id_int


def _fetch_skip_times(anilist_id, episode, client_id=None):
    """Direct single-trip GraphQL fetch of Anime-Skip intervals for an episode."""
    if not anilist_id:
        return {}

    api_key = client_id or control.getSetting('animeskip.apikey') or DEFAULT_CLIENT_ID
    headers = {
        'Content-Type': 'application/json',
        'X-Client-ID': api_key
    }

    query = '''
    query FindShows($service: ExternalService!, $serviceId: String!) {
        findShowsByExternalId(service: $service, serviceId: $serviceId) {
            id
            name
            episodes {
                id
                number
                timestamps {
                    at
                    typeId
                }
            }
        }
    }
    '''
    variables = {
        'service': 'ANILIST',
        'serviceId': str(anilist_id)
    }

    try:
        response = client.post(
            ANIME_SKIP_GRAPHQL_URL,
            headers=headers,
            json_data={'query': query, 'variables': variables},
            timeout=8.0
        )
        if not (response and response.ok):
            return {}

        data = control.safe_json(response, default={})
        shows = (data.get('data') or {}).get('findShowsByExternalId') or []

        candidate_timestamps = []
        for s in shows:
            for ep in s.get('episodes', []):
                try:
                    num = float(ep.get('number') or -1)
                except (ValueError, TypeError):
                    continue
                if int(num) == int(episode) and ep.get('timestamps'):
                    candidate_timestamps.append(ep['timestamps'])

        if not candidate_timestamps:
            return {}

        best_raw = max(candidate_timestamps, key=len)
        stamps = []
        for t in best_raw:
            at = t.get('at')
            if at is None or at < 0:
                continue
            tname = ANIME_SKIP_TYPE_MAP.get(t.get('typeId'), 'Unknown')
            stamps.append((float(at), tname))
        stamps.sort(key=lambda x: x[0])

        op = None
        ed = None
        for i, (at, name) in enumerate(stamps):
            if op is None and name in ('Intro', 'New Intro', 'Mixed Intro'):
                for next_at, next_name in stamps[i + 1:]:
                    if next_name != name:
                        op = {'startTime': round(at, 2), 'endTime': round(next_at, 2)}
                        break
            if ed is None and name in ('Credits', 'New Credits', 'Mixed Credits'):
                for next_at, next_name in stamps[i + 1:]:
                    if next_name != name:
                        ed = {'startTime': round(at, 2), 'endTime': round(next_at, 2)}
                        break
                if ed is None and i == len(stamps) - 1:
                    ed = {'startTime': round(at, 2), 'endTime': round(at + 90.0, 2)}

        return {'op': op, 'ed': ed}
    except Exception as e:
        control.log(f'Anime-Skip API error for AniList {anilist_id}: {e}', 'warning')
        return {}


def get_skip_times(mal_id, episode=1, skip_type='op', client_id=None):
    """High-level resolver: maps mal_id to AniList ID and extracts interval matching skip_type.

    Returns a dict matching the AniSkip response structure:
    {'results': [{'skipType': 'op'|'ed', 'interval': {'startTime': float, 'endTime': float}}]} or None.
    """
    anilist_id = resolve_anilist_id(mal_id)
    if not anilist_id:
        return None

    api_key = client_id or control.getSetting('animeskip.apikey') or DEFAULT_CLIENT_ID
    intervals = database.get(
        _fetch_skip_times,
        168,
        anilist_id,
        int(episode),
        api_key,
        key='animeskip'
    )
    if not intervals or not isinstance(intervals, dict):
        return None

    if skip_type in ('op', 'mixed-op', 'intro'):
        op = intervals.get('op')
        if op and op.get('startTime') is not None and op.get('endTime') is not None:
            return {
                'results': [{
                    'skipType': 'op',
                    'interval': {
                        'startTime': float(op['startTime']),
                        'endTime': float(op['endTime'])
                    }
                }]
            }
    elif skip_type in ('ed', 'mixed-ed', 'outro'):
        ed = intervals.get('ed')
        if ed and ed.get('startTime') is not None and ed.get('endTime') is not None:
            return {
                'results': [{
                    'skipType': 'ed',
                    'interval': {
                        'startTime': float(ed['startTime']),
                        'endTime': float(ed['endTime'])
                    }
                }]
            }

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Legacy Compatibility Shims
# ═══════════════════════════════════════════════════════════════════════════

def get_episode_ids(anilist_id, episode):
    """Legacy helper: find episode IDs matching episode number."""
    api_key = control.getSetting('animeskip.apikey') or DEFAULT_CLIENT_ID
    headers = {'Content-Type': 'application/json', 'X-Client-ID': api_key}
    query = '''
    query($service: ExternalService!, $serviceId: String!) {
        findShowsByExternalId(service: $service, serviceId: $serviceId) {
            episodes { id number }
        }
    }
    '''
    variables = {'service': 'ANILIST', 'serviceId': str(anilist_id)}
    try:
        response = client.post(ANIME_SKIP_GRAPHQL_URL, headers=headers, json_data={'query': query, 'variables': variables}, timeout=8.0)
        if response and response.ok:
            data = control.safe_json(response, default={})
            res = (data.get('data') or {}).get('findShowsByExternalId') or []
            id_list = []
            for resx in res:
                for x in resx.get('episodes', []):
                    if x.get('number') is not None:
                        try:
                            ep_num = int(float(x['number']))
                        except (ValueError, TypeError):
                            continue
                        if ep_num == int(episode):
                            id_list.append(x['id'])
            return id_list
    except Exception:
        pass
    return []


def get_time_stamps(id_list):
    """Legacy helper: query timestamps for a list of episode IDs."""
    if not id_list:
        return []
    api_key = control.getSetting('animeskip.apikey') or DEFAULT_CLIENT_ID
    headers = {'Content-Type': 'application/json', 'X-Client-ID': api_key}
    query = '''
        query($episodeId: ID!) {
            findTimestampsByEpisodeId(episodeId: $episodeId) {
                at
                type { name }
            }
        }
    '''
    for eid in id_list:
        try:
            response = client.post(ANIME_SKIP_GRAPHQL_URL, headers=headers, json_data={'query': query, 'variables': {'episodeId': eid}}, timeout=8.0)
            if response and response.ok:
                data = control.safe_json(response, default={})
                res = (data.get('data') or {}).get('findTimestampsByEpisodeId') or []
                if res:
                    return res
        except Exception:
            continue
    return []


def convert_time_stamps(time_stamp, intro, outro):
    """Legacy helper: convert list of timestamp dicts to intro/outro dict."""
    if not time_stamp:
        return None
    skip_times = {}
    for skip in time_stamp:
        skip_type = skip.get('type', {}).get('name') if isinstance(skip.get('type'), dict) else None
        skip_at = skip.get('at')
        if not skip_type or skip_at is None:
            continue
        if intro:
            if skip_type in ['Intro', 'Branding', 'New Intro', 'Mixed Intro']:
                skip_times['intro'] = {'start': skip_at}
            elif skip_times.get('intro') and not skip_times['intro'].get('end') and skip_type == 'Canon':
                skip_times['intro']['end'] = skip_at
        if outro:
            if skip_type in ['Credits', 'Mixed Credits', 'New Credits']:
                skip_times['outro'] = {'start': skip_at}
            elif skip_times.get('outro') and skip_type in ['Preview', 'Canon']:
                skip_times['outro']['end'] = skip_at
    return skip_times
