# -*- coding: utf-8 -*-
"""
    Otaku Add-on

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys

from resources.lib.ui import control
from resources.lib.ui.router import router_process


if __name__ == "__main__":
    control.process_context()
    from resources.lib import Main  # noQA
    plugin_url = control.get_plugin_url(sys.argv[0])
    plugin_params = control.get_plugin_params(sys.argv[2])
    try:
        router_process(plugin_url, plugin_params)
    except Exception as e:
        control.log(f'Unhandled exception in router_process: {e}', 'error')
        try:
            import xbmcplugin
            handle = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else -1
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle, succeeded=False)
        except Exception:
            pass
    else:
        # Queue changelog display via RunPlugin after root directory invoker cleanly finishes and window activates
        if (plugin_url == 'plugin://plugin.video.otaku.rpdev/' or not plugin_params) and control.ADDON_VERSION != control.getSetting('version'):
            control.setSetting('version', control.ADDON_VERSION)
            if control.getInt('showchangelog') == 0:
                control.execute('RunPlugin(plugin://plugin.video.otaku.rpdev/change_log)')
        elif control.ADDON_VERSION != control.getSetting('version'):
            control.setSetting('version', control.ADDON_VERSION)

    control.log(f'Finished Running: {plugin_url=} {plugin_params=}')
