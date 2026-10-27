import xbmc

from resources.lib.windows.base_window import BaseWindow
from resources.lib.ui import control


class PlayingNext(BaseWindow):
    def __init__(self, xml_file, xml_location, actionArgs=None):
        super().__init__(xml_file, xml_location, actionArgs=actionArgs)
        self.player = xbmc.Player()
        self.playing_file = self.player.getPlayingFile()
        self.closed = False
        self.actioned = False
        self.total_time = int(self.player.getTotalTime())
        self.duration = max(1, int(self.total_time - self.player.getTime()))
        self.skipoutro_end = actionArgs.get('skipoutro_end') if actionArgs else None
        self.default_action = control.getInt('playingnext.defaultaction')

    def onInit(self):
        self.background_tasks()

    def background_tasks(self):
        """Optimized background task with reduced updates"""
        if self.duration <= 0:
            self.close()
            return
        progress_bar = None
        try:
            progress_bar = self.getControl(3014)
        except Exception as e:
            control.log(f"playing_next getControl(3014) warning: {e}", 'debug')
        while not self.closed:
            p = self.player
            if not p:
                break
            try:
                if self.playing_file != p.getPlayingFile():
                    break
                if progress_bar:
                    percent = ((self.total_time - int(p.getTime())) / max(1, self.duration)) * 100
                    if percent < 2:
                        break
                    progress_bar.setPercent(percent)
            except Exception:
                break
            xbmc.sleep(1000)
        self.close()

    def doModal(self):
        super(PlayingNext, self).doModal()

    def close(self):
        if getattr(self, 'closed', False):
            return
        # If no user action was taken, perform the default action.
        if not self.actioned and self.player:
            try:
                if self.default_action == 1:
                    self.player.pause()
            except Exception as e:
                control.log(f"playing_next pause error: {e}", 'debug')
        self.closed = True
        self.player = None
        super(PlayingNext, self).close()

    def onClick(self, controlID):
        self.handle_action(controlID)

    def handle_action(self, controlID):
        if controlID == 3001:   # playnext
            self.actioned = True
            if self.player:
                total_t = self.player.getTotalTime() if hasattr(self.player, 'getTotalTime') else 0
                self.player.seekTime(max(0, total_t - 5))
            self.close()
        if controlID == 3002:   # close
            self.actioned = True
            self.close()
        if controlID == 3003:   # skipoutro
            self.actioned = True
            skipoutro_end_skip_time = self.skipoutro_end
            if skipoutro_end_skip_time != 0:
                self.player.seekTime(skipoutro_end_skip_time)
            self.close()

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [9, 10, 92, 216]:
            # BACK / BACKSPACE / ESCAPE (including Android TV remote back action 9)
            self.close()

        if actionID in (7, 100):
            # ENTER / SELECT
            self.handle_action(self.getFocusId())
