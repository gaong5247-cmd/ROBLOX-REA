"""Strict manifests for authorized Studio map backups.

A rescue package is an index of pre-existing local captures and opaque RBXM
blobs. It never synthesizes missing mesh geometry or script source.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from .schema import SceneError

BUNDLE_SCHEMA = "roblox-rea.rescue.v1"
MAX_TERRAIN_CHUNKS = 48
MAX_TOTAL_NATIVE_BYTES = 512 * 1024 * 1024
MAX_TILE_CELLS = 48
CELL_LOW = -32000
CELL_HIGH = 32000
MATERIAL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")


def _triplet(value: Any, field: str, lo: int, hi: int) -> list[int]:
    if not isinstance(value, list) or len(value) != 3 or any(
        type(x) is not int or x < lo or x > hi for x in value
    ):
        raise SceneError(f"{field} must contain three integers between {lo} and {hi}")
    return value


def _unit_color(value: Any, field: str) -> None:
    if not isinstance(value, list) or len(value) != 3 or any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
        for v in value
    ):
        raise SceneError(f"{field} must be a 3-element unit RGB list")


def _settings(value: Any) -> None:
    if not isinstance(value, dict) or len(value) > 9:
        raise SceneError("Invalid Terrain settings")
    allowed = {"decoration", "grass_length", "water_color", "water_reflectance",
               "water_transparency", "water_wave_size", "water_wave_speed", "material_colors"}
    if not set(value) <= allowed:
        raise SceneError("Unexpected Terrain setting")
    for field, field_value in value.items():
        if field == "decoration":
            if type(field_value) is not bool:
                raise SceneError("decoration must be a boolean")
        elif field == "water_color":
            _unit_color(field_value, "water_color")
        elif field == "material_colors":
            if not isinstance(field_value, dict) or len(field_value) > 80:
                raise SceneError("Invalid material_colors")
            for material, color in field_value.items():
                if not isinstance(material, str) or not MATERIAL_NAME.fullmatch(material):
                    raise SceneError("Invalid terrain material name")
                _unit_color(color, f"material_colors.{material}")
        else:
            if type(field_value) not in (float, int) or not math.isfinite(field_value):
                raise SceneError(f"Invalid {field}")
            if not 0 <= field_value <= 100:
                raise SceneError(f"Out-of-range {field}")
            if field in {"water_reflectance", "water_transparency"} and field_value > 1:
                raise SceneError(f"Out-of-range {field}")


def validate_bundle_request(request: object) -> dict:
    if not isinstance(request, dict):
        raise SceneError("Rescue package must be a JSON object")
    mandatory = {"name", "capture_id", "native_id", "terrain_chunks"}
    if not mandatory <= set(request) or not set(request) <= mandatory | {"terrain_settings"}:
        raise SceneError("Rescue package has missing or unexpected fields")
    name = request["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 200:
        raise SceneError("Invalid rescue package name")
    from .storage import CaptureStore

    capture_id = CaptureStore._id(request["capture_id"])
    native_id = CaptureStore._id(request["native_id"])
    chunks = request["terrain_chunks"]
    if not isinstance(chunks, list) or len(chunks) > MAX_TERRAIN_CHUNKS:
        raise SceneError(f"terrain_chunks must contain at most {MAX_TERRAIN_CHUNKS} items")
    if "terrain_settings" in request:
        _settings(request["terrain_settings"])

    ids = {native_id}
    boxes = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict) or set(chunk) != {"native_id", "origin_cells", "size_cells"}:
            raise SceneError(f"terrain chunk {index} has invalid fields")
        tid = CaptureStore._id(chunk["native_id"])
        if tid in ids:
            raise SceneError("Rescue package refers to a duplicate native ID")
        ids.add(tid)
        origin = _triplet(chunk["origin_cells"], "origin_cells", CELL_LOW, CELL_HIGH - 1)
        size = _triplet(chunk["size_cells"], "size_cells", 1, MAX_TILE_CELLS)
        if any(origin[d] + size[d] > CELL_HIGH for d in range(3)):
            raise SceneError("Terrain tile exceeds supported cell coordinates")
        # Terrain tiles are half-open cell volumes, and may touch at edges.
        box = (origin, [origin[i] + size[i] for i in range(3)])
        for prior in boxes:
            if all(box[0][i] < prior[1][i] and prior[0][i] < box[1][i] for i in range(3)):
                raise SceneError("Overlapping terrain chunks are not permitted")
        boxes.append(box)
    return request


def package_digest(doc: dict) -> str:
    """SHA-256 for accidental corruption detection, not a cryptographic signature."""
    stable = {key: doc[key] for key in
              ("schema", "name", "capture_id", "native_id", "terrain_chunks")}
    if "terrain_settings" in doc:
        stable["terrain_settings"] = doc["terrain_settings"]
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
