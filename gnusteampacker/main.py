import logging
import signal
import sys
from pathlib import Path

from gnusteampacker import APP_ID, __version__
from gnusteampacker import config as cfg
from gnusteampacker.i18n import _


def main() -> int:
    import os

    if len(sys.argv) > 1 and sys.argv[1] == "pack":
        if len(sys.argv) > 2 and sys.argv[2] == "login":
            subtype = sys.argv[3] if len(sys.argv) > 3 else ""
            if subtype == "steam":
                from gnusteampacker.cli import run_pack_steam_login

                return run_pack_steam_login()
            if subtype == "multiup":
                from gnusteampacker.cli import run_pack_login

                return run_pack_login()
            print("Usage: gnusteampacker pack login <steam|multiup>", file=sys.stderr)
            return 1
        from gnusteampacker.cli import run_pack

        return run_pack(sys.argv[2:])

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    except ImportError:
        print(
            "GTK 4 / libadwaita not found. "
            "Install gnusteampacker-gui or PyGObject to use the GUI.\n"
            "For headless use: gnusteampacker pack --help",
            file=sys.stderr,
        )
        return 1

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
                icon_dir = Path(__file__).parent.parent / "data" / "icons"
                if icon_dir.exists():
                    display = Gdk.Display.get_default()
                    if display:
                        Gtk.IconTheme.get_for_display(display).add_search_path(str(icon_dir))
                self._window = MainWindow(app)
                self._setup_actions()
                self._apply_color_scheme()
            self._window.present()

        def _setup_actions(self) -> None:
            prefs_action = Gio.SimpleAction.new("preferences", None)
            prefs_action.connect(
                "activate", lambda *_args: PreferencesWindow().present(self._window)
            )
            self.add_action(prefs_action)

            about_action = Gio.SimpleAction.new("about", None)
            about_action.connect("activate", self._show_about)
            self.add_action(about_action)

            quit_action = Gio.SimpleAction.new("quit", None)
            quit_action.connect("activate", lambda *_args: self.quit())
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

        def _show_about(self, *_args) -> None:
            dialog = Adw.AboutDialog(
                application_name="GnuSteamPacker",
                application_icon=APP_ID,
                version=__version__,
                comments=_(
                    "A Linux-native GUI for downloading, cleaning, and packaging Steam "
                    "games for archival and sharing. Spiritual port of "
                    '<a href="https://github.com/Masquerade64/SuperSteamPacker">SuperSteamPacker</a>.'
                ),
                website="https://github.com/SavageCore/GnuSteamPacker",
                license_type=Gtk.License.GPL_3_0,
                copyright="© 2026 SavageCore",
                developers=["SavageCore"],
            )
            dialog.add_link(_("Donate"), "https://ko-fi.com/savagecore")
            dialog.add_acknowledgement_section(
                _("Third-Party Libraries and Special Thanks"),
                [
                    "aiohttp https://github.com/aio-libs/aiohttp",
                    "vdf https://github.com/ValvePython/vdf",
                    "SecretStorage https://github.com/mitya57/secretstorage",
                ],
            )
            dialog.present(self._window)

    conf = cfg.load()
    level = logging.DEBUG if os.getenv("GNUSTEAMPACKER_DEBUG") else logging.WARNING
    log_file = Path(conf["steamcmd_path"]).parent / "gnusteampacker.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    app = GnuSteamPackerApp()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
