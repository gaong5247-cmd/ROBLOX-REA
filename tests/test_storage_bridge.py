import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from roblox_rea.bridge import REABridge
from roblox_rea.schema import SceneError
from roblox_rea.storage import CaptureStore

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_scene.json"


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CaptureStore(Path(self.tmp.name))
        self.scene = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_store_and_retrieve(self):
        result = self.store.save_capture(self.scene)
        capture_id = result["capture_id"]
        self.assertEqual(len(capture_id), 32)
        self.assertEqual(self.store.read_capture(capture_id)["scene_name"], "ExampleArena")
        self.assertEqual(len(self.store.list_captures()), 1)
        self.assertNotIn("capture_id", self.scene)

    def test_path_traversal_rejected(self):
        with self.assertRaises(SceneError):
            self.store.read_capture("../../etc/passwd")

    def test_native_binary_roundtrip(self):
        model = b"\x00\xff\x81\x00<roblox!>\x00"
        result = self.store.save_native("내 경기장", model)
        self.assertEqual(self.store.read_native(result["native_id"]), model)
        self.assertEqual(self.store.list_native()[0]["name"], "내 경기장")

    def test_token_persistence(self):
        self.assertEqual(self.store.auth_token(), self.store.auth_token())
        self.assertEqual(len(self.store.auth_token()), 64)


class BridgeTests(StorageTests):
    def setUp(self):
        super().setUp()
        self.server = REABridge(0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close)

    def _close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self, method, path, body=None, token=True, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {"X-REA-Token": self.server.token} if token else {}
        headers.update(extra or {})
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        status = response.status
        data = response.read()
        conn.close()
        return status, data

    def test_end_to_end(self):
        body = json.dumps(self.scene).encode()
        status, result = self.send("POST", "/v1/captures", body, extra={"Content-Type": "application/json"})
        self.assertEqual(status, 201)
        capture_id = json.loads(result)["capture_id"]
        status, data = self.send("GET", "/v1/captures/" + capture_id + "/analysis")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["node_count"], 3)
        status, data = self.send("GET", "/v1/captures/" + capture_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["scene_name"], "ExampleArena")

    def test_auth_and_browser_origin(self):
        self.assertEqual(self.send("GET", "/v1/captures", token=False)[0], 401)
        self.assertEqual(self.send("GET", "/v1/captures", extra={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.send("GET", "/health", token=False)[0], 200)

    def test_native_transport(self):
        content = b"\x00\xff\x80model\x00"
        status, payload = self.send("POST", "/v1/native", content, extra={"Content-Type": "application/octet-stream", "X-REA-Name": "%EB%82%B4%20%EB%A7%B5"})
        self.assertEqual(status, 201)
        native_id = json.loads(payload)["native_id"]
        self.assertEqual(self.send("GET", "/v1/native/" + native_id), (200, content))


if __name__ == "__main__":
    unittest.main()
