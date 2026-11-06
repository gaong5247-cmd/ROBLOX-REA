"""Geometry-only spatial queries over bounded, validated Studio snapshots.

CFrame is represented as x/y/z followed by a row-major 3x3 rotation matrix.
Distances use oriented part extents projected into world-aligned bounding boxes;
they are NOT collision-mesh distances or Roblox physics/navigation results.
"""

from __future__ import annotations

import math
from typing import Any

from .schema import validate_scene


def part_bounds(node: dict) -> tuple[list[float], list[float]] | None:
    """Return world-space AABB from serialized Size and CFrame, if present."""
    p = node.get("properties", {})
    size = p.get("size")
    cf = p.get("cframe")
    if size is None or cf is None:
        return None
    half = [abs(float(s)) / 2 for s in size]
    radii = [
        sum(abs(float(cf[3 + 3 * axis + col])) * half[col] for col in range(3))
        for axis in range(3)
    ]
    return (
        [float(cf[axis]) - radii[axis] for axis in range(3)],
        [float(cf[axis]) + radii[axis] for axis in range(3)],
    )


def _distance_to_box(point: tuple[float, float, float], bounds: tuple[list[float], list[float]]) -> float:
    lo, hi = bounds
    return math.sqrt(sum(max(lo[i] - point[i], 0.0, point[i] - hi[i]) ** 2 for i in range(3)))


def query_nearby(
    scene: dict,
    x: float,
    y: float,
    z: float,
    radius: float = 20.0,
    limit: int = 30,
    collidable_only: bool = False,
) -> dict[str, Any]:
    """Find objects whose *bounding boxes* intersect a sphere centered at (x,y,z)."""
    validate_scene(scene)
    values = (x, y, z, radius)
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in values):
        raise ValueError("query coordinates/radius must be finite numbers")
    if radius < 0 or radius > 1_000_000:
        raise ValueError("radius must be between 0 and 1,000,000 studs")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not isinstance(collidable_only, bool):
        raise ValueError("collidable_only must be a boolean")
    center = (float(x), float(y), float(z))
    matches = []
    scanned = 0
    for node in scene["nodes"]:
        properties = node.get("properties", {})
        if collidable_only and properties.get("can_collide") is not True:
            continue
        bounds = part_bounds(node)
        if bounds is None:
            continue
        scanned += 1
        distance = _distance_to_box(center, bounds)
        if distance <= radius:
            matches.append({
                "id": node["id"],
                "path": node.get("path", node["id"]),
                "name": node["name"],
                "class": node["class"],
                "distance_to_bounds": round(distance, 4),
                "center": [round(float(v), 4) for v in properties["cframe"][:3]],
                "can_collide": properties.get("can_collide"),
                "bounds": {"min": [round(v, 4) for v in bounds[0]], "max": [round(v, 4) for v in bounds[1]]},
            })
    matches.sort(key=lambda obj: (obj["distance_to_bounds"], obj["path"]))
    return {
        "scene_name": scene["scene_name"],
        "center": list(center),
        "radius_studs": float(radius),
        "collidable_only": collidable_only,
        "part_bounds_examined": scanned,
        "matches_total": len(matches),
        "matches": matches[:limit],
        "truncated": len(matches) > limit,
        "limitations": "Distance is measured to axis-aligned bounding boxes, not actual MeshPart/CSG geometry or navigation paths.",
    }
