import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from gnusteampacker.queue_model import QueueItem, Status


class QueueRow(Adw.ActionRow):
    def __init__(self, item: QueueItem, remove_cb, retry_cb):
        super().__init__()
        self._item = item
        self._remove_cb = remove_cb
        self._retry_cb = retry_cb

        self.set_title(item.game_name or f"AppID {item.appid}")
        branch = item.branch or "public"
        self.set_subtitle(f"AppID: {item.appid}  ·  {item.display_platform}  ·  Branch: {branch}")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)

        self._status_label = Gtk.Label(label=item.status.value)
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
        self._retry_btn.set_tooltip_text("Retry")
        self._retry_btn.set_visible(False)
        self._retry_btn.connect("clicked", lambda _: retry_cb(item))
        self._btn_box.append(self._retry_btn)

        self._remove_btn = Gtk.Button()
        self._remove_btn.set_icon_name("user-trash-symbolic")
        self._remove_btn.add_css_class("flat")
        self._remove_btn.set_tooltip_text("Remove")
        self._remove_btn.connect("clicked", lambda _: remove_cb(item))
        self._btn_box.append(self._remove_btn)

        box.append(self._btn_box)
        self.add_suffix(box)

    def update(self, item: QueueItem) -> None:
        self._item = item
        self.set_title(item.game_name or f"AppID {item.appid}")
        self._status_label.set_text(item.status.value)

        downloading = item.status == Status.DOWNLOADING
        compressing = item.status == Status.COMPRESSING
        self._progress.set_visible(downloading or compressing)
        if downloading or compressing:
            if item.progress > 0:
                self._progress.set_fraction(item.progress)
            else:
                self._progress.pulse()

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
