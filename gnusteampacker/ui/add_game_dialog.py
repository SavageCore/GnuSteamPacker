"""Add Game dialog — search by name or enter AppID directly."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from gnusteampacker import steam_api
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.queue_model import QueueItem


class AddGameDialog(Adw.Dialog):
    def __init__(self, on_add):
        super().__init__(title="Add Game")
        self._on_add = on_add
        self._search_results: list[dict] = []
        self._selected_appid: str = ""
        self._game_name: str = ""

        self.set_content_width(480)
        self.set_content_height(560)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)
        self.set_child(toolbar_view)

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(16)
        content.set_margin_end(16)
        toolbar_view.set_content(content)

        # ── Search section ──────────────────────────────────────────────────
        search_group = Adw.PreferencesGroup(title="Search by name")
        self._search_entry = Gtk.SearchEntry(placeholder_text="e.g. Half-Life, Portal…")
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", self._on_search_activate)
        search_group.add(self._search_entry)

        self._results_list = Gtk.ListBox()
        self._results_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._results_list.add_css_class("boxed-list")
        self._results_list.set_visible(False)
        self._results_list.connect("row-activated", self._on_result_selected)
        search_group.add(self._results_list)
        content.append(search_group)

        # ── Manual AppID ────────────────────────────────────────────────────
        manual_group = Adw.PreferencesGroup(title="Or enter AppID directly")
        manual_group.set_margin_top(16)
        self._appid_row = Adw.EntryRow(title="AppID")
        self._appid_row.connect("changed", self._on_appid_changed)
        manual_group.add(self._appid_row)
        content.append(manual_group)

        # ── Options ─────────────────────────────────────────────────────────
        options_group = Adw.PreferencesGroup(title="Options")
        options_group.set_margin_top(16)

        platforms = list(steam_api.PLATFORMS.keys())
        self._platform_row = Adw.ComboRow(title="Platform")
        platform_model = Gtk.StringList.new(platforms)
        self._platform_row.set_model(platform_model)
        options_group.add(self._platform_row)

        self._branch_row = Adw.EntryRow(title="Branch")
        self._branch_row.set_text("public")
        self._branch_row.connect("changed", self._on_branch_changed)
        options_group.add(self._branch_row)

        self._password_row = Adw.PasswordEntryRow(title="Branch password")
        self._password_row.set_visible(False)
        options_group.add(self._password_row)

        content.append(options_group)

        # ── Footer buttons ───────────────────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(20)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.close())
        btn_box.append(cancel_btn)

        self._add_btn = Gtk.Button(label="Add to Queue")
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.set_sensitive(False)
        self._add_btn.connect("clicked", self._on_add_clicked)
        btn_box.append(self._add_btn)

        content.append(btn_box)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        term = entry.get_text().strip()
        if len(term) >= 2:
            GLib.timeout_add(400, self._do_search, term)

    def _on_search_activate(self, entry: Gtk.SearchEntry) -> None:
        self._do_search(entry.get_text().strip())

    def _do_search(self, term: str) -> bool:
        async_run(self._search_async(term))
        return False

    async def _search_async(self, term: str) -> None:
        try:
            results = await steam_api.search_games(term)
        except Exception:
            results = []
        GLib.idle_add(self._populate_results, results)

    def _populate_results(self, results: list[dict]) -> bool:
        while row := self._results_list.get_first_child():
            self._results_list.remove(row)
        self._search_results = results[:10]
        for r in self._search_results:
            row = Adw.ActionRow(title=r["name"], subtitle=f"AppID: {r['appid']}")
            row.set_activatable(True)
            self._results_list.append(row)
        self._results_list.set_visible(bool(results))
        return False

    def _on_result_selected(self, listbox, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if 0 <= idx < len(self._search_results):
            r = self._search_results[idx]
            self._selected_appid = r["appid"]
            self._game_name = r["name"]
            self._appid_row.set_text(r["appid"])
            self._add_btn.set_sensitive(True)

    def _on_appid_changed(self, row: Adw.EntryRow) -> None:
        text = row.get_text().strip()
        if text.isdigit():
            self._selected_appid = text
            if not self._game_name:
                self._game_name = ""
            self._add_btn.set_sensitive(True)
        else:
            self._add_btn.set_sensitive(False)

    def _on_branch_changed(self, row: Adw.EntryRow) -> None:
        branch = row.get_text().strip()
        self._password_row.set_visible(branch not in ("", "public"))

    def _on_add_clicked(self, _btn) -> None:
        platforms = list(steam_api.PLATFORMS.values())
        platform = platforms[self._platform_row.get_selected()]
        appid = self._appid_row.get_text().strip() or self._selected_appid
        if not appid.isdigit():
            return
        item = QueueItem(
            appid=appid,
            game_name=self._game_name or f"App {appid}",
            platform=platform,
            branch=self._branch_row.get_text().strip() or "public",
            branch_password=self._password_row.get_text().strip(),
        )
        self._on_add(item)
        self.close()
