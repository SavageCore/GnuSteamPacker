"""Headless CLI: `gnusteampacker pack <appid> [options]`."""

import argparse
import asyncio
import logging
import os
import sys
import webbrowser
from pathlib import Path

from gnusteampacker import config as cfg
from gnusteampacker import credentials, release_text, worker
from gnusteampacker.queue_model import QueueItem, Status
from gnusteampacker.steam_api import PLATFORM_STEAMCMD


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


def _make_update_cb(platform: str) -> worker.UpdateCB:
    state = {"in_progress_line": False}

    def update_cb(item: QueueItem) -> None:
        if item.status in (Status.DOWNLOADING, Status.COMPRESSING):
            pct = int(item.progress * 100)
            print(f"\r[{platform}] {item.status.display_name} {pct:3d}%", end="", flush=True)
            state["in_progress_line"] = True
        else:
            prefix = "\n" if state["in_progress_line"] else ""
            print(f"{prefix}[{platform}] {item.status.display_name}")
            state["in_progress_line"] = False

    return update_cb


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

        update_cb = _make_update_cb(item.platform)
        await worker.process_item(
            item,
            update_cb,
            auth_override=per_item_auth,
            upload=args.upload,
            multiup_user=args.multiup_user,
            multiup_pass=args.multiup_pass,
        )

        if item.status == Status.STEAMGUARD:
            code = input(f"\n[{item.platform}] Steam Guard code required: ").strip()
            item.status = Status.READY
            item.progress = 0.0
            item.error_detail = ""
            await worker.process_item(
                item,
                update_cb,
                steam_guard_code=code,
                upload=args.upload,
                multiup_user=args.multiup_user,
                multiup_pass=args.multiup_pass,
            )

        if item.status == Status.BADLOGIN:
            break


def _print_summary(items: list[QueueItem], conf: dict, upload: bool) -> None:
    output_dir = Path(conf["output_dir"])

    print("\n" + "=" * 60)
    if len(items) == 1:
        print(f"Platform {items[0].platform} complete.")
    else:
        print("All platforms complete.")
    print("=" * 60)

    if not upload:
        print("\nUpload these .7z files to multiup.io:")
        for item in items:
            print(f"  {output_dir / f'{item.archive_name}.7z'}")


def _resolve_forum_post_url(appid: str, args: argparse.Namespace, conf: dict) -> str:
    cache = dict(conf.get("forum_post_urls", {}))
    if args.forum_post_url:
        url = args.forum_post_url
    elif appid in cache:
        url = cache[appid]
        print(f"\nUsing cached forum post URL: {url}")
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
            print(f"\n[WARNING: {txt_path} not found, skipping forum post generation]")
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
        print("\nSteamDB patch notes URL unavailable (no build ID found).")
        return

    patchnotes_url = f"https://steamdb.info/patchnotes/{build_id}/"

    print("\nForum reply:")
    print(f"  SteamDB patch notes: {patchnotes_url}")
    print(f"  [url={forum_url}]Updated[/url] to [url={patchnotes_url}]{version}[/url]")


def _print_multiup_delete_instructions(items: list[QueueItem]) -> None:
    print("\nTo delete the uploaded files from multiup.io, use these links:")
    for item in items:
        if item.delete_url:
            print(f"  [{item.platform}] {item.delete_url}")


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
        print("\nFAILED:")
        for item in failed:
            if item.status == Status.READY:
                print(f"  [{item.platform}] not attempted (earlier platform failed)")
            else:
                print(f"  [{item.platform}] {item.status.display_name}: {item.error_detail}")
        return 1

    conf = cfg.load()
    _print_summary(items, conf, args.upload)

    forum_url = _resolve_forum_post_url(args.appid, args, conf)
    version = _resolve_version(args, items)

    forum_post_path = _write_forum_post(items, conf, args)
    if forum_post_path:
        print(f"\nNew forum post written to: {forum_post_path}")
        print("Review it, then paste the contents into the release thread.")

    _print_steamdb_reply(items, forum_url, version)

    if args.upload:
        _print_multiup_delete_instructions(items)

    return 0
