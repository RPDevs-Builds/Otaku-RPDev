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
    try:
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
            # Queue changelog display via RunPlugin ONLY after the root directory invoker cleanly finishes
            is_root = (plugin_url in ('plugin://plugin.video.otaku.rpdev/', 'plugin://plugin.video.otaku.rpdev') and not plugin_params)
            saved_ver = control.getSetting('version') or control.getSetting('otaku.version')
            if is_root and control.ADDON_VERSION != saved_ver:
                control.setSetting('version', control.ADDON_VERSION)
                control.setSetting('otaku.version', control.ADDON_VERSION)
                if control.getInt('showchangelog') == 0:
                    control.execute('RunPlugin(plugin://plugin.video.otaku.rpdev/change_log)')
            elif is_root:
                control.setSetting('version', control.ADDON_VERSION)
                control.setSetting('otaku.version', control.ADDON_VERSION)

        control.log(f'Finished Running: {plugin_url=} {plugin_params=}')
    finally:
        control.cleanup()
