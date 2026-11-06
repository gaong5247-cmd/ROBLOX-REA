"""Deterministic, read-only reconstruction diagnosis for Studio-authorized maps.

The output is a *proposal*, not executable code. Only the Studio plugin can
apply its constrained subset, after displaying the plan and requiring approval.
Unknown geometry, scripts, Terrain and permission-protected assets remain
explicitly unrepairable from JSON evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .references import REFERENCE_FIELDS, reference_paths
from .schema import validate_scene

REPAIR_SCHEMA = "roblox-rea.repair-plan.v1"
MAX_OPERATIONS = 100

# Only properties whose assignment semantics are implemented in the Studio
# plugin and can be checked against a captured source are proposed for edits.
PART_PROPERTIES = {
    "size", "cframe", "color", "material", "transparency", "reflectance",
    "anchored", "can_collide", "can_touch", "can_query", "cast_shadow", "shape",
}
OTHER_PROPERTIES = {
    "Decal": {"texture", "transparency", "face", "color"},
    "Texture": {"texture", "transparency", "face", "color", "studs_per_tile_u", "studs_per_tile_v"},
    "Attachment": {"local_cframe", "visible"},
    "SpecialMesh": {"mesh_id", "texture_id", "mesh_type", "scale", "offset"},
    "PointLight": {"brightness", "color", "enabled", "shadows", "range"},
    "SpotLight": {"brightness", "color", "enabled", "shadows", "range", "angle", "face"},
    "SurfaceLight": {"brightness", "color", "enabled", "shadows", "angle", "face"},
    "Sound": {"sound_id", "volume", "playback_speed", "looped", "rolloff_max_distance", "rolloff_min_distance"},
    "SurfaceAppearance": {"color_map", "metalness_map", "normal_map", "roughness_map"},
}
SAFE_CLASSES = {"Part", "WedgePart", "CornerWedgePart", "TrussPart", "Seat", "VehicleSeat", "SpawnLocation"}
# MeshPart and UnionOperation: generic BasePart properties are safe, but their
# actual geometry is only recoverable from native RBXM.
GEOMETRY_CLASSES = SAFE_CLASSES | {"MeshPart", "UnionOperation"}


def _fingerprint(scene: dict) -> str:
    """Content identity excluding unstable capture timestamps / transient IDs."""
    id_paths = {n["id"]: n.get("path", n["id"]) for n in scene["nodes"]}
    entries = [
        {"path": n.get("path", n["id"]), "class": n["class"], "name": n["name"],
         "properties": n.get("properties", {}), "attributes": n.get("attributes", {}),
         "tags": n.get("tags", []), "references": reference_paths(scene, n, id_paths),
         "external_references": n.get("external_references", [])}
        for n in scene["nodes"]
    ]
    entries.sort(key=lambda n: n["path"])
    data = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _value_supported(prop: str, value: Any) -> bool:
    if prop in {"size", "scale", "offset", "color", "cframe", "local_cframe"}:
        lengths = {"size": 3, "scale": 3, "offset": 3, "color": 3, "cframe": 12, "local_cframe": 12}
        if not isinstance(value, list) or len(value) != lengths[prop]:
            return False
        return all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e7 for v in value)
    if prop in {"anchored", "can_collide", "can_touch", "can_query", "cast_shadow", "enabled", "shadows", "visible", "looped"}:
        return type(value) is bool
    if prop in {"transparency", "reflectance", "brightness", "range", "angle", "volume", "playback_speed", "rolloff_max_distance", "rolloff_min_distance", "studs_per_tile_u", "studs_per_tile_v"}:
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1_000_000
    if prop in {"material", "shape", "face", "mesh_type"}:
        return isinstance(value, str) and 1 <= len(value) <= 60 and value.replace("_", "").isalnum()
    if prop in {"texture", "mesh_id", "texture_id", "sound_id", "color_map", "metalness_map", "normal_map", "roughness_map"}:
        return isinstance(value, str) and len(value) <= 400
    return False


def plan_repairs(reference: dict, current: dict, limit: int = MAX_OPERATIONS) -> dict:
    """Plan bounded, non-destructive property and intra-map reference repairs."""
    validate_scene(reference)
    validate_scene(current)
    if type(limit) is not int or not 1 <= limit <= MAX_OPERATIONS:
        raise ValueError(f"limit must be 1..{MAX_OPERATIONS}")
    a = {n.get("path", n["id"]): n for n in reference["nodes"]}
    b = {n.get("path", n["id"]): n for n in current["nodes"]}
    ref_ids = {n["id"]: n.get("path", n["id"]) for n in reference["nodes"]}
    cur_ids = {n["id"]: n.get("path", n["id"]) for n in current["nodes"]}
    operations: list[dict] = []
    blocked: list[dict] = []
    missing = sorted(set(a) - set(b))
    added = sorted(set(b) - set(a))
    blocked_total = 0

    def cannot(path: str, reason: str, detail: str = "") -> None:
        nonlocal blocked_total
        blocked_total += 1
        if len(blocked) < limit:
            blocked.append({"path": path, "reason": reason, "detail": detail})

    for path in missing:
        cannot(path, "missing_object", "Try hybrid stage with an authorized native RBXM; no guessed mesh/script creation")
    # Never delete additional user objects, even if missing from reference.
    for path in sorted(set(a) & set(b)):
        source, dest = a[path], b[path]
        if source["class"] != dest["class"]:
            cannot(path, "class_mismatch", source["class"] + " / " + dest["class"])
            continue
        cls = source["class"]
        allowed = PART_PROPERTIES if cls in GEOMETRY_CLASSES else OTHER_PROPERTIES.get(cls, set())
        sp, dp = source.get("properties", {}), dest.get("properties", {})
        for key in sorted(sp):
            if key in dp and sp[key] == dp[key]:
                continue
            if key not in allowed or not _value_supported(key, sp[key]):
                cannot(path, "unsupported_property", key)
                continue
            if len(operations) >= limit:
                cannot(path, "plan_limit", key)
                continue
            operations.append({
                "op": "set_property", "path": path, "class": cls, "property": key,
                "expected": dp.get(key), "expected_present": key in dp,
                "value": sp[key],
            })
        src_links = reference_paths(reference, source, ref_ids)
        dst_links = reference_paths(current, dest, cur_ids)
        for field, target_path in sorted(src_links.items()):
            if dst_links.get(field) == target_path:
                continue
            if target_path not in b or a[target_path]["class"] != b[target_path]["class"]:
                cannot(path, "missing_reference_target", field + " -> " + target_path)
                continue
            if cls not in REFERENCE_FIELDS or field not in REFERENCE_FIELDS[cls]:
                cannot(path, "unsupported_reference", field)
                continue
            if len(operations) >= limit:
                cannot(path, "plan_limit", field)
                continue
            operations.append({
                "op": "set_reference", "path": path, "class": cls, "property": field,
                "expected_path": dst_links.get(field), "target_path": target_path,
            })
        # Metadata changes and reference removals aren't silently applied.
        for category in ("attributes", "tags"):
            if source.get(category, {} if category == "attributes" else []) != dest.get(category, {} if category == "attributes" else []):
                cannot(path, "manual_metadata_review", category)
        for field in sorted(set(dst_links) - set(src_links)):
            cannot(path, "manual_reference_removal", field)
    source_hash, target_hash = _fingerprint(reference), _fingerprint(current)
    payload = {"schema": REPAIR_SCHEMA, "source_hash": source_hash, "target_hash": target_hash,
               "operations": operations, "blocked_total": blocked_total, "missing": missing, "extra": added}
    plan_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        **payload,
        "plan_id": plan_hash,
        "counts": {"planned": len(operations), "blocked": blocked_total,
                   "missing": len(missing), "extra_preserved": len(added)},
        "blocked": blocked,
        "truncated": len(operations) >= limit or blocked_total > len(blocked),
        "safety": "PREVIEW ONLY. Studio requires typed approval, validates a fresh plan ID, records Undo and stages hybrids in ServerStorage. No scripts or Terrain edits.",
    }
