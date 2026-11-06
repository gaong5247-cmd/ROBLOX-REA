"""Bounded, data-only scene format shared by the Studio plugin and the CLI."""

from __future__ import annotations

import math
import re

SCHEMA = "roblox-rea.scene.v1"
MAX_NODES = 15_000
MAX_SCENE_BYTES = 12 * 1024 * 1024
MAX_NATIVE_BYTES = 48 * 1024 * 1024
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class SceneError(ValueError):
    """A capture is malformed, incomplete or exceeds supported bounds."""


def _string(value: object, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SceneError(f"{label} must be a non-empty string (max {maximum})")
    return value


def _check_data(value: object, label: str, depth: int = 0) -> None:
    if depth > 6:
        raise SceneError(f"{label}: property nesting limit exceeded")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and len(value) > 4096:
            raise SceneError(f"{label}: string too long")
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise SceneError(f"{label}: non-finite number")
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise SceneError(f"{label}: list too long")
        for item in value:
            _check_data(item, label, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 60:
            raise SceneError(f"{label}: too many properties")
        for key, item in value.items():
            _string(key, f"{label} key", 80)
            _check_data(item, label, depth + 1)
        return
    raise SceneError(f"{label}: unsupported property value")


def _vector(props: dict, name: str, length: int) -> None:
    value = props.get(name)
    if value is None:
        return
    if not isinstance(value, list) or len(value) != length or any(
        isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
        for n in value
    ):
        raise SceneError(f"{name} must contain {length} finite numbers")


def validate_scene(scene: object) -> dict:
    """Return a validated scene without interpreting or executing source content."""
    if not isinstance(scene, dict):
        raise SceneError("scene must be a JSON object")
    if scene.get("schema") != SCHEMA:
        raise SceneError(f"schema must be {SCHEMA}")
    _string(scene.get("scene_name"), "scene_name", 200)
    root = _string(scene.get("root_id"), "root_id", 64)
    if not IDENTIFIER.fullmatch(root):
        raise SceneError("invalid root_id")
    nodes = scene.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        raise SceneError(f"nodes must contain between 1 and {MAX_NODES} items")
    parents: dict[str, str | None] = {}
    paths: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise SceneError(f"node {index} must be an object")
        key = _string(node.get("id"), f"node {index}.id", 64)
        if not IDENTIFIER.fullmatch(key) or key in parents:
            raise SceneError(f"node {index}: invalid or duplicate id")
        parent = node.get("parent_id")
        if parent is not None and (not isinstance(parent, str) or not IDENTIFIER.fullmatch(parent)):
            raise SceneError(f"node {index}: invalid parent_id")
        parents[key] = parent
        _string(node.get("name"), f"node {index}.name", 200)
        _string(node.get("class"), f"node {index}.class", 80)
        if "path" in node:
            path = _string(node["path"], f"node {index}.path", 2048)
            if path in paths:
                raise SceneError(f"node {index}: duplicate hierarchy path")
            paths.add(path)
        props = node.get("properties", {})
        if not isinstance(props, dict):
            raise SceneError(f"node {index}.properties must be an object")
        _check_data(props, f"node {index}.properties")
        _vector(props, "size", 3)
        _vector(props, "cframe", 12)
        _vector(props, "color", 3)
        _vector(props, "local_cframe", 12)
        if "size" in props and any(n <= 0 or n > 1_000_000 for n in props["size"]):
            raise SceneError("size components must be > 0 and <= 1,000,000 studs")
        for key in ("cframe", "local_cframe"):
            if key in props:
                cf = props[key]
                if any(abs(n) > 100_000_000 for n in cf[:3]) or any(abs(n) > 1.001 for n in cf[3:]):
                    raise SceneError(f"{key} components exceed expected Roblox transform bounds")
        if "color" in props and any(not 0 <= n <= 1 for n in props["color"]):
            raise SceneError("color components must be between 0 and 1")

    if root not in parents or parents[root] is not None:
        raise SceneError("root_id must refer to a root node")
    if sum(parent is None for parent in parents.values()) != 1:
        raise SceneError("scene must have exactly one root")
    # Check both dangling references and cycles without recursive Python stack use.
    finished: set[str] = set()
    for key in parents:
        chain: set[str] = set()
        current: str | None = key
        while current is not None and current not in finished:
            if current in chain:
                raise SceneError("parent cycle detected")
            chain.add(current)
            if current not in parents:
                raise SceneError("dangling parent_id")
            current = parents[current]
            if len(chain) > 150:
                raise SceneError("scene hierarchy too deep")
        finished.update(chain)
    if isinstance(scene.get("source"), dict):
        _check_data(scene["source"], "source")
    return scene
