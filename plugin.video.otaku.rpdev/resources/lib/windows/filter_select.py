import xbmcgui

from resources.lib.windows.base_window import BaseWindow
from resources.lib.ui import control, source_utils


class FilterSelect(BaseWindow):
    """
    Dialog to provide filter settings
    """

    def __init__(self, xml_file, xml_location):
        super().__init__(xml_file, xml_location)

        self.videocodec_list = None
        self.hdrcodec_list = None
        self.audiocodec_list = None
        self.audiochannels_list = None
        self.misc_list = None

        filter_list = control.getStringList("general.filters")
        self.current_filters = set(filter_list) if filter_list else set()
        self.initial_filters = set(self.current_filters)
        self._cancelled = False

    def onInit(self):
        self.videocodec_list = self.getControlList(1000)
        self.hdrcodec_list = self.getControlList(2000)
        self.audiocodec_list = self.getControlList(3000)
        self.audiochannels_list = self.getControlList(4000)
        self.misc_list = self.getControlList(5000)

        self._populate_list(self.videocodec_list, "videocodec")
        self._populate_list(self.hdrcodec_list, "hdrcodec")
        self._populate_list(self.audiocodec_list, "audiocodec")
        self._populate_list(self.audiochannels_list, "audiochannels")
        self._populate_list(self.misc_list, "misc")

        super().onInit()

    @staticmethod
    def _set_setting_item_properties(menu_item, setting):
        value = str(setting.get("value") if setting.get("value") is not None else '')
        menu_item.setProperty("label", str(setting.get("label") or ''))
        menu_item.setProperty("value", value)

    def _populate_list(self, codec_list, key):
        def _create_menu_item(setting):
            new_item = xbmcgui.ListItem(label=f"{setting['label']}")
            self._set_setting_item_properties(new_item, setting)
            return new_item

        for idx, codec in enumerate(
            sorted(
                [
                    i
                    for i in source_utils.INFO_STRUCT[key]
                    if i
                    not in {
                        "SDR",
                    }
                ]
            )
        ):
            info_item = {"label": codec, "value": codec in self.current_filters}
            if idx < codec_list.size():
                menu_item = codec_list.getListItem(idx)
                self._set_setting_item_properties(
                    menu_item,
                    info_item,
                )
            else:
                menu_item = _create_menu_item(info_item)
                codec_list.addItem(menu_item)

    def _flip_info(self, list_item):
        label = list_item.getLabel()
        if label in self.current_filters:
            self.current_filters.remove(label)
            list_item.setProperty("value", str(False))
        else:
            self.current_filters.add(label)
            list_item.setProperty("value", str(True))

    def reset_filters(self):
        """Reset all filter items in lists 1000..5000 in-place without calling reset()."""
        self.current_filters.clear()
        for lst in (
            self.videocodec_list,
            self.hdrcodec_list,
            self.audiocodec_list,
            self.audiochannels_list,
            self.misc_list,
        ):
            if lst is None:
                continue
            for idx in range(lst.size()):
                li = lst.getListItem(idx)
                if li is not None:
                    li.setProperty("value", "False")

    def onClick(self, control_id):
        """Kodi callback when a control is clicked"""
        if control_id in [1000, 2000, 3000, 4000, 5000]:
            lists = {
                1000: self.videocodec_list,
                2000: self.hdrcodec_list,
                3000: self.audiocodec_list,
                4000: self.audiochannels_list,
                5000: self.misc_list,
            }

            li = lists.get(control_id).getSelectedItem()
            self._flip_info(li)
        elif control_id == 6001:
            self.close()
        elif control_id == 6002:
            self._cancelled = True
            self.current_filters = set(self.initial_filters)
            super().close()
        elif control_id == 6003:
            self.reset_filters()

    def onAction(self, action):
        """Kodi callback when an action occurs"""
        action_id = action.getId()
        # ESC, Backspace, Context Menu, or Android TV Back closes the dialog
        if action_id in [9, 10, 92, 110, 117, 216]:
            self.close()

    def close(self):
        control.setStringList("general.filters", list(self.current_filters))
        super().close()
