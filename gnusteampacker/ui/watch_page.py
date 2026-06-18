"""Watch page - persistent watchlist management and pending download processing."""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

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
    return list(groups.values())


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
        output_dir = Path(conf["output_dir"])
        if not output_dir.exists():
            return

        groups = _load_pending_groups(output_dir)
        self._pending_group.set_visible(bool(groups))

        for group in groups:
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
        row = Adw.ActionRow(title=entry.name, subtitle=subtitle)

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

        process_btn = Gtk.Button(label=_("Process"))
        process_btn.set_valign(Gtk.Align.CENTER)
        process_btn.add_css_class("suggested-action")
        process_btn.connect("clicked", self._make_process_handler(group))
        row.add_suffix(process_btn)

        return row

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
