import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from gnusteampacker import APP_ID, __version__
from gnusteampacker import config as cfg
from gnusteampacker.ui.preferences_window import PreferencesWindow
from gnusteampacker.ui.window import MainWindow


class GnuSteamPackerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._window: MainWindow | None = None
        self.connect("activate", self._on_activate)

    def _on_activate(self, app) -> None:
        if not self._window:
            self._window = MainWindow(app)
            self._setup_actions()
            self._apply_color_scheme()
        self._window.present()

    def _setup_actions(self) -> None:
        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", lambda *_: PreferencesWindow().present(self._window))
        self.add_action(prefs_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about)
        self.add_action(about_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def _apply_color_scheme(self) -> None:
        conf = cfg.load()
        scheme_map = {
            "default": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        scheme = scheme_map.get(conf.get("color_scheme", "default"), Adw.ColorScheme.DEFAULT)
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def _show_about(self, *_) -> None:
        dialog = Adw.AboutDialog(
            application_name="GnuSteamPacker",
            application_icon=APP_ID,
            version=__version__,
            comments="Download and package Steam games on Linux.",
            website="https://github.com/savagecore/GnuSteamPacker",
            license_type=Gtk.License.GPL_3_0,
            developers=["Oliver Sayers"],
        )
        dialog.present(self._window)


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = GnuSteamPackerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
