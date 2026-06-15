"""Headless CLI: `gnusteampacker pack <appid> [options]`."""

import argparse
import asyncio
import contextlib
import logging
import os
import sys
import webbrowser
from pathlib import Path

from rich.console import Console, RenderableType
from rich.live import Live
from rich.markup import escape
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from gnusteampacker import config as cfg
from gnusteampacker import credentials, release_text, worker
from gnusteampacker.queue_model import QueueItem, Status
from gnusteampacker.steam_api import PLATFORM_STEAMCMD

console = Console()

_PROGRESS_STATUSES = (Status.DOWNLOADING, Status.COMPRESSING, Status.UPLOADING, Status.HASHING)

# (icon, colour) used to finalize a status line when it transitions to a terminal state.
_TERMINAL_STYLES: dict[Status, tuple[str, str]] = {
    Status.COMPLETE: ("✔", "green"),
    Status.FAIL: ("✖", "red"),
    Status.BADLOGIN: ("✖", "red"),
    Status.NOSUB: ("✖", "red"),
    Status.RATELIMITED: ("✖", "red"),
    Status.STEAMGUARD: ("⚠", "yellow"),
    Status.SKIPPED: ("○", "dim"),
}

# (icon, colour) used to finalize a status line when moving on to the next phase.
_FINALIZE_STYLE = ("✔", "green")

# Progress-bar animation: how often to ease the displayed percentage toward
# the latest real value, and how much of the remaining gap to close per tick.
# SteamCMD/7z often report progress in large, irregular jumps; easing between
# them makes the bar appear to move smoothly instead of "stepping".
_ANIM_INTERVAL = 1 / 15
_ANIM_EASE = 0.15

# Per-platform colour for the "[platform]" label, so concurrent/sequential
# platform lines are easy to tell apart at a glance.
_PLATFORM_COLORS: dict[str, str] = {
    "win64": "cyan",
    "win32": "blue",
    "lin64": "magenta",
    "lin32": "bright_magenta",
    "macos": "yellow",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gnusteampacker pack",
        description="Headless download, clean, and package pipeline for one or more platforms.",
    )
    parser.add_argument("appid", help="Steam AppID, e.g. 1902940")
    parser.add_argument(
        "--platforms",
        default="win64,lin64",
        help="Comma-separated platform keys, e.g. win64,lin64 (default: win64,lin64)",
    )
    parser.add_argument("--branch", default="public", help="Steam branch (default: public)")
    parser.add_argument("--branch-password", default="", help="Password for a private branch")
    parser.add_argument(
        "--version",
        default="",
        help="Human version string for the forum reply, e.g. 1.3.5 (prompted if omitted)",
    )
    parser.add_argument(
        "--forum-post-url",
        default="",
        help="URL of the release post; cached per-appid (prompted on first use for an appid)",
    )
    parser.add_argument(
        "--forum-post-content",
        default="",
        help=(
            "Content of the release post (prompted if omitted; "
            "can be a path to a text file or pasted content)"
        ),
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't auto-open the SteamDB patch notes page in a browser",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload the packaged files",
    )
    parser.add_argument(
        "--multiup-user",
        default="",
        help="Username for multiup.io (optional)",
    )
    parser.add_argument(
        "--multiup-pass",
        default="",
        help="Password for multiup.io (optional)",
    )
    return parser


def _setup_cli_logging() -> None:
    conf = cfg.load()
    debug = bool(os.getenv("GNUSTEAMPACKER_DEBUG"))
    log_file = Path(conf["steamcmd_path"]).parent / "gnusteampacker.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        pass
    if debug:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def _platform_label(platform: str) -> Text:
    color = _PLATFORM_COLORS.get(platform, "cyan")
    return Text(f"[{platform}] ", style=color)


