"""Authenticated HTTP bridge bound exclusively to the local computer."""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from .analysis import analyze_scene, compare_scenes
from .audit import audit_reconstruction
from .schema import MAX_NATIVE_BYTES, MAX_SCENE_BYTES, SceneError
from .storage import CaptureStore

DEFAULT_PORT = 8787


class REABridge(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int = DEFAULT_PORT, store: CaptureStore | None = None):
        self.store = store or CaptureStore()
        self.token = self.store.auth_token()
        # Only loopback is accepted; there is deliberately no --host flag.
        super().__init__(("127.0.0.1", port), BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    server: REABridge
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Avoid logging credentials, filenames or sensitive scene data.
        print("[rea-rbx] " + fmt % args)

    def _reply(self, code: int, payload: dict | bytes, content_type: str = "application/json") -> None:
        if isinstance(payload, dict):
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        else:
            data = payload
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        provided = self.headers.get("X-REA-Token", "")
        if len(provided) > 256 or not hmac.compare_digest(provided, self.server.token):
            self.close_connection = True
            self._reply(401, {"error": "Missing or invalid X-REA-Token"})
            return False
        # Reject browser-originated calls. This is a local desktop bridge,
        # never a public web API. Studio plugin requests omit Origin.
        if self.headers.get("Origin"):
            self.close_connection = True
            self._reply(403, {"error": "Browser origins are not permitted"})
            return False
        return True

    def _url(self) -> str:
        return unquote(urlsplit(self.path).path)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self._url()
        if path == "/health":
            self._reply(200, {"status": "ok", "service": "roblox-rea", "version": "0.2.0"})
            return
        if not self._authorized():
            return
        try:
            store = self.server.store
            if path == "/v1/captures":
                self._reply(200, {"items": store.list_captures()})
            elif path == "/v1/native":
                self._reply(200, {"items": store.list_native()})
            elif path.startswith("/v1/captures/"):
                rest = path.removeprefix("/v1/captures/")
                if rest.endswith("/analysis"):
                    scene = store.read_capture(rest.removesuffix("/analysis"))
                    self._reply(200, analyze_scene(scene))
                elif rest.endswith("/audit"):
                    scene = store.read_capture(rest.removesuffix("/audit"))
                    self._reply(200, audit_reconstruction(scene))
                else:
                    self._reply(200, store.read_capture(rest))
            elif path.startswith("/v1/native/"):
                raw = store.read_native(path.removeprefix("/v1/native/"))
                self._reply(200, raw, "application/octet-stream")
            else:
                self._reply(404, {"error": "Unknown endpoint"})
        except (FileNotFoundError, IsADirectoryError):
            self._reply(404, {"error": "Capture not found"})
        except (SceneError, ValueError) as exc:
            self._reply(400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        # Close after every POST; error paths do not necessarily consume the body.
        # Otherwise unread JSON bytes can be parsed as a second HTTP request.
        self.close_connection = True
        if not self._authorized():
            return
        path = self._url()
        compare_id = path.removeprefix("/v1/compare/") if path.startswith("/v1/compare/") else None
        if path not in ("/v1/captures", "/v1/native") and compare_id is None:
            self._reply(404, {"error": "Unknown endpoint"})
            return
        cap = MAX_NATIVE_BYTES if path == "/v1/native" else MAX_SCENE_BYTES
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._reply(411, {"error": "Content-Length required"})
            return
        if size < 1 or size > cap:
            self._reply(413, {"error": f"Payload must be between 1 and {cap} bytes"})
            self.close_connection = True
            return
        raw = self.rfile.read(size)
        if len(raw) != size:
            self._reply(400, {"error": "Incomplete request"})
            return
        try:
            if path == "/v1/captures" or compare_id is not None:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self._reply(415, {"error": "Expected application/json"})
                    return
                doc = json.loads(raw.decode("utf-8"))
                if compare_id is None:
                    result = self.server.store.save_capture(doc)
                else:
                    # Comparison is read-only: it never stores or modifies the submitted scene.
                    result = compare_scenes(self.server.store.read_capture(compare_id), doc)
            else:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/octet-stream":
                    self._reply(415, {"error": "Expected application/octet-stream"})
                    return
                result = self.server.store.save_native(unquote(self.headers.get("X-REA-Name", "Untitled")), raw)
            self._reply(201 if compare_id is None else 200, result)
        except (FileNotFoundError, IsADirectoryError):
            self._reply(404, {"error": "Capture not found"})
        except (SceneError, ValueError, UnicodeError, TypeError) as exc:
            self._reply(400, {"error": str(exc)})


def serve(port: int = DEFAULT_PORT, store: CaptureStore | None = None) -> None:
    server = REABridge(port, store)
    print(f"ROBLOX-REA local bridge: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Studio plugin token: {server.token}", flush=True)
    print("Token is private; do not commit it. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
