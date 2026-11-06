"""Local-only storage with bounded, opaque capture IDs and atomic writes."""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .schema import MAX_NATIVE_BYTES, MAX_SCENE_BYTES, SceneError, validate_scene
from .rescue import BUNDLE_SCHEMA, MAX_TOTAL_NATIVE_BYTES, validate_bundle_request, package_digest

CAPTURE_ID = re.compile(r"^[0-9a-f]{32}$")


def data_dir() -> Path:
    return Path(os.environ.get("REA_RBX_DATA_DIR", "~/.roblox-rea")).expanduser().resolve()


class CaptureStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or data_dir()).resolve()
        self.captures = self.root / "captures"
        self.native = self.root / "native"
        self.packages = self.root / "packages"
        self.captures.mkdir(parents=True, exist_ok=True)
        self.native.mkdir(parents=True, exist_ok=True)
        self.packages.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _id(capture_id: str) -> str:
        if not isinstance(capture_id, str) or not CAPTURE_ID.fullmatch(capture_id):
            raise SceneError("Invalid capture ID")
        return capture_id

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        file_descriptor, tmp = tempfile.mkstemp(prefix=".rea-", dir=path.parent)
        try:
            with os.fdopen(file_descriptor, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def save_capture(self, scene: dict) -> dict:
        validate_scene(scene)
        # Do not trust IDs sent by the client or let them overwrite existing files.
        document = dict(scene)
        document["capture_id"] = secrets.token_hex(16)
        document["stored_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(content) > MAX_SCENE_BYTES:
            raise SceneError("Capture is too large")
        self._write_atomic(self.captures / (document["capture_id"] + ".json"), content)
        return {"capture_id": document["capture_id"], "nodes": len(scene["nodes"]), "scene_name": scene["scene_name"]}

    def read_capture(self, capture_id: str) -> dict:
        path = self.captures / (self._id(capture_id) + ".json")
        scene = json.loads(path.read_text(encoding="utf-8"))
        return validate_scene(scene)

    def list_captures(self, limit: int = 50) -> list[dict]:
        items = sorted(self.captures.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for path in items[:max(1, min(limit, 100))]:
            try:
                scene = self.read_capture(path.stem)
                out.append({"capture_id": scene["capture_id"], "scene_name": scene["scene_name"], "node_count": len(scene["nodes"]), "stored_at": scene.get("stored_at")})
            except (OSError, ValueError, KeyError):
                continue
        return out

    def save_native(self, name: str, content: bytes, kind: str = "model") -> dict:
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            raise SceneError("Invalid native model name")
        if kind not in ("model", "terrain"):
            raise SceneError("Invalid native backup kind")
        if not content or len(content) > MAX_NATIVE_BYTES:
            raise SceneError("Native RBXM payload empty or too large")
        native_id = secrets.token_hex(16)
        info = {"native_id": native_id, "name": name, "bytes": len(content), "kind": kind, "sha256": hashlib.sha256(content).hexdigest(),
                "stored_at": datetime.now(timezone.utc).isoformat()}
        self._write_atomic(self.native / (native_id + ".rbxm"), content)
        self._write_atomic(self.native / (native_id + ".json"), json.dumps(info, ensure_ascii=False).encode("utf-8"))
        return info

    def native_info(self, native_id: str) -> dict:
        info = json.loads((self.native / (self._id(native_id) + ".json")).read_text(encoding="utf-8"))
        if info.get("native_id") != native_id:
            raise SceneError("Native metadata ID mismatch")
        return info

    def read_native(self, native_id: str) -> bytes:
        metadata = self.native_info(native_id)
        content = (self.native / (self._id(native_id) + ".rbxm")).read_bytes()
        digest = metadata.get("sha256")
        if digest is not None and not secrets.compare_digest(hashlib.sha256(content).hexdigest(), digest):
            raise SceneError("Native backup SHA-256 verification failed")
        if len(content) != metadata.get("bytes"):
            raise SceneError("Native backup length verification failed")
        return content

    def list_native(self, limit: int = 50) -> list[dict]:
        items = sorted(self.native.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for path in items[:max(1, min(limit, 100))]:
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out

    def save_package(self, request: dict) -> dict:
        request = validate_bundle_request(request)
        self.read_capture(request["capture_id"])
        main_info = self.native_info(request["native_id"])
        if main_info.get("kind", "model") != "model":
            raise SceneError("Main RBXM must be a model backup")
        total_bytes = 0
        all_ids = [request["native_id"]] + [c["native_id"] for c in request["terrain_chunks"]]
        for index, native_id in enumerate(all_ids):
            info = self.native_info(native_id)
            expected_kind = "model" if index == 0 else "terrain"
            if info.get("kind", "model") != expected_kind:
                raise SceneError(f"Native backup {native_id} has wrong kind")
            # Verify content before committing a manifest: records cannot point at damaged files.
            self.read_native(native_id)
            total_bytes += info["bytes"]
            if total_bytes > MAX_TOTAL_NATIVE_BYTES:
                raise SceneError("Rescue package exceeds 512 MiB native budget")
        document = dict(request)
        document.update({"schema": BUNDLE_SCHEMA, "package_id": secrets.token_hex(16),
                         "stored_at": datetime.now(timezone.utc).isoformat(),
                         "native_bytes": total_bytes})
        document["sha256"] = package_digest(document)
        self._write_atomic(self.packages / (document["package_id"] + ".json"),
                           json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        return document

    def read_package(self, package_id: str) -> dict:
        document = json.loads((self.packages / (self._id(package_id) + ".json")).read_text(encoding="utf-8"))
        if document.get("schema") != BUNDLE_SCHEMA or document.get("package_id") != package_id:
            raise SceneError("Invalid rescue package metadata")
        validate_bundle_request({key: document[key] for key in
                                 ("name", "capture_id", "native_id", "terrain_chunks", "terrain_settings")
                                 if key in document})
        digest = package_digest(document)
        if not secrets.compare_digest(digest, document.get("sha256", "")):
            raise SceneError("Rescue manifest integrity check failed")
        return document

    def verify_package(self, package_id: str) -> dict:
        document = self.read_package(package_id)
        entries = []
        errors = []
        for native_id in [document["native_id"]] + [chunk["native_id"] for chunk in document["terrain_chunks"]]:
            try:
                contents = self.read_native(native_id)
                info = self.native_info(native_id)
                entries.append({"native_id": native_id, "bytes": len(contents),
                                "kind": info.get("kind", "model"), "verified": True})
            except (OSError, ValueError) as exc:
                errors.append({"native_id": native_id, "error": str(exc)})
        try:
            self.read_capture(document["capture_id"])
        except (OSError, ValueError) as exc:
            errors.append({"capture_id": document["capture_id"], "error": str(exc)})
        return {"package_id": package_id, "ok": not errors, "files_checked": len(entries),
                "terrain_chunks": len(document["terrain_chunks"]), "entries": entries, "errors": errors,
                "meaning": "Checks local file integrity and availability, not in-Studio rendering fidelity."}

    def list_packages(self, limit: int = 50) -> list[dict]:
        paths = sorted(self.packages.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        items = []
        for path in paths[:max(1, min(limit, 100))]:
            try:
                doc = self.read_package(path.stem)
                items.append({"package_id": doc["package_id"], "name": doc["name"],
                              "capture_id": doc["capture_id"], "terrain_chunks": len(doc["terrain_chunks"]),
                              "native_bytes": doc["native_bytes"], "stored_at": doc["stored_at"]})
            except (OSError, ValueError):
                continue
        return items

    def auth_token(self) -> str:
        """Use a persisted localhost secret (never sent to a remote service)."""
        path = self.root / "bridge.token"
        try:
            token = path.read_text(encoding="ascii").strip()
            if len(token) == 64 and all(c in "0123456789abcdef" for c in token):
                return token
        except FileNotFoundError:
            pass
        # The file lives in a user-owned local directory, not the Git repository.
        token = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(token + "\n")
        return token