class _PlatformProgress:
    """Renders a live spinner/progress bar for one platform's pipeline run.

    Each time `item.status` changes, the previous status is finalized as a
    permanent line (preventing the duplicate lines that repeated pushes of
    the same status used to cause), and the new status is shown live via a
    spinner (indeterminate phases) or a progress bar (download/compress).
    """

    def __init__(self, platform: str, live: Live) -> None:
        self._platform = platform
        self._live = live
        self._color = _PLATFORM_COLORS.get(platform, "cyan")
        self._last_status: Status | None = None
        self._last_text = ""
        self._last_progress = 0.0
        self._item: QueueItem | None = None
        self._display_progress = 0.0
        self._target_progress = 0.0
        self._anim_task: asyncio.Task | None = None

    async def __aenter__(self) -> "_PlatformProgress":
        self._anim_task = asyncio.create_task(self._animate())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._anim_task:
            self._anim_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._anim_task

    async def _animate(self) -> None:
        while True:
            await asyncio.sleep(_ANIM_INTERVAL)
            if self._item is None or self._last_status not in _PROGRESS_STATUSES:
                continue
            diff = self._target_progress - self._display_progress
            if abs(diff) < 0.0005:
                self._display_progress = self._target_progress
            else:
                self._display_progress += diff * _ANIM_EASE
            self._live.update(self._render(self._item, self._display_progress))

    def _finalize(self, icon: str, color: str, text: str) -> None:
        line = _platform_label(self._platform)
        line.append(icon, style=color)
        line.append(f" {text}", style="white")
        self._live.console.print(line)

    def _print_build_id(self, build_id: str) -> None:
        line = _platform_label(self._platform)
        line.append(f"  Build {build_id}", style="white")
        self._live.console.print(line)

    def _render(self, item: QueueItem, display_progress: float) -> RenderableType:
        if item.status in _PROGRESS_STATUSES:
            pct = int(display_progress * 100)
            grid = Table.grid(padding=(0, 1))
            grid.add_column()
            grid.add_column()
            grid.add_column()
            grid.add_column(justify="right", width=4)
            grid.add_column()
            grid.add_row(
                _platform_label(self._platform),
                Text(item.status.display_name, style="white"),
                ProgressBar(total=100, completed=pct, width=30, complete_style=self._color),
                Text(f"{pct:3d}%", style="white"),
                Text(item.display_speed, style="white"),
            )
            return grid

        text = item.status.display_name
        if item.error_detail:
            text = f"{text} ({item.error_detail})"
        grid = Table.grid(padding=(0, 1))
        grid.add_column()
        grid.add_column()
        grid.add_column()
        grid.add_row(
            _platform_label(self._platform),
            Spinner("dots", style=self._color),
            Text(text, style="white"),
        )
        return grid

    def update(self, item: QueueItem) -> None:
        if item.status != self._last_status:
            if self._last_status is not None:
                # SteamCMD authenticates before it starts downloading, so the
                # worker's initial "Downloading 0%" placeholder is immediately
                # followed by "Authenticating…". Skip finalizing that
                # placeholder so it doesn't show up as a spurious, separate
                # "Downloading 100%" line.
                skip = (
                    self._last_status == Status.DOWNLOADING
                    and self._last_progress == 0.0
                    and item.status == Status.AUTHENTICATING
                )
                if not skip:
                    icon, color = _FINALIZE_STYLE
                    text = self._last_text
                    if self._last_status in _PROGRESS_STATUSES:
                        text = f"{self._last_status.display_name} 100%"
                    self._finalize(icon, color, text)
                    if self._last_status == Status.GETINFO and item.build_id:
                        self._print_build_id(item.build_id)
            self._last_status = item.status
            if item.status in _PROGRESS_STATUSES:
                # New phase: snap back to 0% rather than animating down from
                # the previous phase's progress.
                self._display_progress = 0.0
                self._target_progress = item.progress

        if item.status in _PROGRESS_STATUSES:
            self._last_progress = item.progress
            self._last_text = f"{item.status.display_name} {int(item.progress * 100):3d}%"
            self._target_progress = item.progress
        else:
            self._last_progress = 0.0
            self._last_text = item.status.display_name

        self._item = item

        if item.status in _TERMINAL_STYLES:
            icon, color = _TERMINAL_STYLES[item.status]
            self._finalize(icon, color, self._last_text)
            self._live.update("")
        else:
            self._live.update(self._render(item, self._display_progress))


