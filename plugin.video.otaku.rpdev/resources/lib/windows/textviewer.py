from xbmcgui import WindowXMLDialog


class TextViewerXML(WindowXMLDialog):
    def __init__(self, xmlFilename: str, scriptPath: str, *args, **kwargs):
        super().__init__(xmlFilename, scriptPath)
        self.heading = kwargs.get('heading')
        self.instructions_text = kwargs.get('instructions_text')
        self.changelog_text = kwargs.get('changelog_text')
        self.news_text = kwargs.get('news_text')
        self.actioned = None

    def run(self):
        self.doModal()
        self.clearProperties()

    def onInit(self):
        self.set_properties()
        try:
            self.setFocusId(2062)
        except Exception:
            try:
                self.setFocusId(2060)
            except Exception:
                pass

    def onClick(self, controlID):
        self.handle_action(controlID)

    def handle_action(self, controlID):
        self.actioned = True
        self.close()

    def onAction(self, action):
        actionID = action.getId()

        # Handle all back, previous menu, escape, stop, and select actions
        # 9: ACTION_BACK (Android TV remote back button)
        # 10: ACTION_PREVIOUS_MENU
        # 13: ACTION_STOP
        # 92: ACTION_NAV_BACK
        # 110: ACTION_CONTEXT_MENU
        # 216: KEY_ESC
        if actionID in (9, 10, 13, 92, 110, 216):
            self.actioned = True
            self.close()
            return

        # 7: ACTION_SELECT_ITEM, 100: ACTION_MOUSE_LEFT_CLICK
        if actionID in (7, 100):
            self.handle_action(actionID)
            return

        try:
            super().onAction(action)
        except Exception:
            pass

    def set_properties(self):
        self.setProperty('otaku.news_text', self.news_text or '')
        self.setProperty('otaku.changelog_text', self.changelog_text or '')
        self.setProperty('otaku.text', self.instructions_text or '')
        self.setProperty('otaku.heading', self.heading or '')
