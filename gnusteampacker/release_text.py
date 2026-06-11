"""Generate cs.rin.ru-compatible BBCode release text."""

from gnusteampacker.queue_model import QueueItem


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

    return (
        f"[url={item.url}][color=white][b]{item.game_name} [{platform_label}]"
        f" [Branch: {branch}] (Clean Steam Files)[/b][/color][/url]\n"
        f"[size=85][color=white][b]Version:[/b]"
        f" [i]{build_time} [Build {build_id}][/i][/color][/size]\n"
        f"\n"
        f'[spoiler="[color=white]Depots & Manifests[/color]"][code=text]'
        f"{depot_block}"
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
                moved = f"{current_section}\n\n{previous_content}"
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
