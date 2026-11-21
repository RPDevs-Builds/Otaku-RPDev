
from resources.lib.ui import control, database, source_utils

# Lazy browser initialization for improved startup performance
_BROWSER_INSTANCE = None


def _get_browser():
    """Lazy-load browser instance on first access"""
    global _BROWSER_INSTANCE
    if _BROWSER_INSTANCE is None:
        if control.getStr('browser.api') == 'otaku':
            from resources.lib.OtakuBrowser import OtakuBrowser
            _BROWSER_INSTANCE = OtakuBrowser()
        elif control.getStr('browser.api') == 'mal':
            from resources.lib.MalBrowser import MalBrowser
            _BROWSER_INSTANCE = MalBrowser()
        else:
            from resources.lib.AniListBrowser import AniListBrowser
            _BROWSER_INSTANCE = AniListBrowser()
    return _BROWSER_INSTANCE


# Backwards compatibility: BROWSER property that lazily initializes
class _BrowserProxy:
    """Proxy that provides attribute access to the lazily-loaded browser"""
    def __getattribute__(self, name):
        return getattr(_get_browser(), name)


BROWSER = _BrowserProxy()


def get_anime_init(mal_id):
    # Lazy import indexers - only import what's actually needed
    show_meta = database.get_show_meta(mal_id)
    show = database.get_show(mal_id)

    # Ensure both shows and shows_meta tables are populated
    # shows_meta can exist from collect_meta batch runs without the shows entry
    if not show_meta or not show:
        BROWSER.get_anime(mal_id)
        show_meta = database.get_show_meta(mal_id)
        show = database.get_show(mal_id)
        if not show_meta or not show:
            return [], 'episodes'

    if control.getBool('override.meta.api'):
        # Import only the specified indexer when override is enabled
        meta_api = control.getSetting('meta.api')
        if meta_api == 'simkl':
            from resources.lib.indexers import simkl
            data = simkl.SIMKLAPI().get_episodes(mal_id, show_meta)
        elif meta_api == 'anizip':
            from resources.lib.indexers import anizip
            data = anizip.ANIZIPAPI().get_episodes(mal_id, show_meta)
        elif meta_api == 'jikanmoe':
            from resources.lib.indexers import jikanmoe
            data = jikanmoe.JikanAPI().get_episodes(mal_id, show_meta)
        elif meta_api == 'anidb':
            from resources.lib.indexers import anidb
            data = anidb.ANIDBAPI().get_episodes(mal_id, show_meta)
        elif meta_api == 'kitsu':
            from resources.lib.indexers import kitsu
            data = kitsu.KitsuAPI().get_episodes(mal_id, show_meta)
        elif meta_api == 'otaku':
            from resources.lib.indexers import otaku
            data = otaku.OtakuAPI().get_episodes(mal_id, show_meta)
        else:
            data = None
    else:
        # Fallback chain - import indexers one by one as needed
        from resources.lib.indexers import simkl
        data = simkl.SIMKLAPI().get_episodes(mal_id, show_meta)
        if not data:
            from resources.lib.indexers import anizip
            data = anizip.ANIZIPAPI().get_episodes(mal_id, show_meta)
        if not data:
            from resources.lib.indexers import jikanmoe
            data = jikanmoe.JikanAPI().get_episodes(mal_id, show_meta)
        if not data:
            from resources.lib.indexers import anidb
            data = anidb.ANIDBAPI().get_episodes(mal_id, show_meta)
        if not data:
            from resources.lib.indexers import kitsu
            data = kitsu.KitsuAPI().get_episodes(mal_id, show_meta)
        if not data:
            data = []
    return data, 'episodes'


