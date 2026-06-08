"""Main application window."""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from gnusteampacker import config as cfg
from gnusteampacker import credentials, steamcmd, worker
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.queue_model import QueueItem, Status
from gnusteampacker.ui.add_game_dialog import AddGameDialog
from gnusteampacker.ui.queue_row import QueueRow


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="GnuSteamPacker")
        conf = cfg.load()
        self.set_default_size(conf["window_width"], conf["window_height"])
        if conf["window_maximized"]:
            self.maximize()
        self.connect("close-request", self._on_close_request)

        self._items: list[QueueItem] = []
        self._rows: dict[int, QueueRow] = {}  # id(item) → row
        self._is_batch_running = False

        self._build_ui()

    def _on_close_request(self, _win) -> bool:
        conf = cfg.load()
        if not self.is_maximized():
            conf["window_width"] = self.get_width()
            conf["window_height"] = self.get_height()
        conf["window_maximized"] = self.is_maximized()
        if not bool(conf.get("remember_login", True)):
            steamcmd.clear_cached_login(Path(conf["steamcmd_path"]))
        cfg.save(conf)
        return False

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # ── Header bar ────────────────────────────────────────────────────
        header = Adw.HeaderBar()

        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_tooltip_text("Add game")
        add_btn.connect("clicked", self._on_add_clicked)
        header.pack_start(add_btn)

        self._start_btn = Gtk.Button(label="Start All")
        self._start_btn.add_css_class("suggested-action")
        self._start_btn.set_sensitive(False)
        self._start_btn.connect("clicked", self._on_start_all)
        header.pack_end(self._start_btn)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("Menu")
        menu_btn.set_menu_model(self._build_menu())
        header.pack_end(menu_btn)

        toolbar_view.add_top_bar(header)

        # ── Content: stack between status page and list ───────────────────
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)

        status_page = Adw.StatusPage(
            title="No games in queue",
            description="Press + to add a game to download.",
            icon_name="folder-download-symbolic",
        )
        self._stack.add_named(status_page, "empty")

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_top(12)
        self._list_box.set_margin_bottom(12)
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        scroll.set_child(self._list_box)
        self._stack.add_named(scroll, "queue")

        self._refresh_stack()

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About GnuSteamPacker", "app.about")
        return menu

    # ── Queue management ─────────────────────────────────────────────────

    def _on_add_clicked(self, _btn) -> None:
        AddGameDialog(on_add=self._add_item).present(self)

    def _add_item(self, item: QueueItem) -> None:
        self._items.append(item)
        row = QueueRow(
            item,
            remove_cb=self._remove_item,
            retry_cb=self._retry_item,
        )
        self._rows[id(item)] = row
        self._list_box.append(row)
        self._refresh_stack()
        self._update_start_button_state()

    def _remove_item(self, item: QueueItem) -> None:
        row = self._rows.pop(id(item), None)
        if row:
            self._list_box.remove(row)
        if item in self._items:
            self._items.remove(item)
        self._refresh_stack()
        self._update_start_button_state()

    def _refresh_stack(self) -> None:
        self._stack.set_visible_child_name("queue" if self._items else "empty")

    # ── Download ─────────────────────────────────────────────────────────

    def _on_start_all(self, _btn) -> None:
        if self._is_batch_running:
            return
        ready_items = [item for item in self._items if item.status == Status.READY]
        if not ready_items:
            return
        self._start_btn.set_sensitive(False)
        self._is_batch_running = True
        async_run(
            self._run_ready_items_sequentially(ready_items),
            done_cb=lambda _result, _exc: self._on_batch_done(),
        )

    async def _run_ready_items_sequentially(
        self,
        ready_items: list[QueueItem],
    ) -> None:
        conf = cfg.load()

        def update_cb(updated_item: QueueItem) -> None:
            GLib.idle_add(self._on_item_updated, updated_item)

        base_auth = self._build_auth_override(conf)

        remember_login = bool(
            (base_auth or {}).get("remember_login", conf.get("remember_login", True))
        )
        username = (base_auth or {}).get("username", credentials.get_username()).strip()

        for idx, item in enumerate(ready_items):
            per_item_auth = base_auth
            # Match SSP queue behavior: password is only passed for the first queued job.
            if idx > 0 and remember_login and username:
                per_item_auth = {
                    "username": username,
                    "password": "",
                    "remember_login": remember_login,
                }
            await worker.process_item(item, update_cb, auth_override=per_item_auth)
            if item.status in (Status.BADLOGIN, Status.STEAMGUARD):
                break

    def _on_batch_done(self) -> bool:
        self._is_batch_running = False
        self._update_start_button_state()
        return False

    def _retry_item(self, item: QueueItem) -> None:
        if item.status == Status.STEAMGUARD:
            self._show_steamguard_dialog(item)
            return
        item.status = Status.READY
        item.progress = 0.0
        item.error_detail = ""
        row = self._rows.get(id(item))
        if row:
            row.update(item)
        self._start_item(item, auth_override=None)

    def _start_item(self, item: QueueItem, auth_override: dict | None = None) -> None:
        conf = cfg.load()
        resolved_auth = (
            auth_override if auth_override is not None else self._build_auth_override(conf)
        )

        def update_cb(updated_item: QueueItem) -> None:
            GLib.idle_add(self._on_item_updated, updated_item)

        async_run(worker.process_item(item, update_cb, auth_override=resolved_auth))

    def _on_item_updated(self, item: QueueItem) -> bool:
        row = self._rows.get(id(item))
        if row:
            row.update(item)
        if item.status == Status.STEAMGUARD:
            self._show_steamguard_dialog(item)
        return False

    def _show_steamguard_dialog(self, item: QueueItem) -> None:
        dialog = Adw.AlertDialog(
            heading="Steam Guard Required",
            body="Enter the code from your email or authenticator app.",
        )
        entry = Gtk.Entry(placeholder_text="XXXXX", activates_default=True)

        def _on_guard_changed(_entry):
            text = _entry.get_text()
            upper = text.upper()
            if text != upper:
                pos = _entry.get_position()
                _entry.set_text(upper)
                _entry.set_position(pos)

        entry.connect("changed", _on_guard_changed)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("retry", "Retry")
        dialog.set_default_response("retry")
        dialog.set_response_appearance("retry", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_dlg, response: str) -> None:
            if response == "retry":
                self._retry_with_code(item, entry.get_text().strip())

        dialog.connect("response", on_response)
        dialog.present(self)

    def _retry_with_code(self, item: QueueItem, steam_guard_code: str) -> None:
        item.status = Status.READY
        item.progress = 0.0
        item.error_detail = ""
        row = self._rows.get(id(item))
        if row:
            row.update(item)

        def update_cb(updated_item: QueueItem) -> None:
            GLib.idle_add(self._on_item_updated, updated_item)

        async_run(worker.process_item(item, update_cb, steam_guard_code=steam_guard_code))

    def _update_start_button_state(self) -> None:
        has_ready = any(i.status == Status.READY for i in self._items)
        self._start_btn.set_sensitive(has_ready and not self._is_batch_running)

    def _build_auth_override(self, conf: dict) -> dict | None:
        remember_login = bool(conf.get("remember_login", True))

        username = credentials.get_username().strip()
        if username.lower() == "qr":
            credentials.clear_username()
            username = ""
        if not username:
            return None
        return {
            "username": username,
            "password": credentials.get_password(),
            "remember_login": remember_login,
        }