async def _process_all(items: list[QueueItem], args: argparse.Namespace) -> None:
    conf = cfg.load()
    base_auth = credentials.build_auth_override(conf)
    remember_login = bool((base_auth or {}).get("remember_login", conf.get("remember_login", True)))
    username = (base_auth or {}).get("username", credentials.get_username()).strip()

    for idx, item in enumerate(items):
        per_item_auth = base_auth
        # Match SSP queue behavior: password is only passed for the first queued job.
        if idx > 0 and remember_login and username:
            per_item_auth = {
                "username": username,
                "password": "",
                "remember_login": remember_login,
            }

        with Live(console=console, transient=True, refresh_per_second=10) as live:
            async with _PlatformProgress(item.platform, live) as progress:
                await worker.process_item(
                    item,
                    progress.update,
                    auth_override=per_item_auth,
                    upload=args.upload,
                    multiup_user=args.multiup_user,
                    multiup_pass=args.multiup_pass,
                    compute_hash=True,
                )

        if item.status == Status.STEAMGUARD:
            code = input(f"\n{_platform_label(item.platform)}Steam Guard code required: ").strip()
            item.status = Status.READY
            item.progress = 0.0
            item.error_detail = ""
            with Live(console=console, transient=True, refresh_per_second=10) as live:
                async with _PlatformProgress(item.platform, live) as progress:
                    await worker.process_item(
                        item,
                        progress.update,
                        steam_guard_code=code,
                        upload=args.upload,
                        multiup_user=args.multiup_user,
                        multiup_pass=args.multiup_pass,
                        compute_hash=True,
                    )

        if item.status == Status.BADLOGIN:
            break


def _print_summary(items: list[QueueItem], conf: dict, upload: bool) -> None:
    output_dir = Path(conf["output_dir"])

    console.print("\n" + "=" * 60)
    if len(items) == 1:
        console.print(f"[bold green]Platform {items[0].platform} complete.[/bold green]")
    else:
        console.print("[bold green]All platforms complete.[/bold green]")
    console.print("=" * 60)

    if not upload:
        console.print("\n[bold white]Upload these .7z files to multiup.io:[/bold white]")
        for item in items:
            path = escape(str(output_dir / f"{item.archive_name}.7z"))
            console.print(f"  [cyan]{path}[/cyan]")


def _resolve_forum_post_url(appid: str, args: argparse.Namespace, conf: dict) -> str:
    cache = dict(conf.get("forum_post_urls", {}))
    if args.forum_post_url:
        url = args.forum_post_url
    elif appid in cache:
        url = cache[appid]
        console.print(f"\nUsing cached forum post URL: [cyan]{escape(url)}[/cyan]")
    else:
        url = input("\nForum post URL for this game (cached for next time): ").strip()

    cache[appid] = url
    conf["forum_post_urls"] = cache
    cfg.save(conf)
    return url


def _resolve_forum_post_content(args: argparse.Namespace) -> str:
    if not args.forum_post_content:
        return ""

    candidate = Path(args.forum_post_content).expanduser()
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return args.forum_post_content


def _resolve_version(args: argparse.Namespace, items: list[QueueItem]) -> str:
    if args.version:
        return args.version
    else:
        if not args.no_open:
            print("\nOpening SteamDB patch notes page so you can find the new version number...")
            webbrowser.open(f"https://steamdb.info/patchnotes/{items[0].build_id}")

        return input("New version number, e.g. 1.3.5: ").strip()


