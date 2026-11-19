__metaclass__ = type

import os
import xbmcgui
from resources.lib.ui import control, database


class BaseWindow(xbmcgui.WindowXMLDialog):

    def __init__(self, xml_file, location, actionArgs=None):
        super().__init__(xml_file, location)

        control.closeBusyDialog()
        self.canceled = False

        self.setProperty('texture.white', os.path.join(control.IMAGES_PATH, 'white.png'))
        self.setProperty('texture.aver', os.path.join(control.IMAGES_PATH, 'anichart-icon-smile.png'))
        self.setProperty('texture.avernone', os.path.join(control.IMAGES_PATH, 'anichart-icon-none.png'))
        self.setProperty('texture.averstr', os.path.join(control.IMAGES_PATH, 'anichart-icon-null.png'))
        self.setProperty('texture.aversad', os.path.join(control.IMAGES_PATH, 'anichart-icon-frown.png'))
        self.setProperty('texture.popular', os.path.join(control.IMAGES_PATH, 'anichart-icon-popular.png'))
        self.setProperty('texture.mal', os.path.join(control.IMAGES_PATH, 'anichart-icon-mal.png'))
        self.setProperty('texture.anilist', os.path.join(control.IMAGES_PATH, 'anichart-icon-anilist.png'))
        self.setProperty('texture.imdb', os.path.join(control.IMAGES_PATH, 'anichart-icon-imdb.png'))
        self.setProperty('texture.trakt', os.path.join(control.IMAGES_PATH, 'anichart-icon-trakt.png'))
        self.setProperty('texture.tmdb', os.path.join(control.IMAGES_PATH, 'anichart-icon-tmdb.png'))
        self.setProperty('texture.simkl', os.path.join(control.IMAGES_PATH, 'anichart-icon-simkl.png'))
        self.setProperty('otaku.logo', control.OTAKU_LOGO3_PATH)
        self.setProperty('otaku.fanart', control.OTAKU_FANART)
        self.setProperty('settings.color', 'deepskyblue')
        self.setProperty('test.pattern', os.path.join(control.IMAGES_PATH, 'test_pattern.png'))
        self.setProperty('skin.dir', control.ADDON_PATH)

        if actionArgs is None:
            return

        if actionArgs.get('mal_id'):
            show_data = database.get_show(actionArgs['mal_id'])
            if show_data and show_data.get('kodi_meta'):
                self.item_information = database.loads(show_data['kodi_meta'])
            else:
                self.item_information = {}
        elif actionArgs.get('playnext'):
            self.item_information = actionArgs
        else:
            self.item_information = {}

        # for id, value in self.item_information['ids'].items():
        self.setProperty('item.ids.%s_id' % 1, str('gh'))

        # for i in self.item_information['art'].keys():
        self.setProperty('item.art.%s' % 'thumb', self.item_information.get('thumb') or '')
        self.setProperty('item.art.%s' % 'poster', self.item_information.get('poster') or '')
        self.setProperty('item.art.%s' % 'fanart', self.item_information.get('fanart') or '')
        self.setProperty('item.info.%s' % 'title', self.item_information.get('name') or '')

        # self.item_information['info'] = control.clean_air_dates(self.item_information['info'])

        # year, month, day = self.item_information['info'].get('aired', '0000-00-00').split('-')

        self.setProperty('item.info.aired.year', '2018')
        self.setProperty('item.info.aired.month', '01')
        self.setProperty('item.info.aired.day', '01')

        # value = 'TBA'
        try:
            self.setProperty('item.info.%s' % 1, str('fdf'))
        except UnicodeEncodeError:
            self.setProperty('item.info.%s' % 1, 'fdf')

    def setProperty(self, key, value):
        """Override WindowXML setProperty to coerce None/lists and enforce the 64KB UTF-8 ceiling."""
        key_str = str(key or '')
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ''
        val_str = '' if value is None else str(value)
        if len(val_str.encode('utf-8', errors='replace')) > 65536:
            control.log(f"AnichartBaseWindow: skipping oversized property '{key_str}' (>64KB)", 'warning')
            return
        super().setProperty(key_str, val_str)
