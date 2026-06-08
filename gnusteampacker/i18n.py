"""gettext bootstrap — bind the app's translation domain to its bundled .mo files.

The active language follows the desktop locale by default, but can be pinned
to a specific bundled translation via the "language" config key (applied on
the next launch, since GTK widgets bake their label text in at construction
time).

When a language is pinned, we also export it via $LANGUAGE — GNU gettext's
standard catalog-selection override — *before* touching the locale or any
GTK/libadwaita code. That's what makes the toolkit's own built-in strings
(About dialog chrome like "Details"/"Credits"/"Website"/"Code by", which come
from libadwaita's own translation catalog, not ours) follow the same choice,
provided the system has that language's GTK/libadwaita catalogs installed.
"""

import gettext
import locale
import os
from pathlib import Path

from gnusteampacker import config as cfg

DOMAIN = "gnusteampacker"

_locale_dir = Path(__file__).parent / "locale"

# Native display names for languages the app ships translations for.
_NATIVE_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "ja": "日本語",
    "nl": "Nederlands",
    "ru": "Русский",
    "uk": "Українська",
}

_language = cfg.load().get("language", "system")

if _language and _language != "system":
    os.environ["LANGUAGE"] = _language

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

gettext.bindtextdomain(DOMAIN, str(_locale_dir))
gettext.textdomain(DOMAIN)

_languages = None if _language in (None, "", "system") else [_language]
_translation = gettext.translation(DOMAIN, str(_locale_dir), languages=_languages, fallback=True)

_ = _translation.gettext


def available_languages() -> list[str]:
    """Language codes for the Preferences picker: 'system', 'en', plus every bundled translation."""
    codes = ["system", "en"]
    if _locale_dir.is_dir():
        for entry in sorted(_locale_dir.iterdir()):
            if (
                entry.name not in codes
                and entry.is_dir()
                and (entry / "LC_MESSAGES" / f"{DOMAIN}.mo").exists()
            ):
                codes.append(entry.name)
    return codes


def language_display_name(code: str) -> str:
    if code == "system":
        return _("Follow System")
    return _NATIVE_NAMES.get(code, code)
