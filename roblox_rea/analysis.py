"""Deterministic, evidence-based analysis for Studio scene captures."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .schema import validate_scene


def _bbox(nodes: list[dict]) -> dict | None:
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    parts = 0
    for node in nodes:
        p = node.get("properties", {})
        size, cf = p.get("size"), p.get("cframe")
        if size is None or cf is None:
            continue
        # Roblox CFrame:GetComponents() -> xyz + row-major 3x3 rotation.
        half = [abs(n) / 2 for n in size]
        radius = [sum(abs(cf[3 + i * 3 + j]) * half[j] for j in range(3)) for i in range(3)]
        for axis in range(3):
            low[axis] = min(low[axis], cf[axis] - radius[axis])
            high[axis] = max(high[axis], cf[axis] + radius[axis])
        parts += 1
    if not parts:
        return None
    return {
        "min": [round(v, 4) for v in low],
        "max": [round(v, 4) for v in high],
        "dimensions": [round(high[i] - low[i], 4) for i in range(3)],
        "parts_counted": parts,
        "note": "Axis-aligned bounds from Part sizes and CFrames; Mesh/CSG details not inspected.",
    }


def analyze_scene(scene: dict) -> dict[str, Any]:
    scene = validate_scene(scene)
    nodes = scene["nodes"]
    classes = Counter(node["class"] for node in nodes)
    materials = Counter(
        str(node["properties"]["material"])
        for node in nodes
        if "material" in node.get("properties", {})
    )
    collidable = sum(node.get("properties", {}).get("can_collide") is True for node in nodes)
    anchored = sum(node.get("properties", {}).get("anchored") is True for node in nodes)
    return {
        "scene_name": scene["scene_name"],
        "capture_id": scene.get("capture_id"),
        "node_count": len(nodes),
        "class_counts": dict(classes.most_common()),
        "material_counts": dict(materials.most_common()),
        "collidable_parts": collidable,
        "anchored_parts": anchored,
        "bounding_box": _bbox(nodes),
        "limitations": [
            "JSON captures do not encode scripts, physical terrain voxels, or full binary mesh geometry.",
            "For faithful Studio-owned instance copies, use native RBXM roundtrips instead.",
        ],
    }


def _keyed(scene: dict) -> dict[str, dict]:
    return {node.get("path") or node["id"]: node for node in scene["nodes"]}


def compare_scenes(before: dict, after: dict, limit: int = 50) -> dict:
    validate_scene(before)
    validate_scene(after)
    a = _keyed(before)
    b = _keyed(after)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    modified = sorted(
        k for k in set(a) & set(b)
        if a[k]["class"] != b[k]["class"] or a[k].get("properties", {}) != b[k].get("properties", {})
    )
    return {
        "before": before.get("capture_id", before["scene_name"]),
        "after": after.get("capture_id", after["scene_name"]),
        "counts": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "added": added[:limit],
        "removed": removed[:limit],
        "modified": modified[:limit],
        "truncated": any(len(x) > limit for x in (added, removed, modified)),
        "matching_rule": "stable hierarchy paths (renames appear as remove/add)",
    }


def find_nodes(scene: dict, query: str, limit: int = 30) -> list[dict]:
    validate_scene(scene)
    if not query or len(query) > 200:
        raise ValueError("query length must be between 1 and 200")
    needle = query.casefold()
    result: list[dict] = []
    for node in scene["nodes"]:
        if needle in " ".join((node["name"], node["class"], node.get("path", ""))).casefold():
            result.append(node)
            if len(result) >= min(max(limit, 1), 100):
                break
    return result