def _read_old_forum_post(args: argparse.Namespace) -> str:
    forum_post = _resolve_forum_post_content(args)
    if forum_post:
        return forum_post

    print("\nPaste the current forum post content, or enter a path to a file containing it.")
    print("For pasted content, finish with Ctrl+D.")
    first_line = input("> ")
    candidate = Path(first_line.strip()).expanduser()
    if first_line.strip() and candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return (first_line + "\n" + sys.stdin.read()).strip()


def _write_forum_post(items: list[QueueItem], conf: dict, args: argparse.Namespace) -> Path | None:
    output_dir = Path(conf["output_dir"])
    new_blocks = []
    for item in items:
        txt_path = output_dir / f"{item.archive_name}.txt"
        if not txt_path.exists():
            console.print(
                f"\n[bold red]WARNING:[/bold red] {escape(str(txt_path))} not found, "
                "skipping forum post generation"
            )
            return None
        new_blocks.append(txt_path.read_text(encoding="utf-8"))

    old_post = _read_old_forum_post(args)
    new_post = release_text.insert_new_release(old_post, new_blocks)

    safe_name = items[0].game_name.replace(" ", ".").replace(":", "").replace("/", "_")
    out_path = output_dir / f"{safe_name}.ForumPost.Build.{items[0].build_id}.txt"
    out_path.write_text(new_post, encoding="utf-8")
    return out_path


def _print_steamdb_reply(items: list[QueueItem], forum_url: str, version: str) -> None:
    build_id = items[0].build_id
    if not build_id:
        console.print("\nSteamDB patch notes URL unavailable (no build ID found).")
        return

    patchnotes_url = f"https://steamdb.info/patchnotes/{build_id}/"

    console.print("\n[bold white]Forum reply:[/bold white]")
    reply = f"  [url={forum_url}]Updated[/url] to [url={patchnotes_url}]{version}[/url]"
    console.print(Text(reply, style="white"))


def _print_multiup_delete_instructions(items: list[QueueItem]) -> None:
    console.print("\nTo delete the uploaded files from multiup.io, use these links:")
    for item in items:
        if item.delete_url:
            line = _platform_label(item.platform)
            line.append(f" {escape(item.delete_url)}", style="white")
            console.print(line)


def run_pack(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    invalid = [p for p in platforms if p not in PLATFORM_STEAMCMD]
    if invalid:
        parser.error(
            f"invalid platform(s): {', '.join(invalid)} (valid: {', '.join(PLATFORM_STEAMCMD)})"
        )
    if not platforms:
        parser.error("--platforms must list at least one platform")

    _setup_cli_logging()

    items = [
        QueueItem(
            appid=args.appid,
            game_name="",
            platform=p,
            branch=args.branch,
            branch_password=args.branch_password,
        )
        for p in platforms
    ]

    asyncio.run(_process_all(items, args))

    failed = [item for item in items if item.status != Status.COMPLETE]
    if failed:
        console.print("\n[bold red]FAILED:[/bold red]")
        for item in failed:
            label = _platform_label(item.platform)
            if item.status == Status.READY:
                console.print(f"  {label} not attempted (earlier platform failed)")
            else:
                detail = escape(item.error_detail)
                console.print(f"  {label} [red]{item.status.display_name}[/red]: {detail}")
        return 1

    conf = cfg.load()
    _print_summary(items, conf, args.upload)

    forum_url = _resolve_forum_post_url(args.appid, args, conf)
    version = _resolve_version(args, items)

    output_dir = Path(conf["output_dir"])
    for item in items:
        item.game_version = version
        txt_path = output_dir / f"{item.archive_name}.txt"
        txt_path.write_text(release_text.generate(item), encoding="utf-8")

    forum_post_path = _write_forum_post(items, conf, args)
    if forum_post_path:
        console.print(
            f"\n[bold white]New forum post written to:[/bold white] {escape(str(forum_post_path))}"
        )

    _print_steamdb_reply(items, forum_url, version)

    if args.upload:
        _print_multiup_delete_instructions(items)

    return 0
