"""Generate cs.rin.ru-compatible BBCode release text."""

from gnusteampacker.queue_model import QueueItem


def generate(item: QueueItem) -> str:
    platform_label = item.platform.capitalize()
    branch = (item.branch or "public").capitalize()
    build_id = item.build_id or "unknown"
    build_time = item.build_time or "unknown"

    depot_block = "\n".join(item.depot_list) if item.depot_list else "(no depot info)"

    return (
        f"[url=][color=white][b]{item.game_name} [{platform_label}]"
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


def build_depot_list(
    game_info: dict,
    depot_names: dict[str, str],
    branch: str = "public",
    manifest_overrides: dict[str, str] | None = None,
) -> list[str]:
    lines: list[str] = []
    for depot_id, depot_data in game_info.get("depots", {}).items():
        name = depot_data.get("name") or depot_names.get(depot_id, "")
        if manifest_overrides and depot_id in manifest_overrides:
            manifest_id = manifest_overrides[depot_id]
        else:
            manifests = depot_data.get("manifests", {})
            manifest_id = manifests.get(branch) or manifests.get("public") or "unknown"
        label = f"{depot_id} - {name}" if name else depot_id
        lines.append(f"{label} [Manifest {manifest_id}]")
    return lines
