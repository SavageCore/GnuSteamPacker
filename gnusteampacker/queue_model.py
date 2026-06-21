from dataclasses import dataclass, field
from enum import StrEnum

from gnusteampacker.i18n import _


class Status(StrEnum):
    READY = "Ready"
    GETINFO = "Fetching info…"
    AUTHENTICATING = "Authenticating…"
    DOWNLOADING = "Downloading"
    CLEANING = "Cleaning"
    COMPRESSING = "Compressing"
    HASHING = "Computing hash"
    COMPLETE = "Complete"
    FAIL = "Failed"
    BADLOGIN = "Bad login"
    RATELIMITED = "Rate limited"
    STEAMGUARD = "Steam Guard needed"
    NOSUB = "No subscription"
    SKIPPED = "Skipped"
    UPLOADING = "Uploading"

    @property
    def display_name(self) -> str:
        return _(self.value)


@dataclass
class QueueItem:
    appid: str
    game_name: str
    platform: str  # "win64" | "win32" | "lin64" | "lin32" | "macos"
    branch: str  # "public" | custom name
    branch_password: str  # "" if none
    status: Status = Status.READY
    progress: float = 0.0  # 0.0–1.0
    build_id: str = ""
    build_time: str = ""
    game_version: str = ""
    url: str = ""
    upload_url: str = ""
    delete_url: str = ""
    depot_list: list[str] = field(default_factory=list)
    available_platforms: list[str] = field(default_factory=list)  # e.g. ["Windows", "Linux"]
    file_hash: str = ""
    error_detail: str = ""
    speed: float = 0.0  # bytes/sec, 0.0 = unknown/idle
    from_daemon: bool = False  # queued by watch mode; writes sidecar instead of release text
    output_dir: str = ""  # "" = use global config output_dir

    @property
    def display_speed(self) -> str:
        if self.speed >= 1_000_000:
            return f"{self.speed / 1_000_000:.1f} MB/s"
        if self.speed >= 1_000:
            return f"{self.speed / 1_000:.0f} KB/s"
        if self.speed <= 0:
            return ""
        return f"{self.speed:.0f} B/s"

    @property
    def display_platform(self) -> str:
        labels = {
            "win64": _("Windows 64-bit"),
            "win32": _("Windows 32-bit"),
            "lin64": _("Linux 64-bit"),
            "lin32": _("Linux 32-bit"),
            "macos": _("macOS"),
        }
        return labels.get(self.platform, self.platform)

    @property
    def safe_name(self) -> str:
        return self.game_name.replace(" ", ".").replace(":", "").replace("/", "_")

    @property
    def archive_name(self) -> str:
        _plat_labels = {
            "win64": "Win64",
            "win32": "Win32",
            "lin64": "Linux64",
            "lin32": "Linux32",
            "macos": "MacOS",
        }
        plat = _plat_labels.get(self.platform, self.platform.capitalize())
        branch = self.branch.capitalize() or "Public"
        build = self.build_id or "0"
        return f"{self.safe_name}.Build.{build}.{plat}.{branch}"

    def is_terminal(self) -> bool:
        return self.status in (
            Status.COMPLETE,
            Status.FAIL,
            Status.BADLOGIN,
            Status.RATELIMITED,
            Status.NOSUB,
            Status.SKIPPED,
        )

    def is_retryable(self) -> bool:
        return self.status in (
            Status.FAIL,
            Status.STEAMGUARD,
            Status.BADLOGIN,
            Status.RATELIMITED,
        )
