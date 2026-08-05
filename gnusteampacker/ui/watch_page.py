"""Watch page - persistent watchlist management and pending download processing."""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from gnusteampacker import config as cfg
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.i18n import _
from gnusteampacker.queue_model import QueueItem
from gnusteampacker.ui.add_game_dialog import AddGameDialog
from gnusteampacker.watchlist import WatchEntry
from gnusteampacker.watchlist import load as load_watchlist
from gnusteampacker.watchlist import save as save_watchlist

log = logging.getLogger(__name__)

_MARGIN = 128


def _set_margins(widget: Gtk.Widget) -> Gtk.Widget:
    widget.set_margin_top(12)
    widget.set_margin_bottom(12)
    widget.set_margin_start(_MARGIN)
    widget.set_margin_end(_MARGIN)
    return widget


def _to_local_str(iso: str) -> str:
    """Convert an ISO-8601 UTC timestamp to a local-time display string."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return iso[:19].replace("T", " ")


def _load_pending_groups(output_dir: Path) -> list[list[dict]]:
    """Scan output_dir for *.pending.json sidecars, grouped by (appid, build_id, branch)."""
    sidecars: list[dict] = []
    for f in sorted(output_dir.glob("*.pending.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_sidecar_path"] = str(f)
            sidecars.append(data)
        except (json.JSONDecodeError, OSError):
            log.warning("Skipping corrupt sidecar: %s", f)
    groups: dict[tuple, list[dict]] = {}
    for s in sidecars:
        key = (s.get("appid", ""), s.get("build_id", ""), s.get("branch", ""))
        groups.setdefault(key, []).append(s)
    return sorted(
        groups.values(), key=lambda g: max(s.get("downloaded_at", "") for s in g), reverse=True
    )


class WatchPage(Gtk.Box):
    def __init__(self, add_daemon_items_cb=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._entries: list[WatchEntry] = []
        self._watchlist_rows: list[Gtk.Widget] = []
        self._pending_rows: list[Gtk.Widget] = []
        self._updating_timer = False
        self._add_daemon_items_cb = add_daemon_items_cb
        self._build_ui()
        self.refresh()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._watchlist_group = Adw.PreferencesGroup(title=_("Watchlist"))
        _set_margins(self._watchlist_group)
        self.append(self._watchlist_group)

        self._pending_group = Adw.PreferencesGroup(title=_("Unprocessed Downloads"))
        _set_margins(self._pending_group)
        self.append(self._pending_group)

        timer_group = Adw.PreferencesGroup(title=_("Automatic Checks"))
        _set_margins(timer_group)

        self._timer_switch = Adw.SwitchRow(
            title=_("Enable timer"),
            subtitle=_("Checks for updates every hour"),
        )
        self._timer_switch.connect("notify::active", self._on_timer_toggled)
        timer_group.add(self._timer_switch)

        self._notify_switch = Adw.SwitchRow(
            title=_("Notify when downloads need processing"),
            subtitle=_("Desktop notification after a scheduled check downloads updates"),
        )
        self._notify_switch.set_active(bool(cfg.load().get("notify_on_pending", True)))
        self._notify_switch.connect("notify::active", self._on_notify_toggled)
        timer_group.add(self._notify_switch)

        self._last_checked_row = Adw.ActionRow(title=_("Last checked"), subtitle=_("Never"))
        timer_group.add(self._last_checked_row)

        self._run_now_btn = Gtk.Button(label=_("Run now"))
        self._run_now_btn.set_valign(Gtk.Align.CENTER)
        self._run_now_btn.connect("clicked", self._on_run_now)
        run_now_row = Adw.ActionRow(title=_("Manual check"))
        run_now_row.add_suffix(self._run_now_btn)
        timer_group.add(run_now_row)

        self.append(timer_group)

    # ── Refresh ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._entries = load_watchlist()
        self._refresh_watchlist_rows()
        self._refresh_pending_rows()
        self._refresh_timer_state()
        self._refresh_last_checked()

    def _refresh_watchlist_rows(self) -> None:
        for row in self._watchlist_rows:
            self._watchlist_group.remove(row)
        self._watchlist_rows.clear()

        add_row = Adw.ActionRow(title=_("Add game to watchlist"))
        add_row.set_activatable(True)
        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", self._on_add_clicked)
        add_row.add_suffix(add_btn)
        add_row.connect("activated", self._on_add_clicked)
        self._watchlist_group.add(add_row)
        self._watchlist_rows.append(add_row)

        for entry in self._entries:
            row = self._make_entry_row(entry)
            self._watchlist_group.add(row)
            self._watchlist_rows.append(row)

    def _refresh_pending_rows(self) -> None:
        for row in self._pending_rows:
            self._pending_group.remove(row)
        self._pending_rows.clear()

        conf = cfg.load()
        dirs_to_scan: set[Path] = {Path(conf["output_dir"])}
        for entry in self._entries:
            if entry.output_dir:
                dirs_to_scan.add(Path(entry.output_dir))

        all_groups: list[list[dict]] = []
        for d in dirs_to_scan:
            if d.exists():
                all_groups.extend(_load_pending_groups(d))
        all_groups.sort(key=lambda g: max(s.get("downloaded_at", "") for s in g), reverse=True)

        self._pending_group.set_visible(bool(all_groups))

        for group in all_groups:
            row = self._make_pending_row(group)
            self._pending_group.add(row)
            self._pending_rows.append(row)

    def _refresh_timer_state(self) -> None:
        self._updating_timer = True
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", "gnusteampacker-daemon.timer"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # exit 4 = unit file not found
            installed = result.returncode != 4
            enabled = result.returncode == 0
            self._timer_switch.set_sensitive(installed)
            self._timer_switch.set_active(enabled)
            if not installed:
                self._timer_switch.set_subtitle(_("Install the gnusteampacker package to enable"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._timer_switch.set_sensitive(False)
            self._timer_switch.set_subtitle(_("systemctl not available"))
        finally:
            self._updating_timer = False

    def _refresh_last_checked(self) -> None:
        if not self._entries:
            self._last_checked_row.set_subtitle(_("Never"))
            return
        times = [e.last_checked for e in self._entries if e.last_checked]
        if times:
            self._last_checked_row.set_subtitle(_to_local_str(max(times)))
        else:
            self._last_checked_row.set_subtitle(_("Never"))

    # ── Row builders ──────────────────────────────────────────────────────

    def _make_entry_row(self, entry: WatchEntry) -> Adw.ActionRow:
        platforms_str = ", ".join(entry.platforms) if entry.platforms else _("None")
        build_str = entry.last_build_id or _("not yet checked")
        subtitle = (
            f"AppID: {entry.appid} · {platforms_str} · "
            f"{_('Branch')}: {entry.branch} · {_('Build')}: {build_str}"
        )
        if entry.output_dir:
            subtitle += f" · {_('Output')}: {entry.output_dir}"
        row = Adw.ActionRow(title=entry.name, subtitle=subtitle)

        gesture = Gtk.GestureClick(button=3)
        gesture.connect("released", lambda g, n, x, y: self._show_entry_menu(entry, row, x, y))
        row.add_controller(gesture)

        switch = Gtk.Switch()
        switch.set_active(entry.enabled)
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect("notify::active", self._make_switch_handler(entry))
        row.add_suffix(switch)

        remove_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.add_css_class("flat")
        remove_btn.add_css_class("destructive-action")
        remove_btn.connect("clicked", self._make_remove_handler(entry))
        row.add_suffix(remove_btn)

        return row

    def _make_pending_row(self, group: list[dict]) -> Adw.ActionRow:
        first = group[0]
        game_name = first.get("game_name", "Unknown")
        build_id = first.get("build_id", "")
        branch = first.get("branch", "public")
        platforms = ", ".join(s.get("platform", "") for s in group)
        downloaded_at = _to_local_str(first.get("downloaded_at", ""))

        row = Adw.ActionRow(
            title=f"{game_name} - Build {build_id}",
            subtitle=f"{platforms} · {branch} · {_('Downloaded')}: {downloaded_at}",
        )

        delete_btn = Gtk.Button(label=_("Delete"))
        delete_btn.set_valign(Gtk.Align.CENTER)
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._make_delete_handler(group))
        row.add_suffix(delete_btn)

        process_btn = Gtk.Button(label=_("Process"))
        process_btn.set_valign(Gtk.Align.CENTER)
        process_btn.add_css_class("suggested-action")
        process_btn.connect("clicked", self._make_process_handler(group))
        row.add_suffix(process_btn)

        return row

    # ── Context menu ──────────────────────────────────────────────────────

    def _show_entry_menu(self, entry: WatchEntry, row: Adw.ActionRow, x: float, y: float) -> None:
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        def _btn(label: str, callback) -> Gtk.Button:
            b = Gtk.Button(label=label, has_frame=False)
            b.connect("clicked", lambda _: (popover.popdown(), callback()))
            box.append(b)
            return b

        _btn(_("Set output path"), lambda: self._pick_output_dir(entry))

        if entry.output_dir:
            _btn(_("Clear custom path"), lambda: self._clear_output_dir(entry))

        forum_post = cfg.forum_post_cache_path(entry.appid)
        if forum_post.exists():
            _btn(_("Open forum post"), lambda: subprocess.run(["xdg-open", str(forum_post)]))

        popover.set_child(box)
        popover.set_parent(row)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    def _pick_output_dir(self, entry: WatchEntry) -> None:
        dialog = Gtk.FileDialog()
        if entry.output_dir:
            dialog.set_initial_folder(Gio.File.new_for_path(entry.output_dir))
        dialog.select_folder(self.get_root(), None, self._on_output_dir_selected, entry)

    def _on_output_dir_selected(self, dialog: Gtk.FileDialog, result, entry: WatchEntry) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        entry.output_dir = folder.get_path()
        save_watchlist(self._entries)
        self._refresh_watchlist_rows()

    def _clear_output_dir(self, entry: WatchEntry) -> None:
        entry.output_dir = ""
        save_watchlist(self._entries)
        self._refresh_watchlist_rows()

    # ── Handler factories ─────────────────────────────────────────────────

    def _make_switch_handler(self, entry: WatchEntry):
        def handler(switch, _param) -> None:
            entry.enabled = switch.get_active()
            save_watchlist(self._entries)

        return handler

    def _make_remove_handler(self, entry: WatchEntry):
        def handler(_btn) -> None:
            self._entries = [e for e in self._entries if e is not entry]
            save_watchlist(self._entries)
            self._refresh_watchlist_rows()

        return handler

    def _make_delete_handler(self, group: list[dict]):
        def handler(_btn) -> None:
            first = group[0]
            game_name = first.get("game_name", "Unknown")
            build_id = first.get("build_id", "")

            body = f"{game_name} - {_('Build')} {build_id} " + _(
                "and its archive files will be permanently deleted."
            )
            dialog = Adw.AlertDialog(heading=_("Delete download?"), body=body)
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("delete", _("Delete"))
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def on_response(_d, response: str) -> None:
                if response != "delete":
                    return
                for item in group:
                    sidecar = Path(item["_sidecar_path"])
                    sidecar.unlink(missing_ok=True)
                    archive = sidecar.parent / (item.get("archive_name", "") + ".7z")
                    if archive.name:
                        archive.unlink(missing_ok=True)
                self._refresh_pending_rows()

            dialog.connect("response", on_response)
            dialog.present(self.get_root())

        return handler

    def _make_process_handler(self, group: list[dict]):
        def handler(_btn) -> None:
            from gnusteampacker.ui.process_dialog import ProcessDialog

            dialog = ProcessDialog(group, on_processed=self._refresh_pending_rows)
            dialog.present(self.get_root())

        return handler

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_add_clicked(self, _widget) -> None:
        AddGameDialog(on_add=self._on_watch_item_added).present(self.get_root())

    def _on_watch_item_added(self, item: QueueItem) -> None:
        for entry in self._entries:
            if entry.appid == item.appid and entry.branch == item.branch:
                if item.platform not in entry.platforms:
                    entry.platforms.append(item.platform)
                    save_watchlist(self._entries)
                    GLib.idle_add(self._refresh_watchlist_rows)
                    self._queue_download(entry, [item.platform])
                return
        new_entry = WatchEntry(
            appid=item.appid,
            name=item.game_name or f"App {item.appid}",
            platforms=[item.platform],
            branch=item.branch,
            branch_password=item.branch_password,
            last_build_id="",
            last_checked="",
            enabled=True,
        )
        self._entries.append(new_entry)
        save_watchlist(self._entries)
        GLib.idle_add(self._refresh_watchlist_rows)
        self._queue_download(new_entry, new_entry.platforms)

    def _queue_download(self, entry: WatchEntry, platforms: list[str]) -> None:
        """Download the current build right away instead of waiting for a future change."""
        if not self._add_daemon_items_cb:
            return
        items = [
            QueueItem(
                appid=entry.appid,
                game_name=entry.name,
                platform=platform,
                branch=entry.branch,
                branch_password=entry.branch_password,
                from_daemon=True,
                output_dir=entry.output_dir,
            )
            for platform in platforms
        ]
        self._add_daemon_items_cb(items)

    def _on_notify_toggled(self, switch, _param) -> None:
        conf = cfg.load()
        conf["notify_on_pending"] = switch.get_active()
        cfg.save(conf)

    def _on_timer_toggled(self, switch, _param) -> None:
        if self._updating_timer:
            return
        action = "enable" if switch.get_active() else "disable"
        try:
            subprocess.run(
                ["systemctl", "--user", action, "--now", "gnusteampacker-daemon.timer"],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            log.warning("systemctl %s failed: %s", action, exc)

    def _on_run_now(self, _btn) -> None:
        from gnusteampacker.daemon import check_all

        self._run_now_btn.set_sensitive(False)
        self._run_now_btn.set_label(_("Checking…"))

        def _done(items, _exc) -> None:
            self._run_now_btn.set_sensitive(True)
            self._run_now_btn.set_label(_("Run now"))
            self.refresh()
            if items and self._add_daemon_items_cb:
                self._add_daemon_items_cb(items)

        async_run(check_all(), done_cb=_done)
