import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from gnusteampacker.i18n import _
from gnusteampacker.queue_model import QueueItem, Status

# Progress-bar animation: how often to ease the displayed fraction toward the
# latest real value, and how much of the remaining gap to close per tick.
# SteamCMD/7z often report progress in large, irregular jumps; easing between
# them makes the bar appear to move smoothly instead of "stepping".
_ANIM_INTERVAL_MS = 66
_ANIM_EASE = 0.15


class QueueRow(Adw.ActionRow):
    def __init__(self, item: QueueItem, remove_cb, retry_cb):
        super().__init__()
        self._item = item
        self._remove_cb = remove_cb
        self._retry_cb = retry_cb

        self.set_title(item.game_name or _("AppID {appid}").format(appid=item.appid))
        self.set_subtitle(self._build_subtitle(item))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)

        self._status_label = Gtk.Label(label=item.status.display_name)
        self._status_label.add_css_class("caption")
        self._status_label.set_xalign(1)
        box.append(self._status_label)

        self._progress = Gtk.ProgressBar()
        self._progress.set_size_request(120, -1)
        self._progress.set_visible(False)
        box.append(self._progress)

        self._btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._btn_box.set_halign(Gtk.Align.END)

        self._retry_btn = Gtk.Button()
        self._retry_btn.set_icon_name("view-refresh-symbolic")
        self._retry_btn.add_css_class("flat")
        self._retry_btn.set_tooltip_text(_("Retry"))
        self._retry_btn.set_visible(False)
        self._retry_btn.connect("clicked", lambda _btn: retry_cb(item))
        self._btn_box.append(self._retry_btn)

        self._remove_btn = Gtk.Button()
        self._remove_btn.set_icon_name("user-trash-symbolic")
        self._remove_btn.add_css_class("flat")
        self._remove_btn.set_tooltip_text(_("Remove"))
        self._remove_btn.connect("clicked", lambda _btn: remove_cb(item))
        self._btn_box.append(self._remove_btn)

        box.append(self._btn_box)
        self.add_suffix(box)

        self._display_progress = 0.0
        self._target_progress = 0.0
        self._last_progress_status: Status | None = None
        self._anim_source_id: int | None = None
        self.connect("destroy", self._on_destroy)

    def _on_destroy(self, _widget: Gtk.Widget) -> None:
        if self._anim_source_id is not None:
            GLib.source_remove(self._anim_source_id)
            self._anim_source_id = None

    def _on_animate_tick(self) -> bool:
        diff = self._target_progress - self._display_progress
        if abs(diff) < 0.0005:
            self._display_progress = self._target_progress
        else:
            self._display_progress += diff * _ANIM_EASE
        if self._display_progress > 0:
            self._progress.set_fraction(self._display_progress)
        else:
            self._progress.pulse()
        return GLib.SOURCE_CONTINUE

    def update(self, item: QueueItem) -> None:
        self._item = item
        self.set_title(item.game_name or _("AppID {appid}").format(appid=item.appid))
        self.set_subtitle(self._build_subtitle(item))
        self.set_tooltip_text(item.error_detail or None)

        in_progress = item.status in (Status.DOWNLOADING, Status.COMPRESSING, Status.UPLOADING)
        if in_progress and item.display_speed:
            self._status_label.set_text(f"{item.status.display_name} · {item.display_speed}")
        else:
            self._status_label.set_text(item.status.display_name)
        self._progress.set_visible(in_progress)
        if in_progress:
            if item.status != self._last_progress_status:
                # New phase: snap back to 0% rather than animating down from
                # the previous phase's progress.
                self._display_progress = 0.0
                self._last_progress_status = item.status
            self._target_progress = item.progress
            if self._anim_source_id is None:
                self._anim_source_id = GLib.timeout_add(_ANIM_INTERVAL_MS, self._on_animate_tick)
        else:
            if self._anim_source_id is not None:
                GLib.source_remove(self._anim_source_id)
                self._anim_source_id = None
            self._display_progress = 0.0
            self._last_progress_status = None

        self._retry_btn.set_visible(item.is_retryable())
        self._remove_btn.set_sensitive(item.status == Status.READY or item.is_terminal())

        for cls in ("success", "error", "warning"):
            self._status_label.remove_css_class(cls)
        if item.status == Status.COMPLETE:
            self._status_label.add_css_class("success")
        elif item.status in (Status.FAIL, Status.BADLOGIN, Status.NOSUB, Status.RATELIMITED):
            self._status_label.add_css_class("error")
        elif item.status == Status.STEAMGUARD:
            self._status_label.add_css_class("warning")

    def _build_subtitle(self, item: QueueItem) -> str:
        branch = (item.branch or "public").capitalize()
        subtitle = _("AppID: {appid}  ·  {platform}  ·  Branch: {branch}").format(
            appid=item.appid, platform=item.display_platform, branch=branch
        )
        if item.error_detail and item.status in (
            Status.FAIL,
            Status.BADLOGIN,
            Status.RATELIMITED,
            Status.NOSUB,
            Status.AUTHENTICATING,
        ):
            subtitle = _("{subtitle}  ·  {detail}").format(
                subtitle=subtitle, detail=item.error_detail
            )
        return subtitle
