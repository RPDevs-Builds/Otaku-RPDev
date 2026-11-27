import sys
import xbmc
import xbmcgui
from urllib import parse


def get_video_info(li: xbmcgui.ListItem) -> dict:
    params = {}
    vinfo: xbmc.InfoTagVideo = li.getVideoInfoTag()
    # Meta Data
    if title := vinfo.getTitle():
        params['title'] = title
    if mediatype := vinfo.getMediaType():
        params['mediatype'] = mediatype
    if tvshow_title := vinfo.getTVShowTitle():
        params['tvshowtitle'] = tvshow_title
    if plot := vinfo.getPlot():
        params['plot'] = plot
    if year := vinfo.getYear():
        params['year'] = str(year)
    if premiered := (vinfo.getPremieredAsW3C() if hasattr(vinfo, 'getPremieredAsW3C') else (vinfo.getPremiered() if hasattr(vinfo, 'getPremiered') else '')):
        params['premiered'] = premiered
    if season := vinfo.getSeason():
        params['season'] = str(season)
    if episode := vinfo.getEpisode():
        params['episode'] = str(episode)
    if aired := (vinfo.getFirstAiredAsW3C() if hasattr(vinfo, 'getFirstAiredAsW3C') else (vinfo.getFirstAired() if hasattr(vinfo, 'getFirstAired') else '')):
        params['aired'] = aired
    if rating := vinfo.getRating():
        params['rating'] = {'score': rating, 'votes': 0}  # Assuming votes are not available
    if resume := (vinfo.getResumeTime() if hasattr(vinfo, 'getResumeTime') else (vinfo.getResumePoint() if hasattr(vinfo, 'getResumePoint') else 0)):
        params['resume'] = str(resume)

    # Artwork
    if poster := li.getArt('poster'):
        params['poster'] = poster
    if tvshowposter := li.getArt('tvshow.poster'):
        params['tvshow.poster'] = tvshowposter
    if icon := li.getArt('icon'):
        params['icon'] = icon
    if thumb := li.getArt('thumb'):
        params['thumb'] = thumb
    if fanart := li.getArt('fanart'):
        params['fanart'] = fanart
    if landscape := li.getArt('landscape'):
        params['landscape'] = landscape
    if banner := li.getArt('banner'):
        params['banner'] = banner
    if clearart := li.getArt('clearart'):
        params['clearart'] = clearart
    if clearlogo := li.getArt('clearlogo'):
        params['clearlogo'] = clearlogo

    # NF-02: Widget & UniqueID resolution
    uids = vinfo.getUniqueIDs() if hasattr(vinfo, 'getUniqueIDs') else {}
    mal_id = (
        (uids.get('mal_id') or uids.get('mal') if isinstance(uids, dict) else '')
        or (li.getProperty('mal_id') if hasattr(li, 'getProperty') else '')
        or (li.getProperty('otaku.mal_id') if hasattr(li, 'getProperty') else '')
    )
    if mal_id:
        params['mal_id'] = str(mal_id)

    return params


def _resolve_widget_mal_id(item: xbmcgui.ListItem, path: str) -> str:
    """Resolve mal_id from ListItem UniqueIDs, properties, or URL query parameters."""
    try:
        vinfo = item.getVideoInfoTag()
        if hasattr(vinfo, 'getUniqueIDs'):
            uids = vinfo.getUniqueIDs() or {}
            mal_val = uids.get('mal_id') or uids.get('mal')
            if mal_val:
                return str(mal_val)
        if hasattr(vinfo, 'getUniqueID'):
            for uk in ('mal_id', 'mal'):
                uval = vinfo.getUniqueID(uk)
                if uval:
                    return str(uval)
    except Exception:
        pass
    for prop in ('mal_id', 'otaku.mal_id', 'UniqueID(mal_id)', 'UniqueID(mal)'):
        try:
            val = item.getProperty(prop)
            if val and str(val).isdigit():
                return str(val)
        except Exception:
            pass
    if path and '?' in path:
        qs = parse.parse_qs(path.split('?', 1)[1])
        for qk in ('mal_id', 'id'):
            vals = qs.get(qk)
            if vals and str(vals[0]).isdigit():
                return str(vals[0])
    return ''


def _extract_subpath(path: str, prefix: str, default: str = '', item=None) -> str:
    """Extract subpath after prefix safely without raising IndexError, falling back to widget properties."""
    if path and prefix in path:
        parts = path.split(prefix, 1)
        sub = parts[1].split('?', 1)[0] if len(parts) > 1 else ''
        if sub:
            return sub
    if item is not None:
        wid_mal = _resolve_widget_mal_id(item, path or '')
        if wid_mal:
            return f"/{wid_mal}"
    if not path or path.startswith(('videodb://', 'library://')):
        return default
    clean = path.split('?', 1)[0].rstrip('/')
    if clean:
        parts = [p for p in clean.split('/') if p]
        return f"/{parts[-1]}" if parts else default
    return default


