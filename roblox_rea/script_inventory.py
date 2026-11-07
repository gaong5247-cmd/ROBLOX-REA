"""Metadata-only Studio script inventory: no Luau source leaves Studio in v0.5."""

from __future__ import annotations

import json
from collections import Counter

from .schema import SceneError

INVENTORY_SCHEMA = "roblox-rea.script-inventory.v1"
MAX_ITEMS = 8000
MAX_BYTES = 1024 * 1024
CLASSES = frozenset({"Script", "LocalScript", "ModuleScript"})
SERVICES = frozenset({
    "Workspace", "ServerScriptService", "ServerStorage", "ReplicatedStorage",
    "ReplicatedFirst", "StarterPlayer", "StarterGui", "StarterPack",
})
ITEM_FIELDS = frozenset({"path", "name", "class", "service", "enabled", "run_context", "archivable"})
RUN_CONTEXTS = frozenset({"Legacy", "Server", "Client"})


def validate_script_inventory(document: object) -> dict:
    if not isinstance(document, dict):
        raise SceneError("Script inventory must be an object")
    if document.get("schema") != INVENTORY_SCHEMA:
        raise SceneError("Invalid script-inventory schema")
    if document.get("mode") != "metadata-only" or document.get("scope") != "authorized-studio-project":
        raise SceneError("Script inventory must be Studio-authorized metadata-only")
    if document.get("includes_source") is not False:
        raise SceneError("Script source is not accepted in v0.5")
    place = document.get("place_id")
    if type(place) is not int or not 0 <= place <= 10**16:
        raise SceneError("Invalid place_id")
    if set(document) - {"schema", "mode", "scope", "includes_source", "place_id",
                        "captured_at", "items", "inventory_id", "stored_at"}:
        raise SceneError("Unexpected top-level script inventory field")
    stamp = document.get("captured_at")
    if type(stamp) is not int or stamp < 0:
        raise SceneError("Invalid captured_at timestamp")
    items = document.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise SceneError(f"Script inventory cannot exceed {MAX_ITEMS} entries")
    paths: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict) or set(item) - ITEM_FIELDS:
            raise SceneError(f"Unexpected script inventory fields in item {i}")
        if item.get("class") not in CLASSES or item.get("service") not in SERVICES:
            raise SceneError(f"Unsupported script class/service in item {i}")
        for key, maxlen in (("path", 1024), ("name", 200)):
            s = item.get(key)
            if not isinstance(s, str) or not s or len(s) > maxlen or "\x00" in s:
                raise SceneError(f"Invalid script {key} in item {i}")
        path = item["path"]
        if not path.startswith(item["service"] + "/") or path in paths:
            raise SceneError(f"Ambiguous script path in item {i}")
        paths.add(path)
        if "enabled" in item and type(item["enabled"]) is not bool:
            raise SceneError(f"Invalid enabled flag in item {i}")
        if "archivable" in item and type(item["archivable"]) is not bool:
            raise SceneError(f"Invalid archivable flag in item {i}")
        if "run_context" in item and (item["class"] != "Script" or
                                      item["run_context"] not in RUN_CONTEXTS):
            raise SceneError(f"Invalid RunContext in item {i}")
    if len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
        raise SceneError("Script inventory exceeds 1 MiB")
    return document


def summarize_script_inventory(document: dict) -> dict:
    doc = validate_script_inventory(document)
    return {
        "inventory_id": doc.get("inventory_id"),
        "place_id": doc["place_id"],
        "count": len(doc["items"]),
        "by_class": dict(Counter(i["class"] for i in doc["items"])),
        "by_service": dict(Counter(i["service"] for i in doc["items"])),
        "includes_source": False,
        "v1_goal": "Explicitly approved Studio-only source backup; no runtime/executor extraction.",
    }


def compare_script_inventories(reference: dict, restored: dict, limit: int = 50) -> dict:
    validate_script_inventory(reference)
    validate_script_inventory(restored)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    before = {x["path"]: x for x in reference["items"]}
    after = {x["path"]: x for x in restored["items"]}
    missing = sorted(set(before) - set(after))
    new = sorted(set(after) - set(before))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return {
        "reference_id": reference.get("inventory_id"),
        "restored_id": restored.get("inventory_id"),
        "counts": {"missing": len(missing), "added": len(new), "metadata_changed": len(changed)},
        "missing": missing[:limit], "added": new[:limit], "metadata_changed": changed[:limit],
        "truncated": max(len(missing), len(new), len(changed)) > limit,
        "source_code_verified": False,
        "note": "Script names, locations and flags only. Luau bodies are not captured or compared.",
    }
