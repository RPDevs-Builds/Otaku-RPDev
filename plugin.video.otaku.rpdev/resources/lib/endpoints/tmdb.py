from resources.lib.ui import client, control, database

api_info = database.get_info('TMDB') or {}
apiKey = api_info.get('api_key', '')
baseUrl = "https://api.themoviedb.org/3/"
thumbPath = "https://image.tmdb.org/t/p/w500"
backgroundPath = "https://image.tmdb.org/t/p/original"


def _find_tmdb_id(external_id, external_source, prefer_movie=False):
    """Resolve a TMDb ID via /find/{external_id} using tvdb_id or imdb_id."""
    if not external_id:
        return None
    params = {'external_source': external_source, 'api_key': apiKey}
    response = client.get(f'{baseUrl}find/{external_id}', params=params)
    res = control.safe_json(response, default={}) if response else {}
    if not isinstance(res, dict):
        return None
    buckets = ('movie_results', 'tv_results') if prefer_movie else ('tv_results', 'movie_results')
    for key in buckets:
        items = res.get(key)
        if items and isinstance(items, list) and isinstance(items[0], dict) and items[0].get('id'):
            return items[0]['id']
    return None


def getArt(meta_ids, mtype, limit=None):
    art = {}
    mid = meta_ids.get('themoviedb_id')
    prefer_movie = str(mtype or '').lower().startswith('movie')
    if mid is None and not prefer_movie:
        mid = _find_tmdb_id(meta_ids.get('thetvdb_id'), 'tvdb_id', prefer_movie=False)
    if mid is None:
        mid = _find_tmdb_id(meta_ids.get('imdb_id'), 'imdb_id', prefer_movie=prefer_movie)

    if mid:
        params = {
            'include_image_language': 'en,ja,null',
            "api_key": apiKey
        }
        response = client.get(f'{baseUrl}{mtype[0:5]}/{mid}/images', params=params)
        res = control.safe_json(response, default={})

        if res:
            # Backdrops are for fanart (wide 16:9 background images)
            if res.get('backdrops'):
                backdrops = res['backdrops'][:limit] if limit else res['backdrops']
                items = [backgroundPath + item['file_path'] for item in backdrops if item.get('file_path')]
                art['fanart'] = items
                # Language-tagged backdrops make clean 16:9 landscape thumbnails
                lang_backdrops = [backgroundPath + item['file_path'] for item in res['backdrops'] if item.get('file_path') and item.get('iso_639_1') in ('en', 'ja')]
                if lang_backdrops:
                    art['thumb'] = lang_backdrops[:1]

            # Posters are 2:3 portrait images
            if res.get('posters'):
                posters = res['posters'][:limit] if limit else res['posters']
                items = [thumbPath + item['file_path'] for item in posters if item.get('file_path')]
                art['poster'] = items

            # Logos are clearlogos (transparent PNG title/logo images)
            if res.get('logos'):
                logos = res['logos'][:limit] if limit else res['logos']
                items = [backgroundPath + item["file_path"] for item in logos if item.get('file_path')]
                art['clearlogo'] = items
    return art


def searchByTitle(title, mtype):
    """Search TMDB by title and return the discovered TMDB ID, or None."""
    if not title:
        return None
    search_type = 'movie' if mtype == 'movies' else 'tv'
    params = {
        'query': title,
        'api_key': apiKey
    }
    response = client.get(f'{baseUrl}search/{search_type}', params=params)
    res = control.safe_json(response, default={})
    results = res.get('results', [])
    if results:
        return results[0].get('id')
    return None


def get_episode_titles(tmdb_id, season_number, episode_number):
    params = {
        'include_image_language': 'en,ja,null',
        "api_key": apiKey
    }
    response = client.get(f'{baseUrl}tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/translations', params=params)
    res = control.safe_json(response, default={})

    # Extract English name, fallback to Japanese if not found
    translations = res.get('translations', [])
    for t in translations:
        if t.get('iso_639_1') == 'en':
            data = t.get('data', {})
            name = data.get('name')
            if name:
                return [name]
    for t in translations:
        if t.get('iso_639_1') == 'ja':
            data = t.get('data', {})
            name = data.get('name')
            if name:
                return [name]
    return []
