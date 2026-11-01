"""services/__init__.py - Registry of Native Subtitle Providers
=============================================================
"""

# -*- coding: utf-8 -*-

from resources.lib.subtitles.services.opensubtitles import OpenSubtitlesService
from resources.lib.subtitles.services.subdl import SubDLService
from resources.lib.subtitles.services.subsource import SubSourceService
from resources.lib.subtitles.services.podnadpisi import PodnadpisiService
from resources.lib.subtitles.services.bsplayer import BSPlayerService
from resources.lib.subtitles.services.addic7ed import Addic7edService

ALL_SERVICES = {
    'opensubtitles': OpenSubtitlesService,
    'subdl': SubDLService,
    'subsource': SubSourceService,
    'podnadpisi': PodnadpisiService,
    'bsplayer': BSPlayerService,
    'addic7ed': Addic7edService,
}
