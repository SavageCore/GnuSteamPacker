"""AdwPreferencesWindow for GnuSteamPacker settings."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from gnusteampacker import config as cfg
from gnusteampacker import credentials

_LEVEL_VALUES = [1, 3, 5, 7, 9]
_LEVEL_LABELS = ["Fastest", "Fast", "Normal", "Maximum", "Ultra"]


class PreferencesWindow(Adw.PreferencesDialog):
    def __init__(self):
        super().__init__(title="Preferences")
        self._conf = cfg.load()
        self._build_depotdownloader_page()
        self._build_output_page()
        self._build_credentials_page()
        self._build_appearance_page()

    # ── DepotDownloader ───────────────────────────────────────────────────

    def _build_depotdownloader_page(self) -> None:
        page = Adw.PreferencesPage(title="Downloaders", icon_name="utilities-terminal-symbolic")
        self.add(page)

        sc_group = Adw.PreferencesGroup(title="SteamCMD")
        page.add(sc_group)

        self._sc_path = Adw.EntryRow(title="Path to SteamCMD")
        self._sc_path.set_text(self._conf.get("steamcmd_path", ""))
        self._sc_path.connect("changed", lambda r: self._save("steamcmd_path", r.get_text()))
        sc_group.add(self._sc_path)

        self._sc_auto_dl = Adw.SwitchRow(title="Auto-download if missing")
        self._sc_auto_dl.set_active(bool(self._conf.get("steamcmd_auto_download", True)))
        self._sc_auto_dl.connect(
            "notify::active",
            lambda r, _: self._save("steamcmd_auto_download", r.get_active()),
        )
        sc_group.add(self._sc_auto_dl)

        dd_group = Adw.PreferencesGroup(title="DepotDownloader")
        page.add(dd_group)

        self._dd_path = Adw.EntryRow(title="Path to DepotDownloader")
        self._dd_path.set_text(self._conf.get("depotdownloader_path", ""))
        self._dd_path.connect("changed", lambda r: self._save("depotdownloader_path", r.get_text()))
        dd_group.add(self._dd_path)

        self._auto_dl = Adw.SwitchRow(title="Auto-download if missing")
        self._auto_dl.set_active(bool(self._conf.get("depotdownloader_auto_download", True)))
        self._auto_dl.connect(
            "notify::active",
            lambda r, _: self._save("depotdownloader_auto_download", r.get_active()),
        )
        dd_group.add(self._auto_dl)

    # ── Output ────────────────────────────────────────────────────────────

    def _build_output_page(self) -> None:
        page = Adw.PreferencesPage(title="Output", icon_name="folder-symbolic")
        self.add(page)

        files_group = Adw.PreferencesGroup(title="Files")
        page.add(files_group)

        self._output_dir = Adw.EntryRow(title="Output directory")
        self._output_dir.set_text(self._conf.get("output_dir", ""))
        self._output_dir.connect("changed", lambda r: self._save("output_dir", r.get_text()))
        files_group.add(self._output_dir)

        browse_row = Adw.ActionRow(title="Browse…")
        browse_row.set_activatable(True)
        browse_row.set_icon_name("folder-open-symbolic")
        browse_row.connect("activated", self._pick_output_dir)
        files_group.add(browse_row)

        compression_group = Adw.PreferencesGroup(title="Compression")
        page.add(compression_group)

        self._level_row = Adw.ComboRow(title="Level")
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
        self._threads_row = Adw.SpinRow(title="Threads", adjustment=adj)
        self._threads_row.connect(
            "notify::value",
            lambda r, _: self._save("compression_threads", int(r.get_value())),
        )
        compression_group.add(self._threads_row)

    def _pick_output_dir(self, _row) -> None:
        dialog = Gtk.FileDialog(title="Choose output directory")
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
        page = Adw.PreferencesPage(title="Account", icon_name="system-users-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="Steam credentials")
        group.set_description(
            "Credentials are stored in GNOME Keyring (or a local file if unavailable)."
        )
        page.add(group)

        self._username_row = Adw.EntryRow(title="Username")
        self._username_row.set_text(credentials.get_username())
        self._username_row.connect("changed", lambda r: credentials.set_username(r.get_text()))
        group.add(self._username_row)

        self._password_row = Adw.PasswordEntryRow(title="Password")
        self._password_row.set_text(credentials.get_password())
        self._password_row.connect("changed", lambda r: credentials.set_password(r.get_text()))
        group.add(self._password_row)

    # ── Appearance ────────────────────────────────────────────────────────

    def _build_appearance_page(self) -> None:
        page = Adw.PreferencesPage(title="Appearance", icon_name="applications-graphics-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="Theme")
        page.add(group)

        schemes = ["Follow System", "Light", "Dark"]
        self._scheme_row = Adw.ComboRow(title="Color scheme")
        self._scheme_row.set_model(Gtk.StringList.new(schemes))
        current = self._conf.get("color_scheme", "default")
        idx = {"default": 0, "light": 1, "dark": 2}.get(current, 0)
        self._scheme_row.set_selected(idx)
        self._scheme_row.connect("notify::selected", self._on_scheme_changed)
        group.add(self._scheme_row)

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
