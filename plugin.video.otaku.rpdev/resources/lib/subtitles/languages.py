"""languages.py - Language Code Mapping for Subtitle Providers
============================================================
"""

# -*- coding: utf-8 -*-

from typing import Optional, List

try:
    import xbmc
    HAS_XBMC = True
except ImportError:
    HAS_XBMC = False


# Fallback dictionary for testing outside Kodi
LANG_MAP = {
    'english': {'iso639_1': 'en', 'iso639_2': 'eng', 'name': 'English'},
    'japanese': {'iso639_1': 'ja', 'iso639_2': 'jpn', 'name': 'Japanese'},
    'spanish': {'iso639_1': 'es', 'iso639_2': 'spa', 'name': 'Spanish'},
    'french': {'iso639_1': 'fr', 'iso639_2': 'fre', 'name': 'French'},
    'german': {'iso639_1': 'de', 'iso639_2': 'ger', 'name': 'German'},
    'italian': {'iso639_1': 'it', 'iso639_2': 'ita', 'name': 'Italian'},
    'dutch': {'iso639_1': 'nl', 'iso639_2': 'dut', 'name': 'Dutch'},
    'russian': {'iso639_1': 'ru', 'iso639_2': 'rus', 'name': 'Russian'},
    'portuguese': {'iso639_1': 'pt', 'iso639_2': 'por', 'name': 'Portuguese'},
    'korean': {'iso639_1': 'ko', 'iso639_2': 'kor', 'name': 'Korean'},
    'chinese': {'iso639_1': 'zh', 'iso639_2': 'chi', 'name': 'Chinese'},
    'arabic': {'iso639_1': 'ar', 'iso639_2': 'ara', 'name': 'Arabic'},
    'hindi': {'iso639_1': 'hi', 'iso639_2': 'hin', 'name': 'Hindi'},
    'turkish': {'iso639_1': 'tr', 'iso639_2': 'tur', 'name': 'Turkish'},
    'polish': {'iso639_1': 'pl', 'iso639_2': 'pol', 'name': 'Polish'},
    'swedish': {'iso639_1': 'sv', 'iso639_2': 'swe', 'name': 'Swedish'},
    'norwegian': {'iso639_1': 'no', 'iso639_2': 'nor', 'name': 'Norwegian'},
    'danish': {'iso639_1': 'da', 'iso639_2': 'dan', 'name': 'Danish'},
    'finnish': {'iso639_1': 'fi', 'iso639_2': 'fin', 'name': 'Finnish'},
}


def to_iso639_1(lang: str) -> str:
    """Convert language name or code to 2-letter ISO 639-1 code (e.g. 'English' -> 'en')."""
    if not lang:
        return 'en'
    clean = str(lang).lower().strip()
    if len(clean) == 2:
        return clean

    if HAS_XBMC and hasattr(xbmc, 'convertLanguage') and hasattr(xbmc, 'ISO_639_1'):
        try:
            converted = xbmc.convertLanguage(clean, xbmc.ISO_639_1)
            if isinstance(converted, str) and converted:
                return converted.lower()
        except Exception:
            pass

    for entry in LANG_MAP.values():
        if clean in (entry['iso639_1'], entry['iso639_2'], entry['name'].lower()):
            return entry['iso639_1']

    return clean[:2]


def to_iso639_2(lang: str) -> str:
    """Convert language name or code to 3-letter ISO 639-2 code (e.g. 'English' -> 'eng')."""
    if not lang:
        return 'eng'
    clean = str(lang).lower().strip()
    if len(clean) == 3:
        return clean

    if HAS_XBMC and hasattr(xbmc, 'convertLanguage') and hasattr(xbmc, 'ISO_639_2'):
        try:
            converted = xbmc.convertLanguage(clean, xbmc.ISO_639_2)
            if isinstance(converted, str) and converted:
                return converted.lower()
        except Exception:
            pass

    for entry in LANG_MAP.values():
        if clean in (entry['iso639_1'], entry['iso639_2'], entry['name'].lower()):
            return entry['iso639_2']

    return clean[:3]


def to_english_name(lang: str) -> str:
    """Convert language code or synonym to standardized English name (e.g. 'eng' -> 'English')."""
    if not lang:
        return 'English'
    clean = str(lang).lower().strip()

    if HAS_XBMC and hasattr(xbmc, 'convertLanguage') and hasattr(xbmc, 'ENGLISH_NAME'):
        try:
            converted = xbmc.convertLanguage(clean, xbmc.ENGLISH_NAME)
            if isinstance(converted, str) and converted:
                return converted
        except Exception:
            pass

    for entry in LANG_MAP.values():
        if clean in (entry['iso639_1'], entry['iso639_2'], entry['name'].lower()):
            return entry['name']

    return str(lang).capitalize()


def map_languages_to_iso639_1(languages: List[str]) -> List[str]:
    """Convert a list of language names/codes to distinct ISO 639-1 codes."""
    res = []
    seen = set()
    for lang in languages:
        code = to_iso639_1(lang)
        if code and code not in seen:
            seen.add(code)
            res.append(code)
    return res or ['en']


def is_language_match(lang_a: str, lang_b: str) -> bool:
    """Check if two language names, 2-letter, or 3-letter codes represent the same language."""
    if not lang_a or not lang_b:
        return False
    a_clean = str(lang_a).lower().strip()
    b_clean = str(lang_b).lower().strip()
    if a_clean == 'none' or b_clean == 'none':
        return a_clean == b_clean
    return to_iso639_1(a_clean) == to_iso639_1(b_clean)


def get_preferred_subtitle_language() -> str:
    """
    Returns the preferred subtitle language as a 2-letter ISO 639-1 code (e.g. 'en'),
    or 'none' if subtitles are disabled in settings (general.subtitles == 0).
    """
    from resources.lib.ui import control
    try:
        sub_setting_idx = control.getInt('general.subtitles')
    except Exception:
        sub_setting_idx = 1

    subtitle_langs = [
        "none", "English", "Japanese", "Spanish", "French", "German",
        "Italian", "Dutch", "Russian", "Portuguese", "Korean", "Chinese",
        "Arabic", "Hindi", "Turkish", "Polish", "Swedish", "Norwegian",
        "Danish", "Finnish"
    ]
    if sub_setting_idx == 0:
        return "none"
    pref_name = subtitle_langs[sub_setting_idx] if sub_setting_idx < len(subtitle_langs) else "English"
    return to_iso639_1(pref_name)


