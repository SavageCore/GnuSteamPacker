"""Generate cs.rin.ru-compatible BBCode release text."""

from gnusteampacker.queue_model import QueueItem

PREVIOUS_VERSION_SEPARATOR = "[color=gray]" + "▬" * 60 + "[/color]"


def _manifest_gid(manifests: dict, branch: str) -> str:
    entry = manifests.get(branch) or manifests.get("public")
    if isinstance(entry, dict):
        return str(entry.get("gid", "unknown"))
    return str(entry or "unknown")


def generate(item: QueueItem) -> str:
    _plat_labels = {
        "win64": "Win64",
        "win32": "Win32",
        "lin64": "Linux64",
        "lin32": "Linux32",
        "macos": "MacOS",
    }
    platform_label = _plat_labels.get(item.platform, item.platform.capitalize())
    branch = (item.branch or "public").capitalize()
    build_id = item.build_id or "unknown"
    build_time = item.build_time or "unknown"

    depot_block = "\n".join(item.depot_list) if item.depot_list else "(no depot info)"
    file_hash = item.file_hash or "unknown"
    game_version = item.game_version or "unknown"
    launch_options_url = f"https://steamdb.info/app/{item.appid}/config/"
    changelog_url = f"https://steamdb.info/patchnotes/{build_id}/"

    return (
        f"[color=white][b]{item.game_name} [{platform_label}]"
        f" [Branch: {branch}] (Clean Steam Files)[/b][/color]\n"
        f" [url={item.url}]{item.archive_name}.7z[/url]\n"
        f"[size=100][color=white][b]Version:[/b]"
        f" [i]{game_version} ({build_time} - Build {build_id})[/i][/color][/size]"
        f"[color=#FFFFFF] | [/color][url={launch_options_url}]Launch Options[/url]"
        f"[color=#FFFFFF] | [/color][url={changelog_url}]Changelog[/url]\n"
        f"\n"
        f'[spoiler="[color=white]Depots, Manifests, & BLAKE3 Hashes[/color]"][code=text]'
        f"{depot_block}\n"
        f"\n"
        f"Hash:\n"
        f"{file_hash}  {item.archive_name}.7z"
        f"[/code][/spoiler]"
        f"[color=white][b]Uploaded version:[/b]"
        f" [i]{build_time} [Build {build_id}][/i][/color]"
    )


def insert_new_release(old_post: str, new_blocks: list[str]) -> str:
    """Move the current release blocks of ``old_post`` into "Previous Versions"
    and insert ``new_blocks`` (per-platform release text, in display order) at the top.

    ``old_post`` is expected to start directly with the current release blocks
    (no header content), matching the format produced by this same function.
    """
    marker = "[b]Previous Versions:[/b]"
    idx = old_post.find(marker)
    if idx == -1:
        moved = old_post.strip()
    else:
        current_section = old_post[:idx].rstrip()
        rest = old_post[idx + len(marker) :]
        spoiler_start = rest.find("[spoiler]")
        if spoiler_start == -1:
            moved = current_section
        else:
            inner_start = spoiler_start + len("[spoiler]")
            spoiler_end = rest.rfind("[/spoiler]")
            previous_content = rest[inner_start:spoiler_end].strip()
            if previous_content:
                moved = f"{current_section}\n\n{PREVIOUS_VERSION_SEPARATOR}\n\n{previous_content}"
            else:
                moved = current_section

    new_section = "\n\n".join(new_blocks)
    return f"{new_section}\n\n[b]Previous Versions:[/b]\n\n[spoiler]{moved}[/spoiler]"


def build_depot_list(
    game_info: dict,
    depot_names: dict[str, str],
    branch: str = "public",
    manifest_overrides: dict[str, str] | None = None,
) -> list[str]:
    lines: list[str] = []
    depots = game_info.get("depots", {})
    depot_iter = (
        [(depot_id, depots.get(depot_id, {})) for depot_id in manifest_overrides]
        if manifest_overrides
        else list(depots.items())
    )
    for depot_id, depot_data in depot_iter:
        if not depot_id.isdigit():
            continue
        if manifest_overrides is not None and depot_id not in manifest_overrides:
            continue
        name = depot_data.get("name") or depot_names.get(depot_id, "")
        if manifest_overrides and depot_id in manifest_overrides:
            manifest_id = manifest_overrides[depot_id]
        else:
            manifests = depot_data.get("manifests", {})
            manifest_id = _manifest_gid(manifests, branch)
        label = f"{depot_id} - {name}" if name else depot_id
        lines.append(f"{label} [Manifest {manifest_id}]")
    return lines