def get_sources(mal_id, episode, media_type, rescrape=False, source_select=False, silent=False):
    from resources.lib import pages
    if not (show := database.get_show(mal_id)):
        show = BROWSER.get_anime(mal_id)
    if not show:
        return []
    kodi_meta = database.loads(show['kodi_meta'])

    # Pre-fetch season and part once so scrapers don't each do redundant DB lookups
    episode_data = database.get_episode(mal_id)
    season = episode_data.get('season') if episode_data else None

    hints = {}
    if media_type != 'movie':
        from resources.lib.ui import utils
        season, hints = utils.get_source_context(mal_id, kodi_meta, season, episode)

    # Fast-path: Check for cached season pack continuity
    if media_type != 'movie' and not rescrape and not source_select and control.getBool('smartplay.reuse_season_pack', default=True):
        cached_pack = database.get_season_pack(mal_id, season)
        if cached_pack:
            total_eps = kodi_meta.get('episodes')
            if source_utils.season_pack_covers_episode(cached_pack, episode, total_eps):
                control.log(f"MetaBrowser: Reusing cached season pack for {mal_id} ep {episode}: {cached_pack.get('release_title')}", level='info')
                pack_candidate = dict(cached_pack)
                pack_candidate['episode_re'] = str(episode)
                pack_candidate['_cached_season_pack'] = True
                pack_candidate.pop('filename', None)
                return [pack_candidate]
            else:
                control.log(f"MetaBrowser: Cached season pack does not cover ep {episode}, clearing pack cache and rescanning", level='info')
                database.clear_season_pack(mal_id, season)

    # Fast-path 2: Check for pre-scraped / cached episode sources
    if not rescrape:
        cached_sources = database.get_episode_sources(mal_id, episode)
        if cached_sources:
            src_filter = control.getInt('general.source')
            cached_sources = source_utils.filter_sources_by_audio(cached_sources, src_filter)
            if cached_sources:
                control.log(f"MetaBrowser: Reusing pre-scraped sources for {mal_id} ep {episode} ({len(cached_sources)} sources)", level='info')
                return cached_sources
            control.log(f"MetaBrowser: Cached sources did not match language filter {src_filter}, re-scraping", level='info')
            database.clear_episode_sources(mal_id, episode)
    else:
        database.clear_episode_sources(mal_id, episode)

    part = None
    mal_mapping = database.get_mappings(mal_id, 'mal_id')
    if mal_mapping and 'thetvdb_part' in mal_mapping:
        part = mal_mapping['thetvdb_part']

    # NF-06: Apply per-series episode_offset strictly to scraper queries (never alters canonical watchlist scrobble episode)
    scrape_episode = episode
    series_override = database.get_series_override(mal_id)
    if isinstance(series_override, dict) and series_override.get('episode_offset'):
        try:
            ep_off = int(series_override.get('episode_offset') or 0)
            if ep_off != 0 and str(episode).isdigit():
                scrape_episode = str(max(1, int(episode) + ep_off))
                control.log(f"MetaBrowser: Applied per-series episode_offset={ep_off:+d} for MAL {mal_id} (canonical ep {episode} -> scrape ep {scrape_episode})", level='info')
        except (ValueError, TypeError):
            scrape_episode = episode

    actionArgs = {
        'query': kodi_meta.get('query', kodi_meta.get('name', '')),
        'mal_id': mal_id,
        'episode': scrape_episode,
        'canonical_episode': episode,
        'episodes': kodi_meta.get('episodes'),
        'status': kodi_meta.get('status'),
        'duration': kodi_meta.get('duration'),
        'media_type': media_type,
        'rescrape': rescrape,
        'source_select': source_select,
        'silent': silent,
        'season': season,
        'part': part,
        'hints': hints,
    }

    sources = pages.getSourcesHelper(actionArgs)
    if sources:
        database.set_episode_sources(mal_id, episode, sources)
    return sources


# Lazy-loaded Next Up API instance
_NEXT_UP_API = None


def _get_next_up_api():
    """Lazy-load Next Up API instance"""
    global _NEXT_UP_API
    if _NEXT_UP_API is None:
        from resources.lib.indexers import otaku_next_up
        _NEXT_UP_API = otaku_next_up.Otaku_Next_Up_API()
    return _NEXT_UP_API


