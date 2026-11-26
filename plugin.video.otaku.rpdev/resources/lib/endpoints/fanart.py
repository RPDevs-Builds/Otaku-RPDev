from resources.lib.ui import client, control, database

api_info = database.get_info('Fanart-TV') or {}
api_key = api_info.get('api_key', '')
baseUrl = "https://webservice.fanart.tv/v3"
lang = ['en', 'ja', '']
headers = {'Api-Key': api_key}
language = ["ja", 'en'][control.getInt("titlelanguage")]


def _sanitize_art_url(url):
    """Escape raw spaces in Fanart.tv URLs so Kodi libcurl never fails with CURLE_URL_MALFORMAT."""
    return str(url).strip().replace(' ', '%20') if url else ''


def getArt(meta_ids, mtype, limit=None):
    art = {}
    if mid := meta_ids.get('themoviedb_id') if mtype == 'movies' else meta_ids.get('thetvdb_id'):
        response = client.get(f'{baseUrl}/{mtype}/{mid}', headers=headers)
        res = control.safe_json(response)
        if res:
            if mtype == 'movies':
                if res.get('moviebackground'):
                    items = [_sanitize_art_url(item.get('url')) for item in res['moviebackground'] if item.get('lang') in lang and item.get('url')]
                    art['fanart'] = items[:limit] if limit else items
                if res.get('moviethumb'):
                    items = [_sanitize_art_url(item.get('url')) for item in res['moviethumb'] if item.get('lang') in lang and item.get('url')]
                    art['thumb'] = items[:limit] if limit else items
            else:
                if res.get('showbackground'):
                    items = [_sanitize_art_url(item.get('url')) for item in res['showbackground'] if item.get('lang') in lang and item.get('url')]
                    art['fanart'] = items[:limit] if limit else items
                if res.get('tvthumb'):
                    items = [_sanitize_art_url(item.get('url')) for item in res['tvthumb'] if item.get('lang') in lang and item.get('url')]
                    art['thumb'] = items[:limit] if limit else items

            if res.get('clearart'):
                items = [_sanitize_art_url(item.get('url')) for item in res['clearart'] if item.get('lang') in lang and item.get('url')]
                art['clearart'] = items[:limit] if limit else items
            elif res.get('hdclearart'):
                items = [_sanitize_art_url(item.get('url')) for item in res['hdclearart'] if item.get('lang') in lang and item.get('url')]
                art['clearart'] = items[:limit] if limit else items
            elif res.get('hdmovieclearart'):
                items = [_sanitize_art_url(item.get('url')) for item in res['hdmovieclearart'] if item.get('lang') in lang and item.get('url')]
                art['clearart'] = items[:limit] if limit else items

            if res.get('clearlogo'):
                items = sorted([item for item in res['clearlogo'] if item.get('lang') in lang], key=lambda x: int(x.get('id', 0)))
                logos = []
                logo = control.safe_next(x['url'] for x in items if x['lang'] == language)
                if logo:
                    logos.append(_sanitize_art_url(logo))
                if not logos:
                    logo = control.safe_next(x['url'] for x in items)
                    if logo:
                        logos.append(_sanitize_art_url(logo))
                art['clearlogo'] = logos
            elif res.get('hdtvlogo'):
                items = sorted([item for item in res['hdtvlogo'] if item.get('lang') in lang], key=lambda x: int(x.get('id', 0)))
                logos = []
                logo = control.safe_next(x['url'] for x in items if x['lang'] == language)
                if logo:
                    logos.append(_sanitize_art_url(logo))
                if not logos:
                    logo = control.safe_next(x['url'] for x in items)
                    if logo:
                        logos.append(_sanitize_art_url(logo))
                art['clearlogo'] = logos
            elif res.get('hdmovielogo'):
                items = sorted([item for item in res['hdmovielogo'] if item.get('lang') in lang], key=lambda x: int(x.get('id', 0)))
                logos = []
                logo = control.safe_next(x['url'] for x in items if x['lang'] == language)
                if logo:
                    logos.append(_sanitize_art_url(logo))
                if not logos:
                    logo = control.safe_next(x['url'] for x in items)
                    if logo:
                        logos.append(_sanitize_art_url(logo))
                art['clearlogo'] = logos
    return art
