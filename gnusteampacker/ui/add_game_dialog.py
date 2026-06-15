"""Add Game dialog - search by name or enter AppID directly."""

import asyncio
import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from gnusteampacker import steam_api
from gnusteampacker.i18n import _

log = logging.getLogger(__name__)
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.queue_model import QueueItem


class AddGameDialog(Adw.Dialog):
    def __init__(self, on_add):
        super().__init__(title=_("Add Game"))
        self._on_add = on_add
        self._search_results: list[dict] = []
        self._appid: str = ""
        self._game_name: str = ""
        self._branches: list[str] = ["public"]
        self._search_timeout_id: int = 0
        self._appid_timeout_id: int = 0
        self._available_platforms: list[str] = list(steam_api.PLATFORMS.values())
        self._has_all_option: bool = False

        self.set_content_width(480)
        self.set_content_height(580)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar_view)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroll)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(16)
        content.set_margin_end(16)
        scroll.set_child(content)

        # ── Search section ──────────────────────────────────────────────────
        search_group = Adw.PreferencesGroup(title=_("Search by name"))
        self._search_entry = Gtk.SearchEntry(placeholder_text=_("e.g. Half-Life, Portal…"))
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", self._on_search_activate)
        search_group.add(self._search_entry)

        self._results_list = Gtk.ListBox()
        self._results_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._results_list.add_css_class("boxed-list")
        self._results_list.set_visible(False)
        self._results_list.connect("row-activated", self._on_result_activated)
        search_group.add(self._results_list)
        content.append(search_group)

        # ── Manual AppID ────────────────────────────────────────────────────
        manual_group = Adw.PreferencesGroup(title=_("Or enter AppID directly"))
        manual_group.set_margin_top(16)

        self._appid_row = Adw.EntryRow(title=_("AppID"))
        self._appid_row.connect("changed", self._on_appid_changed)
        manual_group.add(self._appid_row)

        # Shown while fetching game info
        self._info_row = Adw.ActionRow(title=_("Looking up game…"))
        self._info_row.set_visible(False)
        spinner = Gtk.Spinner()
        spinner.start()
        self._info_row.add_suffix(spinner)
        manual_group.add(self._info_row)

        content.append(manual_group)

        # ── Options (disabled until game info loaded) ──────────────────────
        self._options_group = Adw.PreferencesGroup(title=_("Options"))
        self._options_group.set_margin_top(16)
        self._options_group.set_sensitive(False)

        platforms = list(steam_api.PLATFORMS.keys())
        self._platform_row = Adw.ComboRow(title=_("Platform"))
        self._platform_row.set_model(Gtk.StringList.new(platforms))
        self._options_group.add(self._platform_row)

        self._branch_row = Adw.ComboRow(title=_("Branch"))
        self._branch_row.set_model(Gtk.StringList.new(["public"]))
        self._branch_row.connect("notify::selected", self._on_branch_changed)
        self._options_group.add(self._branch_row)

        self._password_row = Adw.PasswordEntryRow(title=_("Branch password"))
        self._password_row.set_visible(False)
        self._options_group.add(self._password_row)

        content.append(self._options_group)

        # ── Footer ──────────────────────────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(20)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _btn: self.close())
        btn_box.append(cancel_btn)

        self._add_btn = Gtk.Button(label=_("Add to Queue"))
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.set_sensitive(False)
        self._add_btn.connect("clicked", self._on_add_clicked)
        btn_box.append(self._add_btn)

        content.append(btn_box)

    # ── Search ───────────────────────────────────────────────────────────────

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        term = entry.get_text().strip()
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
        if len(term) >= 2:
            self._search_timeout_id = GLib.timeout_add(400, self._do_search, term)
        else:
            self._results_list.set_visible(False)

    def _on_search_activate(self, entry: Gtk.SearchEntry) -> None:
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
        term = entry.get_text().strip()
        if len(term) >= 2:
            self._do_search(term)

    def _do_search(self, term: str) -> bool:
        self._search_timeout_id = 0
        async_run(self._search_async(term))
        return False

    async def _search_async(self, term: str) -> None:
        try:
            results = await steam_api.search_games(term)
        except Exception:
            log.exception("search_games failed for %r", term)
            results = []
        GLib.idle_add(self._populate_results, results)

    def _populate_results(self, results: list[dict]) -> bool:
        self._search_results = results[:10]
        self._results_list.remove_all()

        if not results:
            self._results_list.set_visible(False)
            return False

        if len(results) == 1:
            # Auto-select the only match
            self._results_list.set_visible(False)
            self._select_result(results[0])
            return False

        for r in self._search_results:
            row = Adw.ActionRow(
                title=r["name"], subtitle=_("AppID: {appid}").format(appid=r["appid"])
            )
            row.set_activatable(True)
            self._results_list.append(row)
        self._results_list.set_visible(True)
        return False

    def _on_result_activated(self, _listbox, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if 0 <= idx < len(self._search_results):
            self._results_list.set_visible(False)
            self._select_result(self._search_results[idx])

    def _select_result(self, r: dict) -> None:
        self._appid_row.set_text(r["appid"])
        # _on_appid_changed fires from set_text and triggers the info fetch

    # ── AppID entry ──────────────────────────────────────────────────────────

    def _on_appid_changed(self, row: Adw.EntryRow) -> None:
        text = row.get_text().strip()
        if self._appid_timeout_id:
            GLib.source_remove(self._appid_timeout_id)
            self._appid_timeout_id = 0
        # Reset dependent state
        self._appid = ""
        self._game_name = ""
        self._options_group.set_sensitive(False)
        self._add_btn.set_sensitive(False)
        self._info_row.set_visible(False)

        if text.isdigit() and len(text) >= 2:
            self._appid_timeout_id = GLib.timeout_add(600, self._do_fetch_info, text)

    def _do_fetch_info(self, appid: str) -> bool:
        self._appid_timeout_id = 0
        self._info_row.set_title(_("Looking up game…"))
        self._info_row.set_visible(True)
        async_run(self._fetch_info_async(appid))
        return False

    async def _fetch_info_async(self, appid: str) -> None:
        try:
            info, store = await asyncio.gather(
                steam_api.get_game_info(appid),
                steam_api.get_store_details(appid),
                return_exceptions=True,
            )
            if isinstance(info, Exception):
                GLib.idle_add(self._on_info_loaded, appid, None, {}, str(info))
                return
            if isinstance(store, Exception):
                store = {}
            GLib.idle_add(self._on_info_loaded, appid, info, store, None)
        except Exception as e:
            GLib.idle_add(self._on_info_loaded, appid, None, {}, str(e))

    def _on_info_loaded(
        self, appid: str, info: dict | None, store: dict, error: str | None
    ) -> bool:
        # Ignore stale callbacks if user already changed the AppID
        if self._appid_row.get_text().strip() != appid:
            return False

        self._info_row.set_visible(False)

        if error or not info:
            self._info_row.set_title(
                _("Not found: {error}").format(error=error or _("unknown error"))
            )
            self._info_row.set_visible(True)
            return False

        self._appid = appid
        self._game_name = info.get("name", f"App {appid}")
        self._branches = info.get("branches", ["public"])
        if "public" in self._branches:
            self._branches.remove("public")
        self._branches.insert(0, "public")

        # Populate branch dropdown
        self._branch_row.set_model(Gtk.StringList.new(self._branches))
        self._branch_row.set_selected(0)

        # Filter platform dropdown to only platforms this game supports
        avail_oses = store.get("platforms", {}) if store else {}
        if avail_oses:
            filtered = {
                label: key
                for label, key in steam_api.PLATFORMS.items()
                if avail_oses.get(steam_api.PLATFORM_OS[key], False)
            }
        else:
            filtered = steam_api.PLATFORMS
        self._available_platforms = list(filtered.values())
        labels = list(filtered.keys())
        self._has_all_option = len(labels) > 1
        if self._has_all_option:
            labels = [_("All available platforms")] + labels
        self._platform_row.set_model(Gtk.StringList.new(labels))
        try:
            win64_idx = self._available_platforms.index("win64")
            offset = 1 if self._has_all_option else 0
            self._platform_row.set_selected(win64_idx + offset)
        except ValueError:
            self._platform_row.set_selected(0)

        self._options_group.set_sensitive(True)
        self._add_btn.set_sensitive(True)
        return False

    # ── Branch / password ────────────────────────────────────────────────────

    def _on_branch_changed(self, row: Adw.ComboRow, _param) -> None:
        idx = row.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        branch = self._branches[idx] if idx < len(self._branches) else "public"
        self._password_row.set_visible(branch != "public")

    # ── Add ──────────────────────────────────────────────────────────────────

    def _on_add_clicked(self, _btn) -> None:
        if not self._appid:
            return
        selected = self._platform_row.get_selected()
        idx = self._branch_row.get_selected()
        branch = self._branches[idx] if idx < len(self._branches) else "public"
        password = self._password_row.get_text().strip()

        if self._has_all_option and selected == 0:
            platforms_to_add = self._available_platforms
        else:
            offset = 1 if self._has_all_option else 0
            platforms_to_add = [self._available_platforms[selected - offset]]

        for platform in platforms_to_add:
            self._on_add(
                QueueItem(
                    appid=self._appid,
                    game_name=self._game_name,
                    platform=platform,
                    branch=branch,
                    branch_password=password,
                )
            )
        self.close()
