import os
import threading
import time

from resources.lib.ui import control
from resources.lib.windows.base_window import BaseWindow


class WatchlistFlavorAuth(BaseWindow):
    DEFAULT_IDLE_TIMEOUT = 300

    def __init__(self, xml_file, location, flavor=None, idle_timeout=None):
        super().__init__(xml_file, location)
        self.flavor = flavor
        self.authorized = False
        if idle_timeout is None:
            self.idle_timeout = float(self.DEFAULT_IDLE_TIMEOUT)
        else:
            self.idle_timeout = max(0.0, float(idle_timeout))
        self._idle_stop_event = threading.Event()
        self._idle_thread = None
        self._last_activity = time.monotonic()

    def _reset_idle_timer(self):
        if hasattr(self, '_last_activity'):
            self._last_activity = time.monotonic()

    def _start_idle_timer(self):
        if getattr(self, 'idle_timeout', 0) <= 0:
            return
        self._stop_idle_timer()
        stop_event = getattr(self, '_idle_stop_event', None)
        if stop_event is None:
            return
        stop_event.clear()
        self._reset_idle_timer()
        t = threading.Thread(target=self._idle_watchdog, name='Otaku-WlfAuthIdleGuard', daemon=True)
        self._idle_thread = t
        t.start()

    def _stop_idle_timer(self):
        stop_event = getattr(self, '_idle_stop_event', None)
        if stop_event is not None:
            stop_event.set()
        thread = getattr(self, '_idle_thread', None)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if hasattr(self, '_idle_thread'):
            self._idle_thread = None

    def _idle_watchdog(self):
        stop_event = self._idle_stop_event
        while not stop_event.is_set():
            if control.monitor.abortRequested():
                control.log("WatchlistFlavorAuth: Kodi abort requested, closing auth dialog", 'info')
                self.close()
                return
            elapsed = time.monotonic() - self._last_activity
            remaining = self.idle_timeout - elapsed
            if remaining <= 0:
                control.log(
                    f"WatchlistFlavorAuth: Closing unattended '{self.flavor}' auth dialog after {int(self.idle_timeout)}s inactivity",
                    'info',
                )
                self.close()
                return
            stop_event.wait(timeout=min(0.5, max(0.01, remaining)))

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
        self._reset_idle_timer()

    def doModal(self):
        self._start_idle_timer()
        try:
            super().doModal()
        finally:
            self._stop_idle_timer()
        return self.authorized

    def close(self):
        self._stop_idle_timer()
        super().close()

    def onClick(self, controlId):
        self._reset_idle_timer()
        if controlId == 1000:
            self.handle_action(7)
        else:
            self.handle_action(controlId)

    def onTouch(self, x, y):
        """Handle touchscreen events"""
        self._reset_idle_timer()
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
        self._reset_idle_timer()
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
