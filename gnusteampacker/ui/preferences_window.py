"""AdwPreferencesWindow for GnuSteamPacker settings."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from gnusteampacker import config as cfg
from gnusteampacker import credentials
from gnusteampacker.i18n import _, available_languages, language_display_name

_LEVEL_VALUES = [1, 3, 5, 7, 9]
_LEVEL_LABELS = [_("Fastest"), _("Fast"), _("Normal"), _("Maximum"), _("Ultra")]


class PreferencesWindow(Adw.PreferencesDialog):
    def __init__(self):
        super().__init__(title=_("Preferences"))
        self._conf = cfg.load()
        self._build_downloaders_page()
        self._build_output_page()
        self._build_credentials_page()
        self._build_appearance_page()

    # ── Downloaders ───────────────────────────────────────────────────────

    def _build_downloaders_page(self) -> None:
        page = Adw.PreferencesPage(title=_("Downloaders"), icon_name="utilities-terminal-symbolic")
        self.add(page)

        sc_group = Adw.PreferencesGroup(title=_("SteamCMD"))
        page.add(sc_group)

        self._sc_path = Adw.EntryRow(title=_("Path to SteamCMD"))
        self._sc_path.set_text(self._conf.get("steamcmd_path", ""))
        self._sc_path.connect("changed", lambda r: self._save("steamcmd_path", r.get_text()))
        sc_group.add(self._sc_path)

        self._sc_auto_dl = Adw.SwitchRow(title=_("Auto-download if missing"))
        self._sc_auto_dl.set_active(bool(self._conf.get("steamcmd_auto_download", True)))
        self._sc_auto_dl.connect(
            "notify::active",
            lambda r, _param: self._save("steamcmd_auto_download", r.get_active()),
        )
        sc_group.add(self._sc_auto_dl)

    # ── Output ────────────────────────────────────────────────────────────

    def _build_output_page(self) -> None:
        page = Adw.PreferencesPage(title=_("Output"), icon_name="folder-symbolic")
        self.add(page)

        files_group = Adw.PreferencesGroup(title=_("Files"))
        page.add(files_group)

        self._output_dir = Adw.EntryRow(title=_("Output directory"))
        self._output_dir.set_text(self._conf.get("output_dir", ""))
        self._output_dir.connect("changed", lambda r: self._save("output_dir", r.get_text()))
        files_group.add(self._output_dir)

        browse_row = Adw.ActionRow(title=_("Browse…"))
        browse_row.set_activatable(True)
        browse_row.set_icon_name("folder-open-symbolic")
        browse_row.connect("activated", self._pick_output_dir)
        files_group.add(browse_row)

        compression_group = Adw.PreferencesGroup(title=_("Compression"))
        page.add(compression_group)

        self._level_row = Adw.ComboRow(title=_("Level"))
        self._level_row.set_model(Gtk.StringList.new(_LEVEL_LABELS))
        current_level = int(self._conf.get("compression_level", 5))
        self._level_row.set_selected(
            _LEVEL_VALUES.index(current_level) if current_level in _LEVEL_VALUES else 2
        )
        self._level_row.connect("notify::selected", self._on_level_changed)
        compression_group.add(self._level_row)

        cpu_count = os.cpu_count() or 16
        current_threads = int(self._conf.get("compression_threads", max(1, cpu_count // 2)))
        adj = Gtk.Adjustment(
            value=current_threads,
            lower=1,
            upper=cpu_count,
            step_increment=1,
            page_increment=2,
            page_size=0,
        )
        self._threads_row = Adw.SpinRow(title=_("Threads"), adjustment=adj)
        self._threads_row.connect(
            "notify::value",
            lambda r, _param: self._save("compression_threads", int(r.get_value())),
        )
        compression_group.add(self._threads_row)

    def _pick_output_dir(self, _row) -> None:
        dialog = Gtk.FileDialog(title=_("Choose output directory"))
        dialog.select_folder(self.get_root(), None, self._on_output_dir_chosen)

    def _on_output_dir_chosen(self, dialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self._output_dir.set_text(path)
                self._save("output_dir", path)
        except Exception:
            pass

    def _on_level_changed(self, row: Adw.ComboRow, _param) -> None:
        self._save("compression_level", _LEVEL_VALUES[row.get_selected()])

    # ── Credentials ───────────────────────────────────────────────────────

    def _build_credentials_page(self) -> None:
        page = Adw.PreferencesPage(title=_("Account"), icon_name="system-users-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title=_("Steam credentials"))
        group.set_description(
            _(
                "Username/password are stored in GNOME Keyring (or a local file if unavailable). "
                "SteamCMD keeps its own login session when remembered login is enabled."
            )
        )
        page.add(group)

        saved_username = credentials.get_username().strip()
        if saved_username.lower() == "qr":
            # Clear legacy sentinel value from older QR-login implementation.
            credentials.clear_username()
            saved_username = ""

        self._username_row = Adw.EntryRow(title=_("Username"))
        self._username_row.set_text(saved_username)
        self._username_row.connect("changed", lambda r: credentials.set_username(r.get_text()))
        group.add(self._username_row)

        self._password_row = Adw.PasswordEntryRow(title=_("Password"))
        self._password_row.set_text(credentials.get_password())
        self._password_row.connect("changed", lambda r: credentials.set_password(r.get_text()))
        group.add(self._password_row)

        self._remember_login = Adw.SwitchRow(title=_("Remember login session"))
        self._remember_login.set_subtitle(
            _("Use Steam tool refresh/session tokens so later runs can auto-login.")
        )
        self._remember_login.set_active(bool(self._conf.get("remember_login", True)))
        self._remember_login.connect(
            "notify::active",
            lambda r, _param: self._save("remember_login", r.get_active()),
        )
        group.add(self._remember_login)

    # ── Appearance ────────────────────────────────────────────────────────

    def _build_appearance_page(self) -> None:
        page = Adw.PreferencesPage(
            title=_("Appearance"), icon_name="applications-graphics-symbolic"
        )
        self.add(page)

        group = Adw.PreferencesGroup(title=_("Theme"))
        page.add(group)

        schemes = [_("Follow System"), _("Light"), _("Dark")]
        self._scheme_row = Adw.ComboRow(title=_("Color scheme"))
        self._scheme_row.set_model(Gtk.StringList.new(schemes))
        current = self._conf.get("color_scheme", "default")
        idx = {"default": 0, "light": 1, "dark": 2}.get(current, 0)
        self._scheme_row.set_selected(idx)
        self._scheme_row.connect("notify::selected", self._on_scheme_changed)
        group.add(self._scheme_row)

        lang_group = Adw.PreferencesGroup(title=_("Language"))
        page.add(lang_group)

        self._language_codes = available_languages()
        self._lang_row = Adw.ComboRow(title=_("Display language"))
        self._lang_row.set_subtitle(_("Restart GnuSteamPacker to apply a language change"))
        self._lang_row.set_model(
            Gtk.StringList.new([language_display_name(code) for code in self._language_codes])
        )
        current_lang = self._conf.get("language", "system")
        self._lang_row.set_selected(
            self._language_codes.index(current_lang) if current_lang in self._language_codes else 0
        )
        self._lang_row.connect("notify::selected", self._on_language_changed)
        lang_group.add(self._lang_row)

    def _on_language_changed(self, row: Adw.ComboRow, _param) -> None:
        idx = row.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        self._save("language", self._language_codes[idx])

    def _on_scheme_changed(self, row: Adw.ComboRow, _param) -> None:
        from gi.repository import Adw as _Adw

        choices = ["default", "light", "dark"]
        scheme_key = choices[row.get_selected()]
        self._save("color_scheme", scheme_key)
        adw_schemes = {
            "default": _Adw.ColorScheme.DEFAULT,
            "light": _Adw.ColorScheme.FORCE_LIGHT,
            "dark": _Adw.ColorScheme.FORCE_DARK,
        }
        _Adw.StyleManager.get_default().set_color_scheme(adw_schemes[scheme_key])

    # ── Helpers ───────────────────────────────────────────────────────────

    def _save(self, key: str, value) -> None:
        self._conf[key] = value
        cfg.save(self._conf)
