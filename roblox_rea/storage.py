"""Local-only storage with bounded, opaque capture IDs and atomic writes."""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .schema import MAX_NATIVE_BYTES, MAX_SCENE_BYTES, SceneError, validate_scene

CAPTURE_ID = re.compile(r"^[0-9a-f]{32}$")


def data_dir() -> Path:
    return Path(os.environ.get("REA_RBX_DATA_DIR", "~/.roblox-rea")).expanduser().resolve()


class CaptureStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or data_dir()).resolve()
        self.captures = self.root / "captures"
        self.native = self.root / "native"
        self.captures.mkdir(parents=True, exist_ok=True)
        self.native.mkdir(parents=True, exist_ok=True)

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

    def save_native(self, name: str, content: bytes) -> dict:
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            raise SceneError("Invalid native model name")
        if not content or len(content) > MAX_NATIVE_BYTES:
            raise SceneError("Native RBXM payload empty or too large")
        native_id = secrets.token_hex(16)
        info = {"native_id": native_id, "name": name, "bytes": len(content), "stored_at": datetime.now(timezone.utc).isoformat()}
        self._write_atomic(self.native / (native_id + ".rbxm"), content)
        self._write_atomic(self.native / (native_id + ".json"), json.dumps(info, ensure_ascii=False).encode("utf-8"))
        return info

    def read_native(self, native_id: str) -> bytes:
        return (self.native / (self._id(native_id) + ".rbxm")).read_bytes()

    def list_native(self, limit: int = 50) -> list[dict]:
        items = sorted(self.native.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for path in items[:max(1, min(limit, 100))]:
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out

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
