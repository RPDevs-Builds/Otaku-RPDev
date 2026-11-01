# -*- coding: utf-8 -*-
"""
still_watching.py - Binge Watching Safeguard Dialog
===================================================
Displays an interactive countdown prompt after consecutive autoplayed episodes
to prevent unintended streaming, saving Debrid limits and watch history.
"""

from math import ceil
import time
import xbmc
from resources.lib.ui import control
from resources.lib.windows.base_window import BaseWindow


class StillWatchingXML(BaseWindow):
    closing_actions = (92, 10, 110, 9)
    selection_actions = (7, 100, 401)

    def __init__(self, xml_file, location, actionArgs=None):
        super().__init__(xml_file, location, actionArgs=actionArgs)
        self.closing_actions = (92, 10, 110, 9)
        self.selection_actions = (7, 100, 401)
        self.actionArgs = actionArgs or {}
        self.timeout = max(5, int(self.actionArgs.get('timeout') or control.getInt('smartplay.stillwatching_timeout') or 30))
        self.title = self.actionArgs.get('title') or control.playerWindow.getProperty('item.info.tvshowtitle') or 'Anime Series'
        self.closed = False
        self.keep_watching = False
        self.start_time = time.time()

    def onInit(self):
        self.setProperty('stillwatching.title', self.title)
        self.setProperty('stillwatching.prompt', f"Playback will pause in {self.timeout}s if unanswered.")
        self.setFocusId(3001)
        self._monitor()

    def onClick(self, control_id):
        if control_id == 3001:  # Keep Watching
            self.keep_watching = True
            self.close()
        elif control_id == 3002:  # Stop Playback
            self.keep_watching = False
            self.close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in self.closing_actions:
            self.keep_watching = False
            self.close()
        elif action_id in self.selection_actions:
            focus_id = self.getFocusId()
            if focus_id == 3001:
                self.keep_watching = True
                self.close()
            elif focus_id == 3002:
                self.keep_watching = False
                self.close()

    def _monitor(self):
        """Non-blocking timer updating progress and prompt."""
        progress_bar = None
        try:
            progress_bar = self.getControl(3014)
        except Exception:
            pass

        while not self.closed and not control.monitor.abortRequested():
            elapsed = time.time() - self.start_time
            remaining = max(0, int(ceil(self.timeout - elapsed)))

            self.setProperty('stillwatching.prompt', f"Playback will pause in {remaining}s if unanswered.")
            if progress_bar and self.timeout > 0:
                percent = max(0, min(100, (remaining / float(self.timeout)) * 100))
                try:
                    progress_bar.setPercent(percent)
                except Exception:
                    pass

            if remaining <= 0:
                self.keep_watching = False
                break

            if control.monitor.waitForAbort(0.25):
                self.keep_watching = False
                break

        if not self.closed:
            self.close()

    def doModal(self):
        super().doModal()
        return self.keep_watching

    def close(self):
        self.closed = True
        super().close()
