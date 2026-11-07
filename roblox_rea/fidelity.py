"""Evidence-based, bounded reconstruction accuracy checks for Studio scenes.

Only properties represented in scene JSON are compared.  A passing report is
*not* evidence that mesh triangles, terrain voxels or script source survived.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .schema import SceneError, validate_scene

SCHEMA = "roblox-rea.fidelity-report.v1"
UNVERIFIABLE_CLASSES = frozenset({"MeshPart", "UnionOperation", "Terrain", "Script", "LocalScript", "ModuleScript"})


def _limit(value: object, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be a finite number between 0 and {maximum}")
    return float(value)


def _ratio(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 100.0


def _close(before: Any, after: Any, epsilon: float) -> bool:
    if isinstance(before, bool) or isinstance(after, bool):
        return type(before) is type(after) and before == after
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return math.isclose(before, after, rel_tol=0, abs_tol=epsilon)
    if type(before) is not type(after):
        return False
    if isinstance(before, list):
        return len(before) == len(after) and all(_close(a, b, epsilon) for a, b in zip(before, after))
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(_close(v, after[k], epsilon) for k, v in before.items())
    return before == after


def _transform_errors(original: list, restored: list) -> tuple[float, float]:
    position_error = math.dist(original[:3], restored[:3])
    # Rotations are 3x3 matrices, row-major, in Roblox CFrame components.
    # trace(R_source^T * R_restored) is their element-wise dot product.
    trace = sum(a * b for a, b in zip(original[3:], restored[3:]))
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    return position_error, math.degrees(math.acos(cosine))


def _refs(node: dict, by_id: dict[str, str]) -> dict[str, str]:
    result = {}
    for field, target_id in node.get("references", {}).items():
        result[field] = by_id.get(target_id, f"<unresolved:{target_id}>")
    return result


def assess_fidelity(reference: dict, restored: dict, *, position_tolerance: float = 0.05,
                    rotation_tolerance: float = 0.1, size_tolerance: float = 0.05,
                    numeric_tolerance: float = 0.0001, limit: int = 60) -> dict:
    """Compare observed scene metadata using stable hierarchy paths, not capture-local IDs.

    Distinguishes observed differences from unobservable details such as Mesh geometry,
    Lua source and Terrain voxels. May be called read-only by Studio or AI agents.
    """
    validate_scene(reference)
    validate_scene(restored)
    position_tolerance = _limit(position_tolerance, "position_tolerance", 100)
    rotation_tolerance = _limit(rotation_tolerance, "rotation_tolerance", 180)
    size_tolerance = _limit(size_tolerance, "size_tolerance", 100)
    numeric_tolerance = _limit(numeric_tolerance, "numeric_tolerance", 1)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")

    before = {n.get("path", n["id"]): n for n in reference["nodes"]}
    after = {n.get("path", n["id"]): n for n in restored["nodes"]}
    before_ids = {n["id"]: n.get("path", n["id"]) for n in reference["nodes"]}
    after_ids = {n["id"]: n.get("path", n["id"]) for n in restored["nodes"]}
    common = sorted(before.keys() & after.keys())
    missing = sorted(before.keys() - after.keys())
    unexpected = sorted(after.keys() - before.keys())
    changed = []
    exact_count = 0
    matched_fields = 0
    total_fields = 0
    matched_links = 0
    total_links = 0
    drift_count = 0
    class_changes = 0
    max_position = 0.0
    max_rotation = 0.0
    max_size = 0.0
    mismatch_types: Counter[str] = Counter()

    for path in common:
        source = before[path]
        target = after[path]
        problems: list[dict] = []
        if source["class"] != target["class"]:
            class_changes += 1
            problems.append({"kind": "class", "expected": source["class"], "actual": target["class"]})
        if source["name"] != target["name"]:
            problems.append({"kind": "name", "expected": source["name"], "actual": target["name"]})
        p = source.get("properties", {})
        q = target.get("properties", {})
        for field in sorted(p.keys() | q.keys()):
            total_fields += 1
            if field == "cframe" and field in p and field in q:
                distance, rotation = _transform_errors(p[field], q[field])
                max_position = max(max_position, distance)
                max_rotation = max(max_rotation, rotation)
                if distance <= position_tolerance and rotation <= rotation_tolerance:
                    matched_fields += 1
                else:
                    drift_count += 1
                    problems.append({"kind": "transform", "field": field,
                                     "position_studs": round(distance, 6),
                                     "rotation_degrees": round(rotation, 6)})
            elif field == "size" and field in p and field in q:
                error = max(abs(a - b) for a, b in zip(p[field], q[field]))
                max_size = max(max_size, error)
                if error <= size_tolerance:
                    matched_fields += 1
                else:
                    problems.append({"kind": "size", "field": field, "maximum_axis_studs": round(error, 6)})
            elif field in p and field in q and _close(p[field], q[field], numeric_tolerance):
                matched_fields += 1
            else:
                # Cap the report: do not include huge metadata / asset strings.
                problems.append({"kind": "property", "field": field})
        for field in ("tags", "attributes", "external_references"):
            a = source.get(field, [] if field != "attributes" else {})
            b = target.get(field, [] if field != "attributes" else {})
            if not _close(a, b, numeric_tolerance):
                problems.append({"kind": field})
        s_links, t_links = _refs(source, before_ids), _refs(target, after_ids)
        for field in sorted(s_links.keys() | t_links.keys()):
            total_links += 1
            if field in s_links and s_links[field] == t_links.get(field):
                matched_links += 1
            else:
                problems.append({"kind": "reference", "field": field,
                                 "expected_path": s_links.get(field), "actual_path": t_links.get(field)})
        if problems:
            changed.append({"path": path, "problems": problems[:20], "truncated": len(problems) > 20})
            mismatch_types.update(x["kind"] for x in problems)
        else:
            exact_count += 1

    unverified = Counter(n["class"] for n in reference["nodes"] if n["class"] in UNVERIFIABLE_CLASSES)
    observed_pass = not (missing or unexpected or changed)
    notes = [
        "Percentages measure captured JSON metadata only; they are not visual/behavioral accuracy scores.",
        "Mesh/CSG triangles, Terrain voxels, asset availability, and script source are not verified by JSON comparison.",
        "Hierarchy paths depend on sibling order; inserting same-name siblings can appear as missing/changed nodes.",
        "Referenced objects outside the selected root cannot be reconstructed from this scene snapshot.",
    ]
    return {
        "schema": SCHEMA,
        "reference": reference.get("capture_id", reference["scene_name"]),
        "restored": restored.get("capture_id", restored["scene_name"]),
        "observed_status": "match" if observed_pass else "different",
        "counts": {
            "reference_nodes": len(before), "restored_nodes": len(after), "matched_paths": len(common),
            "matching_nodes": exact_count, "missing": len(missing), "unexpected": len(unexpected),
            "changed": len(changed), "class_mismatches": class_changes, "transform_mismatches": drift_count,
            "captured_fields_matched": matched_fields, "captured_fields_compared": total_fields,
            "references_matched": matched_links, "references_compared": total_links,
        },
        "measurements": {
            "node_coverage_percent": _ratio(len(common), len(before)),
            "matching_node_percent": _ratio(exact_count, len(before)),
            "observed_property_match_percent": _ratio(matched_fields, total_fields),
            "observed_reference_match_percent": _ratio(matched_links, total_links),
            "maximum_position_error_studs": round(max_position, 6),
            "maximum_rotation_error_degrees": round(max_rotation, 6),
            "maximum_size_error_studs": round(max_size, 6),
        },
        "tolerances": {
            "position_studs": position_tolerance,
            "rotation_degrees": rotation_tolerance,
            "size_studs": size_tolerance,
            "numeric": numeric_tolerance,
        },
        "mismatch_types": dict(mismatch_types.most_common()),
        "missing_paths": missing[:limit], "unexpected_paths": unexpected[:limit],
        "changed_details": changed[:limit],
        "truncated": len(missing) > limit or len(unexpected) > limit or len(changed) > limit,
        "unverifiable_class_counts": dict(unverified.most_common()),
        "limitations": notes,
    }