def _extract_watch_target(path: str, plugin: str, item=None) -> str:
    """Extracts '/mal_id/episode' from various plugin URL schemes safely without index errors."""
    if item is not None and (not path or plugin not in path):
        wid_mal = _resolve_widget_mal_id(item, path or '')
        if wid_mal:
            try:
                ep = int(item.getVideoInfoTag().getEpisode() or 1)
            except Exception:
                ep = 1
            return f"/{wid_mal}/{max(1, ep)}"

    clean_path = (path or '').split('?', 1)[0]
    if plugin in clean_path:
        sub = clean_path.split(plugin, 1)[1].strip('/')
    else:
        sub = clean_path.strip('/')

    parts = [p for p in sub.split('/') if p]
    if not parts:
        return "/1/1"

    if parts[0] == 'play_movie' and len(parts) >= 2:
        return f"/{parts[1]}/1"
    if parts[0] in ('play', 'play_oot', 'play_al', 'play_mal', 'watchlist_to_ep') and len(parts) >= 3:
        return f"/{parts[1]}/{parts[2]}"
    if parts[0] in ('play', 'play_oot', 'play_al', 'play_mal', 'animes') and len(parts) >= 2:
        return f"/{parts[1]}/1"

    if len(parts) >= 2 and parts[-2].isdigit() and parts[-1].isdigit():
        return f"/{parts[-2]}/{parts[-1]}"

    if parts[0].isdigit():
        ep = parts[1] if len(parts) >= 2 and parts[1].isdigit() else "1"
        return f"/{parts[0]}/{ep}"

    if len(parts) >= 2 and parts[1].isdigit():
        ep = parts[2] if len(parts) >= 3 and parts[2].isdigit() else "1"
        return f"/{parts[1]}/{ep}"

    if len(parts) >= 1 and parts[-1].isdigit():
        return f"/{parts[-1]}/1"

    if f'{plugin}/play' in clean_path:
        return clean_path.split(f'{plugin}/play', 1)[1]
    return f"/{'/'.join(parts)}"


def _has_resolved_target(item, path, plugin):
    """Return True only when item belongs to Otaku plugin or resolves a concrete widget mal_id."""
    if path and plugin in path:
        return True
    return bool(_resolve_widget_mal_id(item, path or ''))


def main():
    arg = sys.argv[1]
    item = sys.listitem
    path = item.getPath()
    plugin = 'plugin://plugin.video.otaku.rpdev'
    if arg == 'findrecommendations':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"Container.Update({plugin}/find_recommendations{subpath})")
    elif arg == 'findrelations':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"Container.Update({plugin}/find_relations{subpath})")
    elif arg == 'getwatchorder':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"Container.Update({plugin}/watch_order{subpath})")
    elif arg == 'viewreviews':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"Container.Update({plugin}/anime_reviews{subpath})")
    elif arg == 'viewstatistics':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"Container.Update({plugin}/anime_statistics{subpath})")
    elif arg == 'inspectmappings':
        if not _has_resolved_target(item, path, plugin):
            return
        target = _extract_watch_target(path, plugin, item=item)
        mal_seg = target.strip('/').split('/')[0] if target else ''
        if mal_seg and mal_seg.isdigit():
            xbmc.executebuiltin(f"RunPlugin({plugin}/inspect_mappings/{mal_seg})")
    elif arg == 'rescrape':
        if not _has_resolved_target(item, path, plugin):
            return
        params = dict(parse.parse_qsl(path.split('?', 1)[1])) if path and '?' in path else {}
        params.update(get_video_info(item))
        params['rescrape'] = 'true'
        base_path = path.split('?', 1)[0] if (path and plugin in path) else f"{plugin}/play{_extract_watch_target(path, plugin, item=item)}"
        path = f"{base_path}?{parse.urlencode(params)}"
        xbmc.executebuiltin(f"PlayMedia({path})")
    elif arg == 'sourceselect':
        if not _has_resolved_target(item, path, plugin):
            return
        params = dict(parse.parse_qsl(path.split('?', 1)[1])) if path and '?' in path else {}
        params.update(get_video_info(item))
        params['source_select'] = 'true'
        base_path = path.split('?', 1)[0] if (path and plugin in path) else f"{plugin}/play{_extract_watch_target(path, plugin, item=item)}"
        path = f"{base_path}?{parse.urlencode(params)}"
        xbmc.executebuiltin(f"PlayMedia({path})")
    elif arg == 'logout':
        subpath = _extract_subpath(path, f'{plugin}/watchlist', item=item)
        segs = [s for s in subpath.strip('/').split('/') if s]
        flavor_sub = f"/{segs[0]}" if segs else ""
        xbmc.executebuiltin(f"RunPlugin({plugin}/watchlist_logout{flavor_sub})")
    elif arg == 'deletefromdatabase':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"RunPlugin({plugin}/delete_anime_database{subpath})")
    elif arg == 'watchlist':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"RunPlugin({plugin}/watchlist_manager{subpath})")
    elif arg == 'markedaswatched':
        if not _has_resolved_target(item, path, plugin):
            return
        target = _extract_watch_target(path, plugin, item=item)
        xbmc.executebuiltin(f"RunPlugin({plugin}/marked_as_watched{target})")
    elif arg == 'markedasunwatched':
        if not _has_resolved_target(item, path, plugin):
            return
        target = _extract_watch_target(path, plugin, item=item)
        xbmc.executebuiltin(f"RunPlugin({plugin}/marked_as_unwatched{target})")
    elif arg == 'markpreviouswatched':
        if not _has_resolved_target(item, path, plugin):
            return
        target = _extract_watch_target(path, plugin, item=item)
        xbmc.executebuiltin(f"RunPlugin({plugin}/mark_previous_watched{target})")
    elif arg == 'clearcache':
        xbmc.executebuiltin(f"RunPlugin({plugin}/clear_cache)")
    elif arg == 'fanartselect':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"Container.Update({plugin}/fanart_select{subpath})")
    elif arg == 'seriesprofile':
        if not _has_resolved_target(item, path, plugin):
            return
        subpath = _extract_subpath(path, plugin, item=item)
        if subpath:
            xbmc.executebuiltin(f"RunPlugin({plugin}/series_profile{subpath})")
    elif arg == 'manualsubtitles':
        if path and path.startswith(('videodb://', 'library://')) and not _resolve_widget_mal_id(item, path):
            return
        xbmc.executebuiltin(f"RunPlugin({plugin}/search_subtitles)")
    else:
        raise KeyError("Could Not find %s in Context Menu Action" % arg)


if __name__ == "__main__":
    main()
