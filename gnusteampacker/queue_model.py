from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    READY = "Ready"
    GETINFO = "Fetching info…"
    AUTHENTICATING = "Waiting for Steam Guard…"
    DOWNLOADING = "Downloading"
    CLEANING = "Cleaning"
    COMPRESSING = "Compressing"
    COMPLETE = "Complete"
    FAIL = "Failed"
    BADLOGIN = "Bad login"
    RATELIMITED = "Rate limited"
    STEAMGUARD = "Steam Guard needed"
    NOSUB = "No subscription"
    SKIPPED = "Skipped"


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
    depot_list: list[str] = field(default_factory=list)
    error_detail: str = ""

    @property
    def display_platform(self) -> str:
        labels = {
            "win64": "Windows 64-bit",
            "win32": "Windows 32-bit",
            "lin64": "Linux 64-bit",
            "lin32": "Linux 32-bit",
            "macos": "macOS",
        }
        return labels.get(self.platform, self.platform)

    @property
    def archive_name(self) -> str:
        safe = self.game_name.replace(" ", ".").replace(":", "").replace("/", "_")
        plat = self.platform.capitalize()
        branch = self.branch.capitalize() or "Public"
        build = self.build_id or "0"
        return f"{safe}.Build.{build}.{plat}.{branch}"

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
