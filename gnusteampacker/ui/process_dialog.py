"""Process Dialog - turn a daemon-downloaded archive into a release post."""

import asyncio
import logging
import shutil
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from gnusteampacker import config as cfg
from gnusteampacker import credentials, hashing, multiup_api, release_text
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.i18n import _
from gnusteampacker.queue_model import QueueItem
from gnusteampacker.speed import SpeedTracker

log = logging.getLogger(__name__)


def _human_size(n: int) -> str:
    # ponytail: local size formatter, promote to queue_model if reused elsewhere
    if n < 1_000:
        return f"{n} B"
    if n < 1_000_000:
        return f"{n / 1_000:.1f} KB"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{n / 1_000_000_000:.1f} GB"


def _item_from_sidecar(sidecar: dict, version: str) -> QueueItem:
    return QueueItem(
        appid=sidecar["appid"],
        game_name=sidecar["game_name"],
        platform=sidecar["platform"],
        branch=sidecar["branch"],
        branch_password=sidecar.get("branch_password", ""),
        build_id=sidecar.get("build_id", ""),
        build_time=sidecar.get("build_time", ""),
        game_version=version,
        depot_list=sidecar.get("depot_list", []),
        available_platforms=sidecar.get("available_platforms", []),
    )


class ProcessDialog(Adw.Dialog):
    def __init__(self, group: list[dict], on_processed) -> None:
        super().__init__(title=_("Process Download"))
        self._group = group
        self._on_processed = on_processed

        first = group[0]
        self._appid = first.get("appid", "")
        self._game_name = first.get("game_name", "")
        self._build_id = first.get("build_id", "")
        self._branch = first.get("branch", "public")
        self._platforms = [s.get("platform", "") for s in group]

        self.set_content_width(560)
        self._progress_detail = ""

        self._toolbar_view = Adw.ToolbarView()
        self._header = Adw.HeaderBar()
        self._toolbar_view.add_top_bar(self._header)
        self.set_child(self._toolbar_view)

        self._page_stack = Gtk.Stack()
        self._page_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self._toolbar_view.set_content(self._page_stack)

        self._page_stack.add_named(self._build_input_page(), "input")
        self._page_stack.add_named(self._build_result_page(), "result")

    # ── Page builders ─────────────────────────────────────────────────────

    def _build_input_page(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        _output_dir = Path(cfg.load()["output_dir"])
        _total = 0
        for s in self._group:
            p = _output_dir / f"{_item_from_sidecar(s, '').archive_name}.7z"
            if p.exists():
                _total += p.stat().st_size
        _size_str = f" · {_human_size(_total)}" if _total else ""

        info_group = Adw.PreferencesGroup(title=_("Archive"))
        _plats = ", ".join(self._platforms)
        _subtitle = f"Build {self._build_id} · {_plats} · {self._branch}{_size_str}"
        info_row = Adw.ActionRow(title=self._game_name, subtitle=_subtitle)
        info_group.add(info_row)
        box.append(info_group)

        options_group = Adw.PreferencesGroup()
        options_group.set_margin_top(16)

        self._version_entry = Adw.EntryRow(title=_("Version number (e.g. 1.3.5)"))
        self._version_entry.connect("changed", self._on_version_changed)
        options_group.add(self._version_entry)

        cached_url = cfg.load().get("forum_post_urls", {}).get(self._appid, "")
        self._forum_url_entry = Adw.EntryRow(title=_("cs.rin.ru thread URL"))
        self._forum_url_entry.set_text(cached_url)
        options_group.add(self._forum_url_entry)

        self._upload_switch = Adw.SwitchRow(
            title=_("Upload to multiup.io"),
            subtitle=_("Requires multiup.io credentials in Preferences"),
        )
        self._upload_switch.connect("notify::active", self._on_upload_toggled)
        options_group.add(self._upload_switch)

        box.append(options_group)

        self._progress = Gtk.ProgressBar()
        self._progress.set_show_text(True)
        self._progress.set_margin_top(16)
        self._progress.set_visible(False)
        box.append(self._progress)

        self._progress_label = Gtk.Label(label="")
        self._progress_label.set_xalign(0)
        self._progress_label.add_css_class("dim-label")
        self._progress_label.set_margin_top(4)
        self._progress_label.set_visible(False)
        box.append(self._progress_label)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(16)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _btn: self.close())
        btn_box.append(cancel_btn)

        self._process_btn = Gtk.Button(label=_("Generate Release Text"))
        self._process_btn.add_css_class("suggested-action")
        self._process_btn.set_sensitive(False)
        self._process_btn.connect("clicked", self._on_process_clicked)
        btn_box.append(self._process_btn)

        box.append(btn_box)
        return box

    def _build_result_page(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        label = Gtk.Label(label=_("Forum Post"))
        label.add_css_class("heading")
        label.set_halign(Gtk.Align.START)
        label.set_margin_bottom(8)
        box.append(label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_min_content_height(260)

        self._result_view = Gtk.TextView()
        self._result_view.set_editable(False)
        self._result_view.set_monospace(True)
        self._result_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._result_view.set_left_margin(8)
        self._result_view.set_right_margin(8)
        self._result_view.set_top_margin(8)
        self._result_view.set_bottom_margin(8)
        self._result_buffer = self._result_view.get_buffer()
        scroll.set_child(self._result_view)
        box.append(scroll)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(16)
        btn_box.set_halign(Gtk.Align.END)

        self._copy_post_btn = Gtk.Button(label=_("Copy Forum Post"))
        self._copy_post_btn.connect("clicked", self._on_copy_post_clicked)
        btn_box.append(self._copy_post_btn)

        self._copy_btn = Gtk.Button(label=_("Copy Update Message"))
        self._copy_btn.add_css_class("suggested-action")
        self._copy_btn.connect("clicked", self._on_copy_clicked)
        btn_box.append(self._copy_btn)

        close_btn = Gtk.Button(label=_("Close"))
        close_btn.connect("clicked", lambda _btn: self.close())
        btn_box.append(close_btn)

        box.append(btn_box)
        return box

    # ── Input page handlers ───────────────────────────────────────────────

    def _on_version_changed(self, _entry) -> None:
        self._process_btn.set_sensitive(bool(self._version_entry.get_text().strip()))

    def _on_upload_toggled(self, switch, _param) -> None:
        if switch.get_active():
            self._process_btn.set_label(_("Generate & Upload"))
        else:
            self._process_btn.set_label(_("Generate Release Text"))

    def _on_process_clicked(self, _btn) -> None:
        version = self._version_entry.get_text().strip()
        if not version:
            return
        self._version = version
        forum_url = self._forum_url_entry.get_text().strip()
        self._forum_url = forum_url
        if forum_url:
            conf = cfg.load()
            conf.setdefault("forum_post_urls", {})[self._appid] = forum_url
            cfg.save(conf)

        items = [_item_from_sidecar(s, version) for s in self._group]
        do_upload = self._upload_switch.get_active()
        self._set_busy(True)
        conf = cfg.load()
        output_dir = Path(conf["output_dir"])
        mu_user = credentials.get_multiup_username() if do_upload else None
        mu_pass = credentials.get_multiup_password() if do_upload else None

        async def _process() -> None:
            for item in items:
                archive_path = output_dir / f"{item.archive_name}.7z"
                if not archive_path.exists():
                    log.warning("Archive not found: %s", archive_path)
                    continue
                if not item.file_hash:
                    self._progress_detail = _("Hashing") + f" {item.game_name} ({item.platform})"
                    GLib.idle_add(self._progress.set_fraction, 0.0)
                    item.file_hash = await asyncio.to_thread(
                        hashing.blake3_hex,
                        archive_path,
                        lambda pct, speed: GLib.idle_add(self._set_progress, pct, speed),
                    )
                if do_upload:
                    try:
                        user_id = None
                        if mu_user and mu_pass:
                            user_id = await asyncio.to_thread(multiup_api.login, mu_user, mu_pass)
                        tracker = SpeedTracker()
                        self._progress_detail = (
                            _("Uploading") + f" {item.game_name} ({item.platform})"
                        )
                        GLib.idle_add(self._progress.set_fraction, 0.0)
                        result = await asyncio.to_thread(
                            multiup_api.upload_file,
                            file_path=archive_path,
                            user_id=user_id,
                            progress_cb=lambda sent, total: GLib.idle_add(
                                self._set_progress,
                                sent / total if total else 0.0,
                                tracker.update(sent),
                            ),
                        )
                        if isinstance(result, tuple):
                            item.url, item.delete_url = result
                        else:
                            item.url = result
                        log.info("Uploaded %s → %s", item.archive_name, item.url)
                    except Exception as exc:
                        log.error("Upload failed for %s: %s", item.archive_name, exc)

        def _done(_result, exc) -> None:
            if exc:
                log.error("Process task error: %s", exc)
            self._set_busy(False)
            self._finalize(items, do_upload)

        async_run(_process(), done_cb=_done)

    def _set_busy(self, busy: bool) -> None:
        do_upload = self._upload_switch.get_active()
        self._process_btn.set_sensitive(not busy)
        if busy:
            self._process_btn.set_label(_("Uploading…") if do_upload else _("Hashing…"))
        else:
            label = _("Generate & Upload") if do_upload else _("Generate Release Text")
            self._process_btn.set_label(label)
        self._version_entry.set_sensitive(not busy)
        self._upload_switch.set_sensitive(not busy)
        self._progress.set_visible(busy)
        self._progress_label.set_visible(busy)

    def _set_progress(self, fraction: float, speed: float) -> bool:
        self._progress.set_fraction(fraction)
        self._progress.set_text(f"{fraction * 100:.0f}%")
        if speed >= 1_000_000:
            speed_str = f"{speed / 1_000_000:.1f} MB/s"
        elif speed >= 1_000:
            speed_str = f"{speed / 1_000:.0f} KB/s"
        elif speed > 0:
            speed_str = f"{speed:.0f} B/s"
        else:
            speed_str = ""
        detail = self._progress_detail
        if speed_str:
            detail = f"{detail} · {speed_str}" if detail else speed_str
        self._progress_label.set_text(detail)
        return False

    # ── Finalize + result page ─────────────────────────────────────────────

    def _finalize(self, items: list[QueueItem], did_upload: bool = False) -> None:
        _order = {"win64": 0, "win32": 1, "lin64": 2, "lin32": 3, "macos": 4}
        items.sort(key=lambda i: _order.get(i.platform, 99))

        conf = cfg.load()
        output_dir = Path(items[0].output_dir) if items[0].output_dir else Path(conf["output_dir"])
        new_blocks: list[str] = []

        for item in items:
            txt = release_text.generate(item)
            txt_path = output_dir / f"{item.archive_name}.txt"
            try:
                txt_path.write_text(txt, encoding="utf-8")
            except OSError as exc:
                log.error("Failed to write release text for %s: %s", item.archive_name, exc)
            new_blocks.append(txt)

        _cache = cfg.forum_post_cache_path(self._appid)
        old_post = _cache.read_text(encoding="utf-8") if _cache.exists() else ""
        new_post = release_text.insert_new_release(old_post, new_blocks)

        safe_name = items[0].safe_name
        forum_path = output_dir / f"{safe_name}.ForumPost.Build.{self._build_id}.txt"
        try:
            forum_path.write_text(new_post, encoding="utf-8")
        except OSError as exc:
            log.error("Failed to write forum post: %s", exc)

        cfg.save_forum_post_cache(self._appid, new_post)

        if did_upload:
            game_dir = output_dir / safe_name
            game_dir.mkdir(exist_ok=True)
            for item in items:
                for ext in (".7z", ".txt"):
                    src = output_dir / f"{item.archive_name}{ext}"
                    if src.exists():
                        src.rename(game_dir / src.name)
                shutil.rmtree(output_dir / item.archive_name, ignore_errors=True)

        for sidecar in self._group:
            sidecar_path = Path(sidecar.get("_sidecar_path", ""))
            if sidecar_path.exists():
                try:
                    sidecar_path.unlink()
                except OSError as exc:
                    log.warning("Failed to remove sidecar %s: %s", sidecar_path, exc)

        self._on_processed()
        self._show_result(new_post)

    def _show_result(self, forum_post: str) -> None:
        self.set_title(_("Release Text"))
        self._result_buffer.set_text(forum_post)
        self._page_stack.set_visible_child_name("result")

    def _on_copy_clicked(self, _btn) -> None:
        version_text = f"{self._version} ({self._build_id})"

        text = (
            f"[url={self._forum_url}]Updated[/url] to "
            f"[url=https://steamdb.info/patchnotes/{self._build_id}/]{version_text}[/url]"
        )
        provider = Gdk.ContentProvider.new_for_bytes(
            "text/plain;charset=utf-8",
            GLib.Bytes.new(text.encode("utf-8")),
        )
        Gdk.Display.get_default().get_clipboard().set_content(provider)
        self._copy_btn.set_label(_("Copied!"))
        GLib.timeout_add(1500, self._reset_copy_btn)

    def _reset_copy_btn(self) -> bool:
        self._copy_btn.set_label(_("Copy Update Message"))
        return False

    def _on_copy_post_clicked(self, _btn) -> None:
        text = self._result_buffer.get_text(
            self._result_buffer.get_start_iter(),
            self._result_buffer.get_end_iter(),
            False,
        )
        provider = Gdk.ContentProvider.new_for_bytes(
            "text/plain;charset=utf-8",
            GLib.Bytes.new(text.encode("utf-8")),
        )
        Gdk.Display.get_default().get_clipboard().set_content(provider)
        self._copy_post_btn.set_label(_("Copied!"))
        GLib.timeout_add(1500, self._reset_copy_post_btn)

    def _reset_copy_post_btn(self) -> bool:
        self._copy_post_btn.set_label(_("Copy Forum Post"))
        return False
