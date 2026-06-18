"""Process Dialog - turn a daemon-downloaded archive into a release post."""

import asyncio
import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from gnusteampacker import config as cfg
from gnusteampacker import credentials, multiup_api, release_text
from gnusteampacker.async_runner import run as async_run
from gnusteampacker.i18n import _
from gnusteampacker.queue_model import QueueItem

log = logging.getLogger(__name__)


def _forum_post_cache_path(appid: str) -> Path:
    return cfg.DATA_DIR / "forum_posts" / f"{appid}.txt"


def _load_cached_forum_post(appid: str) -> str:
    path = _forum_post_cache_path(appid)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _save_forum_post_cache(appid: str, content: str) -> None:
    path = _forum_post_cache_path(appid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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

        info_group = Adw.PreferencesGroup(title=_("Archive"))
        info_row = Adw.ActionRow(
            title=self._game_name,
            subtitle=f"Build {self._build_id} · {', '.join(self._platforms)} · {self._branch}",
        )
        info_group.add(info_row)
        box.append(info_group)

        options_group = Adw.PreferencesGroup()
        options_group.set_margin_top(16)

        self._version_entry = Adw.EntryRow(title=_("Version number (e.g. 1.3.5)"))
        self._version_entry.connect("changed", self._on_version_changed)
        options_group.add(self._version_entry)

        self._upload_switch = Adw.SwitchRow(
            title=_("Upload to multiup.io"),
            subtitle=_("Requires multiup.io credentials in Preferences"),
        )
        self._upload_switch.connect("notify::active", self._on_upload_toggled)
        options_group.add(self._upload_switch)

        box.append(options_group)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(20)
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

        self._copy_btn = Gtk.Button(label=_("Copy Forum Post"))
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

        items = [_item_from_sidecar(s, version) for s in self._group]

        if self._upload_switch.get_active():
            self._set_busy(True)
            conf = cfg.load()
            output_dir = Path(conf["output_dir"])
            mu_user = credentials.get_multiup_username()
            mu_pass = credentials.get_multiup_password()

            async def _upload() -> None:
                for item in items:
                    archive_path = output_dir / f"{item.archive_name}.7z"
                    if not archive_path.exists():
                        log.warning("Archive not found for upload: %s", archive_path)
                        continue
                    try:
                        user_id = None
                        if mu_user and mu_pass:
                            user_id = await asyncio.to_thread(multiup_api.login, mu_user, mu_pass)
                        result = await asyncio.to_thread(
                            multiup_api.upload_file,
                            file_path=archive_path,
                            user_id=user_id,
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
                    log.error("Upload task error: %s", exc)
                self._set_busy(False)
                self._finalize(items)

            async_run(_upload(), done_cb=_done)
        else:
            self._finalize(items)

    def _set_busy(self, busy: bool) -> None:
        self._process_btn.set_sensitive(not busy)
        self._process_btn.set_label(_("Uploading…") if busy else _("Generate & Upload"))
        self._version_entry.set_sensitive(not busy)
        self._upload_switch.set_sensitive(not busy)

    # ── Finalize + result page ─────────────────────────────────────────────

    def _finalize(self, items: list[QueueItem]) -> None:
        conf = cfg.load()
        output_dir = Path(conf["output_dir"])
        new_blocks: list[str] = []

        for item in items:
            txt = release_text.generate(item)
            txt_path = output_dir / f"{item.archive_name}.txt"
            try:
                txt_path.write_text(txt, encoding="utf-8")
            except OSError as exc:
                log.error("Failed to write release text for %s: %s", item.archive_name, exc)
            new_blocks.append(txt)

        old_post = _load_cached_forum_post(self._appid)
        new_post = release_text.insert_new_release(old_post, new_blocks)

        safe_name = self._game_name.replace(" ", ".").replace(":", "").replace("/", "_")
        forum_path = output_dir / f"{safe_name}.ForumPost.Build.{self._build_id}.txt"
        try:
            forum_path.write_text(new_post, encoding="utf-8")
        except OSError as exc:
            log.error("Failed to write forum post: %s", exc)

        _save_forum_post_cache(self._appid, new_post)

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
        self._copy_btn.set_label(_("Copied!"))
        GLib.timeout_add(1500, self._reset_copy_btn)

    def _reset_copy_btn(self) -> bool:
        self._copy_btn.set_label(_("Copy Forum Post"))
        return False