def get_next_up_meta(mal_id, episode_num):
    """
    Fetch episode metadata for Next Up feature.
    Used by all watchlist flavors for consistent episode metadata.

    Args:
        mal_id: MyAnimeList ID
        episode_num: Episode number to fetch metadata for

    Returns:
        dict with: title, image, plot, aired, rating
    """
    next_up_api = _get_next_up_api()

    episode_meta = {
        'title': None,
        'image': None,
        'plot': None,
        'aired': None,
        'rating': None
    }

    # First try database cache
    episodes = database.get_episode_list(mal_id)
    if episodes:
        try:
            # Episodes are 1-indexed, list is 0-indexed
            ep_data = episodes[episode_num - 1] if episode_num <= len(episodes) else None
            if ep_data:
                kodi_meta = database.loads(ep_data.get('kodi_meta', b''))
                if kodi_meta:
                    info = kodi_meta.get('info', {})
                    image = kodi_meta.get('image', {})
                    episode_meta['title'] = info.get('title')
                    episode_meta['plot'] = info.get('plot')
                    episode_meta['aired'] = info.get('aired')
                    episode_meta['image'] = image.get('thumb') or image.get('icon')
                    if info.get('rating'):
                        episode_meta['rating'] = info['rating'].get('score')

                    # If we have good data, return early
                    if episode_meta['title'] and episode_meta['title'] != f'Episode {episode_num}':
                        return episode_meta
        except (IndexError, TypeError, KeyError) as e:
            control.log(f"Episode cache lookup failed for {mal_id} ep {episode_num}: {str(e)}")

    # Fetch from APIs if cache miss or incomplete
    # Track whether any provider had episodes for this show (to detect unaired episodes)
    provider_max_episode = 0
    episode_found = False

    try:
        # Try Simkl first (best quality metadata)
        simkl_eps = database.get(next_up_api.get_simkl_episode_meta, 6, mal_id)
        if simkl_eps:
            for ep in simkl_eps:
                if ep.get('type') == 'episode':
                    ep_num = ep.get('episode', 0)
                    if isinstance(ep_num, int) and ep_num > provider_max_episode:
                        provider_max_episode = ep_num
                    if str(ep_num) == str(episode_num):
                        episode_found = True
                        if not episode_meta['title']:
                            episode_meta['title'] = ep.get('title')
                        if not episode_meta['plot']:
                            episode_meta['plot'] = ep.get('description')
                        if not episode_meta['aired']:
                            episode_meta['aired'] = ep.get('date', '')[:10] if ep.get('date') else None
                        if ep.get('img') and not episode_meta['image']:
                            episode_meta['image'] = next_up_api.simklImagePath % ep['img']
                        break
    except Exception as e:
        control.log(f"Simkl episode meta fetch failed: {str(e)}")

    # Try AniZip as fallback
    if not episode_meta['title']:
        try:
            anizip_eps = database.get(next_up_api.get_anizip_episode_meta, 6, mal_id)
            if anizip_eps:
                for ep in anizip_eps:
                    ep_num = ep.get('episode', 0)
                    try:
                        ep_num_int = int(ep_num)
                        if ep_num_int > provider_max_episode:
                            provider_max_episode = ep_num_int
                    except (ValueError, TypeError):
                        pass
                    if str(ep_num) == str(episode_num):
                        episode_found = True
                        if not episode_meta['title'] and ep.get('title'):
                            episode_meta['title'] = ep['title'].get('en') or ep['title'].get('x-jat')
                        if not episode_meta['plot']:
                            episode_meta['plot'] = ep.get('overview')
                        if not episode_meta['aired']:
                            episode_meta['aired'] = ep.get('airDate', '')[:10] if ep.get('airDate') else None
                        if not episode_meta['image']:
                            episode_meta['image'] = ep.get('image')
                        break
        except Exception as e:
            control.log(f"AniZip episode meta fetch failed: {str(e)}")

    # If the requested episode wasn't found in any provider but the provider
    # had other episodes for this show, the episode likely hasn't aired yet.
    # Mark it so the caller's unaired check can filter it out.
    if not episode_found and provider_max_episode > 0 and episode_num > provider_max_episode:
        episode_meta['not_yet_aired'] = True

    # Final fallback
    if not episode_meta['title']:
        episode_meta['title'] = f'Episode {episode_num}'

    return episode_meta
