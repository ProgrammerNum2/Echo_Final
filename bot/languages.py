"""Admin-facing language names plus provider language-code mapping."""
from __future__ import annotations
import re

LANGUAGES = {
    "en": "English", "ru": "Russian", "uk": "Ukrainian", "vi": "Vietnamese",
    "es": "Spanish", "de": "German", "fr": "French", "it": "Italian",
    "pt": "Portuguese", "tr": "Turkish", "ar": "Arabic", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "hi": "Hindi", "pl": "Polish",
    "nl": "Dutch", "th": "Thai", "id": "Indonesian", "he": "Hebrew",
    "fa": "Persian", "cs": "Czech", "ro": "Romanian", "el": "Greek",
    "sv": "Swedish", "hu": "Hungarian", "bg": "Bulgarian", "sr": "Serbian",
    "kk": "Kazakh", "uz": "Uzbek", "ka": "Georgian", "hy": "Armenian",
}

BUTTON_CODES = ["en", "ru", "uk", "vi", "es", "de", "fr", "it", "pt", "tr", "ar", "zh", "ja", "ko", "hi", "pl", "nl", "th"]

_BY_NAME = {name.casefold(): name for name in LANGUAGES.values()}
_BY_CODE = {code.casefold(): name for code, name in LANGUAGES.items()}
_VALID = re.compile(r"^[\w\s\-()]+$", re.UNICODE)

def normalize(text: str | None) -> str | None:
    if not text:
        return None
    s = " ".join(text.split())
    if not s or len(s) > 40 or not _VALID.match(s):
        return None
    key = s.casefold()
    if key in _BY_CODE:
        return _BY_CODE[key]
    if key in _BY_NAME:
        return _BY_NAME[key]
    return s.title()

def same_language(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()

def code_for(language: str) -> str | None:
    key = language.casefold()
    for code, name in LANGUAGES.items():
        if name.casefold() == key or code.casefold() == key:
            return code
    return None
