"""Main application window."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from gnusteampacker import worker
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.queue_model import QueueItem, Status
from gnusteampacker.ui.add_game_dialog import AddGameDialog
from gnusteampacker.ui.queue_row import QueueRow


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="GnuSteamPacker")
        self.set_default_size(700, 520)

        self._items: list[QueueItem] = []
        self._rows: dict[int, QueueRow] = {}  # id(item) → row

        self._build_ui()

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
        self._start_btn.set_sensitive(True)

    def _remove_item(self, item: QueueItem) -> None:
        row = self._rows.pop(id(item), None)
        if row:
            self._list_box.remove(row)
        if item in self._items:
            self._items.remove(item)
        self._refresh_stack()
        has_ready = any(i.status == Status.READY for i in self._items)
        self._start_btn.set_sensitive(has_ready)

    def _refresh_stack(self) -> None:
        self._stack.set_visible_child_name("queue" if self._items else "empty")

    # ── Download ─────────────────────────────────────────────────────────

    def _on_start_all(self, _btn) -> None:
        self._start_btn.set_sensitive(False)
        for item in self._items:
            if item.status == Status.READY:
                self._start_item(item)

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
        self._start_item(item)

    def _start_item(self, item: QueueItem) -> None:
        def update_cb(updated_item: QueueItem) -> None:
            GLib.idle_add(self._on_item_updated, updated_item)

        async_run(worker.process_item(item, update_cb))

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

