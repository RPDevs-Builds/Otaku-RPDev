import xbmcgui


class Progress_dialog(xbmcgui.WindowXMLDialog):
    def __init__(self, xml, path, *args, **kwargs):
        super().__init__(xml, path)
        config = kwargs.get('config', {})
        self.heading = config.get('heading', '')
        self.text = config.get('text', '')
        self.qr_code = config.get('qr_code', '')
        self.percent = config.get('percent', 0)
        self._cancelled = False

    def onInit(self):
        try:
            self.getControl(3002).setLabel(self.heading)
        except Exception:
            pass
        try:
            self.getControl(3005).setLabel(self.text)
        except Exception:
            pass
        self.setProperty('qr_code', self.qr_code)
        try:
            self.getControl(3003).setPercent(self.percent)
        except Exception:
            pass

    def onAction(self, action):
        actionID = action.getId()
        if actionID in [9, 10, 92, 110, 216]:
            # BACK / BACKSPACE / ESCAPE (including Android TV remote back action 9)
            self._cancelled = True
            self.close()

    def onClick(self, controlId):
        if controlId == 4001:  # Cancel button ID
            self._cancelled = True
            self.close()

    def update(self, percent=None, text=None):
        if percent is not None:
            try:
                self.getControl(3003).setPercent(percent)
            except Exception:
                pass
        if text is not None:
            try:
                self.getControl(3005).setLabel(text)
            except Exception:
                pass

    def iscanceled(self):
        return self._cancelled
