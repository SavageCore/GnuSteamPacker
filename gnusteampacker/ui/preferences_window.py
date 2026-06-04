"""AdwPreferencesWindow for GnuSteamPacker settings."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from gnusteampacker import config as cfg
from gnusteampacker import credentials


class PreferencesWindow(Adw.PreferencesDialog):
    def __init__(self):
        super().__init__(title="Preferences")
        self._conf = cfg.load()
        self._build_steamcmd_page()
        self._build_output_page()
        self._build_credentials_page()
        self._build_appearance_page()

    # ── SteamCMD ─────────────────────────────────────────────────────────

    def _build_steamcmd_page(self) -> None:
        page = Adw.PreferencesPage(title="SteamCMD", icon_name="utilities-terminal-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="SteamCMD")
        page.add(group)

        self._steamcmd_path = Adw.EntryRow(title="Path to steamcmd.sh")
        self._steamcmd_path.set_text(self._conf.get("steamcmd_path", ""))
        self._steamcmd_path.connect("changed", lambda r: self._save("steamcmd_path", r.get_text()))
        group.add(self._steamcmd_path)

        self._auto_dl = Adw.SwitchRow(title="Auto-download if missing")
        self._auto_dl.set_active(bool(self._conf.get("steamcmd_auto_download", True)))
        self._auto_dl.connect(
            "notify::active",
            lambda r, _: self._save("steamcmd_auto_download", r.get_active()),
        )
        group.add(self._auto_dl)

    # ── Output ────────────────────────────────────────────────────────────

    def _build_output_page(self) -> None:
        page = Adw.PreferencesPage(title="Output", icon_name="folder-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="Files")
        page.add(group)

        self._output_dir = Adw.EntryRow(title="Output directory")
        self._output_dir.set_text(self._conf.get("output_dir", ""))
        self._output_dir.connect("changed", lambda r: self._save("output_dir", r.get_text()))
        group.add(self._output_dir)

        browse_row = Adw.ActionRow(title="Browse…")
        browse_row.set_activatable(True)
        browse_row.set_icon_name("folder-open-symbolic")
        browse_row.connect("activated", self._pick_output_dir)
        group.add(browse_row)

        split_group = Adw.PreferencesGroup(title="Compression")
        page.add(split_group)

        self._split_size = Adw.SpinRow.new_with_range(500, 50000, 512)
        self._split_size.set_title("Archive split size (MB)")
        self._split_size.set_value(float(self._conf.get("split_size_mb", 5120)))
        self._split_size.connect(
            "changed",
            lambda r: self._save("split_size_mb", int(r.get_value())),
        )
        split_group.add(self._split_size)

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
