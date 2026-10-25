import datetime

from functools import partial
from resources.lib.ui import utils, database, client, control
from resources.lib import indexers
from resources.lib.indexers.otaku import OtakuAPI


class Otaku_Next_Up_API(OtakuAPI):
    def get_episode_meta(self, mal_id):
        url = f'{self.baseUrl}/anime/{mal_id}/episodes'
        response = client.get(url)
        if not response:
            return []

        res = response.json()
        res_data = res['data']

        # If only one page, return immediately
        if not res['pagination']['has_next_page']:
            return res_data

        # Paging for additional sources removed; only first page is returned.
        return res_data

    def parse_episode_view(self, res, mal_id, season, poster, fanart, clearart, clearlogo, eps_watched, update_time, tvshowtitle, dub_data, filler_data, episodes=None, meta_cache=None):
        episode_num = str(res.get('episode', res.get('mal_id')))
        # Use cached meta lists
        simkl_meta_list = meta_cache.get('simkl') if meta_cache else None
        anizip_meta_list = meta_cache.get('anizip') if meta_cache else None
        kitsu_meta_list = meta_cache.get('kitsu') if meta_cache else None

        # Find episode meta for this episode
        simkl_meta = None
        if simkl_meta_list:
            for ep in simkl_meta_list:
                if str(ep.get('episode')) == episode_num:
                    simkl_meta = ep
                    break
        anizip_meta = None
        if anizip_meta_list:
            for ep in anizip_meta_list:
                if str(ep.get('episode')) == episode_num:
                    anizip_meta = ep
                    break
        kitsu_meta = None
        if kitsu_meta_list:
            for ep in kitsu_meta_list:
                if str(ep.get('attributes', {}).get('number')) == episode_num:
                    kitsu_meta = ep
                    break

        kodi_meta = database.loads(database.get_show(mal_id)['kodi_meta'])
        episode = res.get('mal_id', res.get('episode'))
        url = f"{mal_id}/{episode}"

        # Check if should hide unaired episodes - use fallback logic across sources
        aired_date = (
            (simkl_meta.get('date') if simkl_meta else None)
            or (anizip_meta.get('airDate') if anizip_meta else None)
            or (kitsu_meta['attributes'].get('airdate') if kitsu_meta and kitsu_meta.get('attributes') else None)
            or ''
        )
        if indexers.should_hide_unaired_episode(aired_date):
            return None

        # Fallback logic for title
        title = (
            (simkl_meta.get('title') if simkl_meta else None)
            or (anizip_meta['title']['en'] if anizip_meta and anizip_meta.get('title') and 'en' in anizip_meta['title'] else None)
            or (kitsu_meta['attributes'].get('canonicalTitle') if kitsu_meta and kitsu_meta.get('attributes') and kitsu_meta['attributes'].get('canonicalTitle') else None)
            or res.get('title')
            or res.get('episode')
            or f"Episode {episode}"
        )
        # Fallback logic for image
        image = (
            (self.simklImagePath % simkl_meta['img'] if simkl_meta and simkl_meta.get('img') else None)
            or (anizip_meta['image'] if anizip_meta and anizip_meta.get('image') else None)
            or (kitsu_meta['attributes']['thumbnail']['original'] if kitsu_meta and kitsu_meta.get('attributes') and kitsu_meta['attributes'].get('thumbnail') and kitsu_meta['attributes']['thumbnail'].get('original') else None)
            or poster
        )
        # Fallback logic for plot
        plot = (
            (simkl_meta.get('description') if simkl_meta else None)
            or (anizip_meta.get('overview') if anizip_meta else None)
            or (kitsu_meta['attributes'].get('synopsis') if kitsu_meta and kitsu_meta.get('attributes') and kitsu_meta['attributes'].get('synopsis') else None)
            or 'No plot available'
        )
        info = {
            'UniqueIDs': {
                'mal_id': str(mal_id),
                **database.get_unique_ids(mal_id, 'mal_id')
            },
            'title': title,
            'season': season,
            'episode': episode,
            'plot': plot,
            'tvshowtitle': tvshowtitle,
            'mediatype': 'episode',
            'status': kodi_meta.get('status'),
            'genre': kodi_meta.get('genre'),
            'country': kodi_meta.get('country'),
            'cast': kodi_meta.get('cast'),
            'studio': kodi_meta.get('studio'),
            'mpaa': kodi_meta.get('mpaa'),
        }

        if eps_watched and int(eps_watched) >= episode:
            info['playcount'] = 1

        # Fallback logic for rating
        rating = control.safe_call(float, simkl_meta.get('rating')) if simkl_meta and simkl_meta.get('rating') else None
        if rating is None and anizip_meta and anizip_meta.get('rating'):
            rating = control.safe_call(float, anizip_meta['rating'])
        if rating is None and kitsu_meta and kitsu_meta.get('attributes') and kitsu_meta['attributes'].get('rating'):
            rating = control.safe_call(float, kitsu_meta['attributes']['rating'])
        if rating is not None:
            info['rating'] = {'score': rating}

        # Fallback logic for aired date
        aired = control.safe_call(lambda: simkl_meta.get('date')[:10]) if simkl_meta and simkl_meta.get('date') else None
        if not aired and anizip_meta and anizip_meta.get('airDate'):
            aired = anizip_meta['airDate'][:10]
        if not aired and kitsu_meta and kitsu_meta.get('attributes') and kitsu_meta['attributes'].get('airdate'):
            aired = kitsu_meta['attributes']['airdate']
        if aired:
            info['aired'] = aired

        filler = control.safe_call(lambda: filler_data[episode - 1], default='')

        parsed = indexers.update_database(mal_id, update_time, res, url, image, info, season, episode, episodes, title, fanart, poster, clearart, clearlogo, dub_data, filler)
        return parsed

    def process_episode_view(self, mal_id, poster, fanart, clearart, clearlogo, eps_watched, tvshowtitle, dub_data, filler_data):
        update_time = datetime.date.today().isoformat()
        result = self.get_anime_info(mal_id)
        if not result:
            return []

        title_list = [name['title'] for name in result['titles']]
        season = utils.get_season(title_list, mal_id)

        # Fetch all episode meta from all providers in parallel using ThreadPoolExecutor
        import concurrent.futures
        meta_cache = {}

        def fetch_simkl():
            try:
                simkl_raw = self.get_simkl_episode_meta(mal_id)
                filtered = [x for x in simkl_raw if x.get('type') == 'episode'] if isinstance(simkl_raw, list) else []
                return ('simkl', filtered)
            except Exception as e:
                control.log(f"SIMKL episode meta fetch failed: {str(e)}")
                return ('simkl', [])

        def fetch_anizip():
            try:
                return ('anizip', self.get_anizip_episode_meta(mal_id))
            except Exception as e:
                control.log(f"AniZip episode meta fetch failed: {str(e)}")
                return ('anizip', [])

        def fetch_kitsu():
            try:
                return ('kitsu', self.get_kitsu_episode_meta(mal_id))
            except Exception as e:
                control.log(f"Kitsu episode meta fetch failed: {str(e)}")
                return ('kitsu', [])

        # Fetch from all providers concurrently
        control.log(f"Fetching episode metadata from 3 providers in parallel for MAL ID: {mal_id}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=control.max_threads) as executor:
            futures = [
                executor.submit(fetch_simkl),
                executor.submit(fetch_anizip),
                executor.submit(fetch_kitsu)
            ]

            # Wait for all to complete and populate meta_cache
            for future in concurrent.futures.as_completed(futures):
                provider, data = future.result()
                meta_cache[provider] = data

        control.log(f"Episode metadata fetched - SIMKL: {len(meta_cache.get('simkl', []))}, AniZip: {len(meta_cache.get('anizip', []))}, Kitsu: {len(meta_cache.get('kitsu', []))}")

        # Use Simkl as base, fallback to AniZip, then Kitsu
        base_ep_list = meta_cache.get('simkl') or meta_cache.get('anizip') or meta_cache.get('kitsu', [])

        if not base_ep_list:
            control.log(f"No episode metadata found for MAL ID: {mal_id}")
            return []

        # Parse episodes in parallel for faster processing
        mapfunc = partial(self.parse_episode_view, mal_id=mal_id, season=season, poster=poster, fanart=fanart, clearart=clearart, clearlogo=clearlogo, eps_watched=eps_watched, update_time=update_time, tvshowtitle=tvshowtitle, dub_data=dub_data, filler_data=filler_data, meta_cache=meta_cache)
        all_results = utils.parallel_process(base_ep_list, mapfunc)
        all_results = [r for r in all_results if r is not None]
        all_results = sorted(all_results, key=lambda x: x['info']['episode'])

        if control.getBool('override.meta.api') and control.getBool('override.meta.notify'):
            control.notify("Otaku", f'{tvshowtitle} Added to Database', icon=poster)
        return all_results
