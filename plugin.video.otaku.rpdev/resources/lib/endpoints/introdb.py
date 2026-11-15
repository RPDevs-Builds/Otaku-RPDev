"""
introdb.py - IntroDB Skip Times Endpoint
========================================
Fallback skip-time provider querying https://api.introdb.app
for anime titles missing from AniSkip.
"""

from resources.lib.ui import client, control, database


INTRODB_BASE_URL = 'https://api.introdb.app'


def resolve_imdb_and_season(mal_id, episode=1):
    """Resolve an IMDb ID, TVDB season number, and movie flag from local metadata."""
    if not mal_id:
        return None, 1, False

    try:
        mal_id_int = int(mal_id)
    except (ValueError, TypeError):
        mal_id_int = mal_id

    # 1. Primary lookup: SQLite mappings.db (instant local query)
    mapping = database.get_mappings(mal_id_int, 'mal_id') or {}
    imdb_id = mapping.get('imdb_id')
    season = mapping.get('thetvdb_season')
    media_type = mapping.get('anime_media_type') or mapping.get('global_media_type')

    # 2. Secondary lookup: local show_meta table
    if not imdb_id:
        show_meta = database.get_show_meta(mal_id_int)
        if show_meta and show_meta.get('meta_ids'):
            try:
                meta_ids = database.loads(show_meta['meta_ids'])
                imdb_id = meta_ids.get('imdb_id') or meta_ids.get('imdb')
            except Exception:
                pass

    # 3. Tertiary fallback: AniZip online mappings
    if not imdb_id:
        try:
            url = f'https://api.ani.zip/mappings?mal_id={mal_id_int}'
            resp = client.get(url, timeout=3.0)
            if resp and resp.ok:
                data = control.safe_json(resp, default={})
                mappings = data.get('mappings') or {}
                imdb_id = mappings.get('imdb_id')
                if not media_type:
                    media_type = mappings.get('type')
        except Exception:
            pass

    if not media_type:
        media_type = 'TV'

    # Normalize season to positive integer
    if season in (None, '', '0', 0, 'a'):
        season = 1
    else:
        try:
            season = max(1, int(season))
        except (ValueError, TypeError):
            season = 1

    is_movie = str(media_type).upper() == 'MOVIE'
    return imdb_id, season, is_movie


def _fetch_segments(imdb_id, season, episode, is_movie):
    """Direct HTTP fetch of IntroDB segments for a title."""
    if not imdb_id:
        return None

    if is_movie:
        url = f'{INTRODB_BASE_URL}/segments?imdb_id={imdb_id}&is_movie=true'
    else:
        url = f'{INTRODB_BASE_URL}/segments?imdb_id={imdb_id}&season={season}&episode={episode}'

    try:
        response = client.get(url, headers={'User-Agent': 'Mozilla/5.0 (Otaku-RPDev)'}, timeout=5.0)
        if response and response.ok:
            data = control.safe_json(response, default={})
            if data and (data.get('intro') or data.get('outro') or data.get('recap') or data.get('post_credits')):
                return data
    except Exception as e:
        control.log(f'IntroDB API error for {imdb_id}: {e}', 'warning')

    return None


def get_segments(imdb_id, season=1, episode=1, is_movie=False):
    """Retrieve segments from IntroDB with 168-hour (7 days) database caching."""
    if not imdb_id:
        return None
    return database.get(
        _fetch_segments,
        168,
        imdb_id,
        season,
        episode,
        is_movie,
        key='introdb'
    )


def get_skip_times(mal_id, episode=1, skip_type='op'):
    """High-level resolver: maps mal_id to IMDb ID and extracts interval matching skip_type.

    Returns a dict matching the AniSkip response structure:
    {'results': [{'skipType': 'op'|'ed', 'interval': {'startTime': float, 'endTime': float}}]} or None.
    """
    imdb_id, season, is_movie = resolve_imdb_and_season(mal_id, episode)
    if not imdb_id:
        return None

    segments = get_segments(imdb_id, season=season, episode=episode, is_movie=is_movie)
    if not segments:
        return None

    if skip_type in ('op', 'mixed-op', 'intro'):
        intro = segments.get('intro')
        if intro and intro.get('start_sec') is not None and intro.get('end_sec') is not None:
            return {
                'results': [{
                    'skipType': 'op',
                    'interval': {
                        'startTime': float(intro['start_sec']),
                        'endTime': float(intro['end_sec'])
                    }
                }]
            }
    elif skip_type in ('ed', 'mixed-ed', 'outro'):
        outro = segments.get('outro')
        if outro and outro.get('start_sec') is not None and outro.get('end_sec') is not None:
            return {
                'results': [{
                    'skipType': 'ed',
                    'interval': {
                        'startTime': float(outro['start_sec']),
                        'endTime': float(outro['end_sec'])
                    }
                }]
            }

    return None


def get_extra_segments(mal_id, episode=1):
    """Retrieve non-standard skip segments (recap and post-credits) if available."""
    imdb_id, season, is_movie = resolve_imdb_and_season(mal_id, episode)
    if not imdb_id:
        return {}

    segments = get_segments(imdb_id, season=season, episode=episode, is_movie=is_movie)
    if not segments:
        return {}

    extras = {}
    recap = segments.get('recap')
    if recap and recap.get('start_sec') is not None and recap.get('end_sec') is not None:
        extras['recap'] = {
            'startTime': float(recap['start_sec']),
            'endTime': float(recap['end_sec'])
        }
    post_credits = segments.get('post_credits')
    if post_credits and post_credits.get('start_sec') is not None and post_credits.get('end_sec') is not None:
        extras['post_credits'] = {
            'startTime': float(post_credits['start_sec']),
            'endTime': float(post_credits['end_sec'])
        }
    return extras
