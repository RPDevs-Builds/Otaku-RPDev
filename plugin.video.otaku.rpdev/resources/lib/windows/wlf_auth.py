import os

from resources.lib.ui import control
from resources.lib.windows.base_window import BaseWindow


class WatchlistFlavorAuth(BaseWindow):
    def __init__(self, xml_file, location, flavor=None):
        super().__init__(xml_file, location)
        self.flavor = flavor
        self.authorized = False

    def onInit(self):
        qr_path = os.path.join(control.dataPath, 'qr_code.png')
        url = f"https://armkai.vercel.app/api/{self.flavor}"
        copy = control.copy2clip(url)
        if copy:
            self.setProperty('copy2clip', control.lang(30083))
        else:
            self.clearProperty('copy2clip')

        try:
            import pyqrcode
            os.makedirs(control.dataPath, exist_ok=True)
            qr = pyqrcode.create(url)
            qr.png(qr_path, scale=20)
            self.setProperty('qr_code', qr_path)
        except Exception as e:
            control.log(f"WatchlistFlavorAuth QR generation failed: {e}", 'warning')
            self.clearProperty('qr_code')

        control.closeBusyDialog()
        self.setFocusId(1000)

    def doModal(self):
        super().doModal()
        return self.authorized

    def onClick(self, controlId):
        if controlId == 1000:
            self.handle_action(7)
        else:
            self.handle_action(controlId)

    def onTouch(self, x, y):
        """Handle touchscreen events"""
        focusedControl = self.getFocusId()
        # Handle touch on button controls (1002 = Authorize, 1003 = Cancel)
        if focusedControl in [1002, 1003]:
            self.handle_action(focusedControl)

    def handle_action(self, actionID):
        if actionID == 1002:
            # Authorize button clicked
            self.set_settings()
        elif actionID == 1003:
            # Cancel button clicked
            self.close()
        elif actionID == 7 and self.getFocusId() == 1002:
            self.set_settings()
        elif actionID == 7 and self.getFocusId() == 1003:
            self.close()

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [9, 10, 92, 216]:
            # BACK / BACKSPACE / ESCAPE (including Android TV remote back action 9)
            self.close()

    def set_settings(self):
        res = {}
        if self.flavor == 'anilist':
            username = (self.getControl(1000).getText() or '').strip()
            token = (self.getControl(1001).getText() or '').strip()
            if not username or not token:
                control.ok_dialog(control.ADDON_NAME, 'Username and Token cannot be empty')
                return
            res['username'] = username
            res['token'] = token
        else:
            authvar = (self.getControl(1000).getText() or '').strip()
            if not authvar:
                control.ok_dialog(control.ADDON_NAME, 'Authorization code or URL cannot be empty')
                return
            res['authvar'] = authvar

        for _id, value in list(res.items()):
            control.setSetting('%s.%s' % (self.flavor, _id), value)

        self.authorized = True
        self.close()
