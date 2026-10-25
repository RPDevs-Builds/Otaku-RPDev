import random

from resources.lib.ui import database, control, client, utils, get_meta
from resources.lib.MalBrowser import MalBrowser
from resources.lib.ui.divide_flavors import div_flavor


class OtakuBrowser(MalBrowser):
    @staticmethod
    def _flatten_mal_data_items(mal_res):
        """Normalize direct items and nested/list 'entry' shapes (e.g. relations)."""
        mal_items_flat = []
        mal_ids = []
        if not mal_res:
            # Upstream API call failed (timeout, 5xx, rate limit) and returned
            # None instead of a response body - fail soft instead of crashing.
            control.log("MAL API request failed or returned no data", 'warning')
            return mal_ids, mal_items_flat
        for item in mal_res.get('data', []):
            if 'mal_id' in item:
                mal_ids.append(item['mal_id'])
                mal_items_flat.append(item)
            elif 'entry' in item:
                entries = item['entry']
                if isinstance(entries, list):
                    for entry in entries:
                        if 'mal_id' in entry:
                            mal_ids.append(entry['mal_id'])
                            merged = dict(entry)
                            if 'relation' in item:
                                merged['relation'] = item['relation']
                            mal_items_flat.append(merged)
                elif isinstance(entries, dict) and 'mal_id' in entries:
                    mal_ids.append(entries['mal_id'])
                    merged = dict(entries)
                    if 'relation' in item:
                        merged['relation'] = item['relation']
                    mal_items_flat.append(merged)
        return mal_ids, mal_items_flat

    def process_otaku_view(self, mal_res, base_plugin_url, page):
        mal_ids, mal_items_flat = self._flatten_mal_data_items(mal_res)

        anilist_res = self.get_anilist_base_res(mal_ids)
        get_meta.collect_meta(mal_items_flat)
        get_meta.collect_meta(anilist_res)
        anilist_by_mal_id = {item['idMal']: item for item in anilist_res if 'idMal' in item}

        def mapfunc(mal_item):
            mal_id = mal_item.get('mal_id')
            anilist_item = anilist_by_mal_id.get(mal_id)
            return self.base_otaku_view(mal_item, anilist_item, completed=self.open_completed())

        all_results = [mapfunc(mal_item) for mal_item in mal_items_flat]
        if mal_res and 'pagination' in mal_res:
            has_next = mal_res['pagination'].get('has_next_page', False)
            all_results += self.handle_paging(has_next, base_plugin_url, page)
        return all_results

    def process_mal_view(self, mal_res, base_plugin_url, page):
        return self.process_otaku_view(mal_res, base_plugin_url, page)

    def get_anime_data(self, mal_id):
        """
        Fetch full anime data from Jikan API by MAL ID.
        Returns the parsed JSON response or None on error.
        """
        mal_res = database.get(self.get_mal_base_res, 24, f"{self._BASE_URL}/anime/{mal_id}")
        data = mal_res.get('data', None)
        mal_id = data['mal_id']
        anilist_res = self.get_anilist_base_res([mal_id])
        get_meta.collect_meta([data])
        get_meta.collect_meta(anilist_res)
        return self.database_update_show(data, anilist_res)

    def get_recommendations(self, mal_id, page, prefix=None):
        recommendations = database.get(self.get_mal_base_res, 24, f"{self._BASE_URL}/anime/{mal_id}/recommendations")
        base_plugin_url = f"{prefix}?page=%d" if prefix else "recommendations?page=%d"
        return self.process_otaku_view(recommendations, base_plugin_url, page)

    def get_relations(self, mal_id, page=1, prefix=None):
        relations = database.get(self.get_mal_base_res, 24, f'{self._BASE_URL}/anime/{mal_id}/relations')
        for item in relations.get('data', []):
            if 'entry' in item and isinstance(item['entry'], list):
                item['entry'] = [entry for entry in item['entry'] if entry.get('type', '').lower() == 'anime']
        base_plugin_url = f"{prefix}?page=%d" if prefix else "relations?page=%d"
        return self.process_otaku_view(relations, base_plugin_url, page)

    @staticmethod
    def get_mal_base_res(url, params=None):
        for attempt in range(3):
            r = client.get(url, params=params)
            if r:
                return r.json()
            if attempt < 2:
                control.sleep(1000 * (attempt + 1))
        control.log(f'Jikan request failed: {url}', level='warning')

    get_base_res = get_mal_base_res

    @staticmethod
    def get_anilist_base_res(mal_ids, page=1, media_type="ANIME"):
        _ANILIST_BASE_URL = "https://graphql.anilist.co"

        query = '''
        query ($page: Int, $malIds: [Int], $type: MediaType) {
          Page(page: $page) {
            pageInfo {
              hasNextPage
              total
            }
            media(idMal_in: $malIds, type: $type) {
              id
              idMal
              title {
                romaji
                english
              }
              coverImage {
                extraLarge
              }
              bannerImage
              startDate {
                year
                month
                day
              }
              description
              synonyms
              format
              episodes
              status
              genres
              duration
              countryOfOrigin
              averageScore
              characters(
                page: 1
                sort: ROLE
                perPage: 10
              ) {
                edges {
                  node {
                    name {
                      userPreferred
                    }
                  }
                  voiceActors(language: JAPANESE) {
                    name {
                      userPreferred
                    }
                    image {
                      large
                    }
                  }
                }
              }
              studios {
                edges {
                  node {
                    name
                  }
                }
              }
              trailer {
                id
                site
              }
              stats {
                scoreDistribution {
                  score
                  amount
                }
              }
            }
          }
        }
        '''

        variables = {"page": 1, "malIds": mal_ids, "type": media_type}
        result = client.post(_ANILIST_BASE_URL, json_data={'query': query, 'variables': variables})
        if not result:
            return []
        results = result.json()
        # AniList often returns "data": null; .get("data", {}) still yields None when the key exists.
        page_data = ((results or {}).get('data') or {}).get('Page') or {}
        all_media = page_data.get('media') or []
        has_next = (page_data.get('pageInfo') or {}).get('hasNextPage', False)

        if not has_next:
            return all_media

        def fetch_page(page_num):
            try:
                vars = {"page": page_num, "malIds": mal_ids, "type": media_type}
                resp = client.post(_ANILIST_BASE_URL, json_data={'query': query, 'variables': vars})
                if resp:
                    resp_json = resp.json()
                    return (((resp_json or {}).get('data') or {}).get('Page') or {}).get('media') or []
                return []
            except Exception as e:
                control.log(f"AniList: Failed to fetch page {page_num}: {str(e)}")
                return []

        max_pages = min(5, len(mal_ids) // 50 + 2)

        page_numbers = list(range(2, max_pages + 1))
        all_page_results = utils.parallel_process(page_numbers, fetch_page)

        for page_media in all_page_results:
            if page_media:
                all_media.extend(page_media)
            else:
                break

        control.log(f"AniList: Fetched {len(all_media)} media items total")
        return all_media

    @div_flavor
    def base_otaku_view(self, mal_res, anilist_res=None, completed=None, mal_dub=None):
        """
        Combines MAL and AniList data for a single anime entry.
        Uses MAL as primary, fills missing fields from AniList if available.
        """
        if not completed:
            completed = {}

        mal_id = mal_res.get('mal_id') if mal_res else (anilist_res.get('idMal') if anilist_res else None)
        anilist_id = anilist_res.get('id') if anilist_res else None

        self.database_update_show(mal_res, anilist_res)

        show_meta = database.get_show_meta(mal_id)
        kodi_meta = database.loads(show_meta.get('art')) if show_meta else {}

        title = None
        if mal_res:
            title = mal_res.get('name') or mal_res.get(self.title_lang) or mal_res.get('title')
        if not title and anilist_res:
            title = anilist_res['title'].get(self.title_lang) or anilist_res['title'].get('romaji')
        if title is None:
            title = ''

        if mal_res and mal_res.get('relation'):
            title += ' [I]%s[/I]' % control.colorstr(mal_res['relation'], 'limegreen')
        elif anilist_res and anilist_res.get('relationType'):
            title += ' [I]%s[/I]' % control.colorstr(anilist_res['relationType'], 'limegreen')

        plot = mal_res.get('synopsis') if mal_res and mal_res.get('synopsis') else None
        if not plot and anilist_res and anilist_res.get('description'):
            desc = anilist_res['description']
            desc = desc.replace('<i>', '[I]').replace('</i>', '[/I]')
            desc = desc.replace('<b>', '[B]').replace('</b>', '[/B]')
            desc = desc.replace('<br>', '[CR]')
            desc = desc.replace('\n', '')
            plot = desc

        genre = [x['name'] for x in mal_res.get('genres', [])] if mal_res else None
        if not genre and anilist_res:
            genre = anilist_res.get('genres')

        studio = [x['name'] for x in mal_res.get('studios', [])] if mal_res else None
        if not studio and anilist_res:
            edges = (anilist_res.get('studios') or {}).get('edges') or []
            main_studios = [x['node'].get('name') for x in edges if x and x.get('isMain') and x.get('node')]
            studio = main_studios if main_studios else [x['node'].get('name') for x in edges if x and x.get('node')]

        status = mal_res.get('status') if mal_res else None
        if not status and anilist_res:
            status = anilist_res.get('status')

        duration = self.duration_to_seconds(mal_res.get('duration')) if mal_res and mal_res.get('duration') else None
        if not duration and anilist_res and anilist_res.get('duration'):
            duration = anilist_res['duration'] * 60

        country = None
        if anilist_res:
            country = [anilist_res.get('countryOfOrigin', '')]

        rating = mal_res.get('rating') if mal_res else None
        info_rating = None
        if mal_res and isinstance(mal_res.get('score'), float):
            info_rating = {'score': mal_res['score']}
            if isinstance(mal_res.get('scored_by'), int):
                info_rating['votes'] = mal_res['scored_by']
        elif anilist_res and anilist_res.get('averageScore'):
            info_rating = {'score': anilist_res.get('averageScore') / 10.0}
            if anilist_res.get('stats') and anilist_res['stats'].get('scoreDistribution'):
                total_votes = sum([score['amount'] for score in anilist_res['stats']['scoreDistribution']])
                info_rating['votes'] = total_votes

        trailer = None
        if mal_res and mal_res.get('trailer') and mal_res['trailer'].get('youtube_id'):
            trailer = f"plugin://plugin.video.youtube/play/?video_id={mal_res['trailer']['youtube_id']}"
        elif anilist_res and anilist_res.get('trailer'):
            try:
                if anilist_res['trailer']['site'] == 'youtube':
                    trailer = f"plugin://plugin.video.youtube/play/?video_id={anilist_res['trailer']['id']}"
                else:
                    trailer = f"plugin://plugin.video.dailymotion_com/?url={anilist_res['trailer']['id']}&mode=playVideo"
            except (KeyError, TypeError):
                pass

        playcount = None
        if completed and completed.get(str(mal_id)):
            playcount = 1

        premiered = None
        year = None
        if mal_res and mal_res.get('aired') and mal_res['aired'].get('from'):
            start_date = mal_res['aired']['from']
            premiered = start_date[:10]
            year = mal_res.get('year', int(start_date[:4]))
        elif anilist_res and anilist_res.get('startDate'):
            start_date = anilist_res.get('startDate')
            year = start_date.get('year')
            month = start_date.get('month')
            day = start_date.get('day')
            if None not in (year, month, day):
                premiered = '{}-{:02}-{:02}'.format(year, month, day)
            else:
                premiered = ''
            year = start_date['year']

        cast = None
        if anilist_res and anilist_res.get('characters'):
            try:
                cast = []
                for i, x in enumerate(anilist_res['characters']['edges']):
                    role = x['node']['name']['userPreferred']
                    actor = x['voiceActors'][0]['name']['userPreferred']
                    actor_hs = x['voiceActors'][0]['image']['large']
                    cast.append({'name': actor, 'role': role, 'thumbnail': actor_hs, 'index': i})
            except (IndexError, KeyError, TypeError):
                pass

        unique_ids = {'mal_id': str(mal_id)}
        if anilist_id:
            unique_ids['anilist_id'] = str(anilist_id)
            unique_ids.update(database.get_unique_ids(anilist_id, 'anilist_id'))
        unique_ids.update(database.get_unique_ids(mal_id, 'mal_id'))

        info = {
            'UniqueIDs': unique_ids,
            'title': title,
            'plot': plot,
            'mpaa': rating,
            'duration': duration,
            'genre': genre,
            'studio': studio,
            'status': status,
            'mediatype': 'tvshow',
            'country': country,
        }
        if info_rating:
            info['rating'] = info_rating
        if playcount:
            info['playcount'] = playcount
        if premiered:
            info['premiered'] = premiered
        if year:
            info['year'] = year
        if cast:
            info['cast'] = cast
        if trailer:
            info['trailer'] = trailer

        dub = True if mal_dub and mal_dub.get(str(mal_id)) else False

        image = None
        poster = None
        fanart = None

        if mal_res and mal_res.get('images'):
            image = mal_res['images']['webp'].get('large_image_url')
            poster = image
            fanart = kodi_meta['fanart'] if kodi_meta.get('fanart') else image
        if not image and anilist_res and anilist_res.get('coverImage'):
            image = anilist_res['coverImage'].get('extraLarge')
        if not poster and anilist_res and anilist_res.get('coverImage'):
            poster = anilist_res['coverImage'].get('extraLarge')
        if not fanart and anilist_res and anilist_res.get('coverImage'):
            fanart = anilist_res['coverImage'].get('extraLarge')

        base = {
            "name": title,
            "url": f'animes/{mal_id}/',
            "image": image,
            "poster": poster,
            'fanart': fanart,
            "info": info
        }

        if kodi_meta.get('banner'):
            base['banner'] = kodi_meta['banner']
        if kodi_meta.get('thumb'):
            thumb = kodi_meta['thumb']
            base['landscape'] = random.choice(thumb) if isinstance(thumb, list) else thumb
        if kodi_meta.get('clearart'):
            clearart = kodi_meta['clearart']
            base['clearart'] = random.choice(clearart) if isinstance(clearart, list) else clearart
        if kodi_meta.get('clearlogo'):
            clearlogo = kodi_meta['clearlogo']
            base['clearlogo'] = random.choice(clearlogo) if isinstance(clearlogo, list) else clearlogo

        episodes = mal_res.get('episodes') or (anilist_res.get('episodes') if anilist_res else None)

        if episodes == 1:
            base['url'] = f'play_movie/{mal_id}/'
            base['info']['mediatype'] = 'movie'
            return utils.parse_view(base, False, True, dub)
        return utils.parse_view(base, True, False, dub)

    def base_mal_view(self, *args, **kwargs):
        return self.base_otaku_view(*args, **kwargs)

    def database_update_show(self, mal_res=None, anilist_res=None):
        """
        Combines MAL and AniList data for database update.
        Uses MAL as primary, fills missing fields from AniList if available.
        """
        mal_id = None
        if mal_res and 'mal_id' in mal_res:
            mal_id = mal_res['mal_id']
        elif anilist_res and 'idMal' in anilist_res:
            mal_id = anilist_res['idMal']
        if not mal_id:
            return

        title_userPreferred = None
        name = None
        ename = None
        titles = None
        if mal_res:
            title_userPreferred = mal_res.get(self.title_lang) or mal_res.get('title')
            name = mal_res.get('title')
            ename = mal_res.get('title_english')
        if (not title_userPreferred or not name) and anilist_res:
            title_userPreferred = anilist_res['title'].get(self.title_lang) or anilist_res['title'].get('romaji')
            name = anilist_res['title'].get('romaji')
            ename = anilist_res['title'].get('english')
        if name and ename:
            titles = f"({name})|({ename})"
        elif name:
            titles = f"({name})"
        elif ename:
            titles = f"({ename})"
        else:
            titles = ''

        start_date = None
        if mal_res and mal_res.get('aired') and mal_res['aired'].get('from'):
            start_date = mal_res['aired']['from']
        elif anilist_res and anilist_res.get('startDate'):
            sd = anilist_res['startDate']
            year = sd.get('year')
            month = sd.get('month')
            day = sd.get('day')
            if None not in (year, month, day):
                start_date = '{}-{:02}-{:02}'.format(year, month, day)
            else:
                start_date = ''

        episodes = mal_res.get('episodes') if mal_res and 'episodes' in mal_res else (anilist_res.get('episodes') if anilist_res and 'episodes' in anilist_res else None)

        poster = None
        if mal_res and mal_res.get('images') and mal_res['images'].get('webp'):
            poster = mal_res['images']['webp'].get('large_image_url')
        if not poster and anilist_res and anilist_res.get('coverImage'):
            poster = anilist_res['coverImage'].get('extraLarge')

        status = mal_res.get('status') if mal_res and 'status' in mal_res else (anilist_res.get('status') if anilist_res and 'status' in anilist_res else None)

        format_ = mal_res.get('type') if mal_res and 'type' in mal_res else (anilist_res.get('format') if anilist_res and 'format' in anilist_res else '')

        plot = mal_res.get('synopsis') if mal_res and 'synopsis' in mal_res else None
        if not plot and anilist_res and anilist_res.get('description'):
            desc = anilist_res['description']
            desc = desc.replace('<i>', '[I]').replace('</i>', '[/I]')
            desc = desc.replace('<b>', '[B]').replace('</b>', '[/B]')
            desc = desc.replace('<br>', '[CR]')
            desc = desc.replace('\n', '')
            plot = desc

        duration = self.duration_to_seconds(mal_res.get('duration')) if mal_res and 'duration' in mal_res else None
        if not duration and anilist_res and 'duration' in anilist_res and anilist_res['duration'] is not None:
            duration = anilist_res['duration'] * 60

        genre = [x['name'] for x in mal_res.get('genres', [])] if mal_res else None
        if not genre and anilist_res:
            genre = anilist_res.get('genres')

        studio = [x['name'] for x in mal_res.get('studios', [])] if mal_res else None
        if not studio and anilist_res and anilist_res.get('studios'):
            studio = [x['node'].get('name') for x in anilist_res['studios']['edges']]

        mpaa = mal_res.get('rating') if mal_res and 'rating' in mal_res else None
        country = [anilist_res.get('countryOfOrigin', '')] if anilist_res and 'countryOfOrigin' in anilist_res else None

        kodi_meta = {
            'name': name,
            'ename': ename,
            'title_userPreferred': title_userPreferred,
            'start_date': start_date,
            'query': titles,
            'episodes': episodes,
            'poster': poster,
            'status': status,
            'format': format_,
            'plot': plot,
            'duration': duration,
            'genre': genre,
            'studio': studio,
            'mpaa': mpaa,
            'country': country,
        }

        try:
            if mal_res and mal_res.get('aired') and mal_res['aired'].get('from'):
                start_date = mal_res['aired']['from']
                kodi_meta['premiered'] = start_date[:10]
                kodi_meta['year'] = mal_res.get('year', int(start_date[:4]))
            elif anilist_res and anilist_res.get('startDate'):
                sd = anilist_res['startDate']
                kodi_meta['premiered'] = '{}-{:02}-{:02}'.format(sd['year'], sd['month'], sd['day'])
                kodi_meta['year'] = sd['year']
        except Exception:
            pass

        try:
            if anilist_res and anilist_res.get('characters'):
                cast = []
                for i, x in enumerate(anilist_res['characters']['edges']):
                    role = x['node']['name']['userPreferred']
                    actor = x['voiceActors'][0]['name']['userPreferred']
                    actor_hs = x['voiceActors'][0]['image']['large']
                    cast.append({'name': actor, 'role': role, 'thumbnail': actor_hs, 'index': i})
                kodi_meta['cast'] = cast
        except Exception:
            pass

        try:
            if mal_res and isinstance(mal_res.get('score'), float):
                kodi_meta['rating'] = {'score': mal_res['score']}
                if isinstance(mal_res.get('scored_by'), int):
                    kodi_meta['rating']['votes'] = mal_res['scored_by']
            elif anilist_res and anilist_res.get('averageScore'):
                kodi_meta['rating'] = {'score': anilist_res.get('averageScore') / 10.0}
                if anilist_res.get('stats') and anilist_res['stats'].get('scoreDistribution'):
                    total_votes = sum([score['amount'] for score in anilist_res['stats']['scoreDistribution']])
                    kodi_meta['rating']['votes'] = total_votes
        except Exception:
            pass

        try:
            if mal_res and mal_res.get('trailer') and mal_res['trailer'].get('youtube_id'):
                kodi_meta['trailer'] = f"plugin://plugin.video.youtube/play/?video_id={mal_res['trailer']['youtube_id']}"
            elif anilist_res and anilist_res.get('trailer'):
                if anilist_res['trailer']['site'] == 'youtube':
                    kodi_meta['trailer'] = f"plugin://plugin.video.youtube/play/?video_id={anilist_res['trailer']['id']}"
                else:
                    kodi_meta['trailer'] = f"plugin://plugin.video.dailymotion_com/?url={anilist_res['trailer']['id']}&mode=playVideo"
        except Exception:
            pass

        database.update_show(mal_id, database.dumps(kodi_meta))
