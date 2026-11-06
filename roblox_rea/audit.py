"""Report what a JSON scan can and cannot faithfully reconstruct."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .schema import validate_scene

# Keep this list in sync with the Studio plugin's ALLOWED reconstruction list.
SUPPORTED = frozenset({
    "Model", "Folder", "Part", "WedgePart", "CornerWedgePart", "TrussPart",
    "Seat", "VehicleSeat", "SpawnLocation", "Decal", "Texture", "SpecialMesh",
    "Attachment", "MeshPart", "UnionOperation", "PointLight", "SpotLight",
    "SurfaceLight", "Sound", "SurfaceAppearance",
})
PLACEHOLDER_CLASSES = frozenset({"MeshPart", "UnionOperation"})
GEOMETRY = frozenset({
    "Part", "WedgePart", "CornerWedgePart", "TrussPart", "Seat", "VehicleSeat",
    "SpawnLocation", "MeshPart", "UnionOperation",
})
ASSET_KEYS = frozenset({"mesh_id", "texture_id", "texture", "sound_id",
                        "color_map", "metalness_map", "normal_map", "roughness_map"})


def audit_reconstruction(scene: dict, limit: int = 50) -> dict[str, Any]:
    validate_scene(scene)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    unsupported = Counter()
    placeholders = Counter()
    missing_transforms = []
    assets = []
    for node in scene["nodes"]:
        kind = node["class"]
        p = node.get("properties", {})
        path = node.get("path", node["id"])
        if kind not in SUPPORTED:
            unsupported[kind] += 1
        elif kind in PLACEHOLDER_CLASSES:
            placeholders[kind] += 1
        if kind in GEOMETRY and ("cframe" not in p or "size" not in p):
            missing_transforms.append(path)
        for key in ASSET_KEYS:
            value = p.get(key)
            if isinstance(value, str) and value:
                assets.append({"path": path, "property": key, "reference": value})
    assets.sort(key=lambda obj: (obj["path"], obj["property"]))
    issues = []
    if unsupported:
        issues.append("Unsupported classes are omitted by JSON reconstruction; descendants may be reparented to the closest supported ancestor.")
    if placeholders:
        issues.append("MeshPart/UnionOperation are placeholder Parts in JSON reconstruction; use native RBXM for their original shapes.")
    if missing_transforms:
        issues.append("Some geometry lacks size or transform information in the scan.")
    issues += [
        "JSON reconstruction never restores script source, execution or Terrain voxels.",
        "Asset references do not guarantee access to the underlying Roblox assets.",
        "Studio tags and supported typed attributes are preserved in JSON; unsupported attribute types are skipped.",
        "Use Studio-native RBXM backup/restore for highest available fidelity.",
    ]
    return {
        "scene_name": scene["scene_name"],
        "node_count": len(scene["nodes"]),
        "supported_nodes": sum(n["class"] in SUPPORTED for n in scene["nodes"]),
        "unsupported_classes": dict(unsupported.most_common()),
        "placeholder_classes": dict(placeholders.most_common()),
        "missing_geometry_properties": {"count": len(missing_transforms), "paths": missing_transforms[:limit]},
        "asset_references": {"count": len(assets), "items": assets[:limit]},
        "truncated": len(missing_transforms) > limit or len(assets) > limit,
        "limitations": issues,
    }
