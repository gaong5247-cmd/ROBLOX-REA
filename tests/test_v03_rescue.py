"""v0.3 high-fidelity manifest + metadata + local bridge regression tests."""

import contextlib
import copy
import http.client
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from roblox_rea.analysis import compare_scenes
from roblox_rea.bridge import REABridge
from roblox_rea.cli import main
from roblox_rea.rescue import validate_bundle_request
from roblox_rea.schema import SceneError, validate_scene
from roblox_rea.storage import CaptureStore

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_scene.json"
PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "RobloxREA.plugin.lua"


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CaptureStore(Path(self.temp.name))
        self.scene = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.capture_id = self.store.save_capture(self.scene)["capture_id"]
        self.model = self.store.save_native("Mesh-rich model", b"\x00native model data\xff")
        self.terrain = self.store.save_native("Terrain tile", b"\x10native terrain data\x00", kind="terrain")
        self.request = {
            "name": "My Test Arena",
            "capture_id": self.capture_id,
            "native_id": self.model["native_id"],
            "terrain_chunks": [{
                "native_id": self.terrain["native_id"],
                "origin_cells": [-32, 0, 24],
                "size_cells": [32, 12, 32],
            }],
            "terrain_settings": {
                "water_color": [.1, .2, .3],
                "decoration": True,
                "water_wave_speed": 3.3,
                "material_colors": {"Grass": [0.1, .6, .1]},
            },
        }

    def test_save_verify_list_and_reopen(self):
        package = self.store.save_package(self.request)
        self.assertEqual(package["terrain_chunks"], self.request["terrain_chunks"])
        self.assertEqual(package["terrain_settings"], self.request["terrain_settings"])
        self.assertEqual(len(package["sha256"]), 64)
        self.assertEqual(self.store.read_package(package["package_id"])["name"], "My Test Arena")
        self.assertEqual(self.store.list_packages()[0]["terrain_chunks"], 1)
        proof = self.store.verify_package(package["package_id"])
        self.assertTrue(proof["ok"])
        self.assertEqual(proof["files_checked"], 2)

    def test_plain_model_only_package(self):
        request = copy.deepcopy(self.request)
        request.pop("terrain_settings")
        request["terrain_chunks"] = []
        package = self.store.save_package(request)
        self.assertTrue(self.store.verify_package(package["package_id"])["ok"])

    def test_overlapping_terrain_tiles_rejected(self):
        request = copy.deepcopy(self.request)
        more = self.store.save_native("other tile", b"other", kind="terrain")
        request["terrain_chunks"].append({
            "native_id": more["native_id"], "origin_cells": [-1, 4, 24],
            "size_cells": [32, 12, 32],
        })
        with self.assertRaisesRegex(SceneError, "Overlapping"):
            self.store.save_package(request)

    def test_adjacent_tiles_allowed(self):
        request = copy.deepcopy(self.request)
        more = self.store.save_native("other tile", b"other", kind="terrain")
        request["terrain_chunks"].append({
            "native_id": more["native_id"], "origin_cells": [0, 0, 24],
            "size_cells": [32, 12, 32],
        })
        self.assertEqual(len(self.store.save_package(request)["terrain_chunks"]), 2)

    def test_duplicate_ids_and_geometry_limits(self):
        for bad in [
            {"terrain_chunks": [dict(self.request["terrain_chunks"][0], native_id=self.model["native_id"])]},
            {"terrain_chunks": [dict(self.request["terrain_chunks"][0], size_cells=[49, 1, 1])]},
            {"terrain_chunks": [dict(self.request["terrain_chunks"][0], origin_cells=[32000, 0, 0])]},
            {"terrain_chunks": [dict(self.request["terrain_chunks"][0], size_cells=[True, 12, 32])]},
            {"terrain_settings": {"water_color": [1, -1, 0]}},
            {"terrain_settings": {"water_wave_speed": float("nan")}},
            {"terrain_settings": {"unknown": "value"}},
            {"terrain_settings": {"material_colors": {"bad name": [0, 0, 0]}}},
            {"rogue": "key"},
        ]:
            with self.subTest(bad=bad):
                request = copy.deepcopy(self.request)
                request.update(bad)
                with self.assertRaises(SceneError):
                    validate_bundle_request(request)

    def test_wrong_kind_rejected(self):
        request = copy.deepcopy(self.request)
        request["native_id"] = self.terrain["native_id"]
        request["terrain_chunks"] = []
        with self.assertRaisesRegex(SceneError, "Main RBXM"):
            self.store.save_package(request)
        request = copy.deepcopy(self.request)
        request["terrain_chunks"][0]["native_id"] = self.store.save_native("other model", b"model")["native_id"]
        with self.assertRaisesRegex(SceneError, "wrong kind"):
            self.store.save_package(request)

    def test_corrupted_native_detected(self):
        package = self.store.save_package(self.request)
        native_path = self.store.native / (self.terrain["native_id"] + ".rbxm")
        native_path.write_bytes(b"tampered")
        self.assertFalse(self.store.verify_package(package["package_id"])["ok"])
        self.assertEqual(len(self.store.verify_package(package["package_id"])["errors"]), 1)

    def test_corrupted_manifest_rejected(self):
        package = self.store.save_package(self.request)
        manifest_path = self.store.packages / (package["package_id"] + ".json")
        doc = json.loads(manifest_path.read_text())
        doc["terrain_settings"]["water_color"] = [.9, .9, .9]
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(SceneError, "integrity"):
            self.store.read_package(package["package_id"])

    def test_native_size_and_global_budget(self):
        with patch("roblox_rea.storage.MAX_TOTAL_NATIVE_BYTES", 3):
            with self.assertRaisesRegex(SceneError, "exceeds"):
                self.store.save_package(self.request)

    def test_cli_verify_and_list(self):
        package = self.store.save_package(self.request)
        with patch.dict("os.environ", {"REA_RBX_DATA_DIR": self.temp.name}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["verify", package["package_id"]]), 0)
            self.assertTrue(json.loads(output.getvalue())["ok"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["packages"]), 0)
            self.assertEqual(len(json.loads(output.getvalue())), 1)

    def test_extended_attributes_and_tags_compare(self):
        scene = copy.deepcopy(self.scene)
        node = scene["nodes"][1]
        node["tags"] = ["Spawn", "Capture"]
        node["attributes"] = {
            "Sector": "A1", "Brightness": 1.5,
            "GoalPos": {"t": "Vector3", "v": [5, 0, 9]},
            "Paint": {"t": "Color3", "v": [0.1, 0.2, 0.3]},
            "Frame": {"t": "CFrame", "v": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        }
        validate_scene(scene)
        report = compare_scenes(self.scene, scene)
        self.assertEqual(report["counts"]["modified"], 1)
        self.assertIn("attributes", report["modified_details"][0]["changes"])
        self.assertIn("tags", report["modified_details"][0]["changes"])
        duplicate = copy.deepcopy(scene)
        duplicate["nodes"][1]["tags"] = ["Spawn", "Spawn"]
        with self.assertRaises(SceneError):
            validate_scene(duplicate)

    def test_invalid_typed_attrs_rejected(self):
        for val in [
            {"t": "not-an-attribute", "v": [1]},
            {"t": "Vector2", "v": [1, True]},
            {"t": "Color3", "v": [-0.1, 0, 0]},
            {"t": "BrickColor", "v": [2.2]},
        ]:
            scene = copy.deepcopy(self.scene)
            scene["nodes"][0]["attributes"] = {"Paint": val}
            with self.subTest(val=val), self.assertRaises(SceneError):
                validate_scene(scene)

    def test_plugin_contains_native_and_deliberate_terrain_actions(self):
        source = PLUGIN.read_text(encoding="utf-8")
        for snippet in [
            "SerializeInstancesAsync({terrainRegion})", "Terrain:CopyRegion",
            ":PasteRegion(", 'confirmTerrain.Text == "APPLY TERRAIN"',
            "FinishRecording", "terrain_settings = terrainSettings()",
            "object:AddTag(tag)", "object:SetAttribute(key, decoded)",
            'kind = "terrain"',
        ]:
            if snippet == 'kind = "terrain"':
                self.assertIn('"terrain")', source)
            else:
                self.assertIn(snippet, source)


class RescueBridgeTests(RescueTests):
    def setUp(self):
        super().setUp()
        self.server = REABridge(0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        h = {"X-REA-Token": self.server.token, **(headers or {})}
        conn.request(method, path, body, h)
        response = conn.getresponse()
        status, data = response.status, response.read()
        conn.close()
        return status, json.loads(data)

    def test_manifest_http_endpoints(self):
        code, data = self.send("POST", "/v1/packages", json.dumps(self.request).encode("utf8"),
                               {"Content-Type": "application/json"})
        self.assertEqual(code, 201)
        id = data["package_id"]
        self.assertEqual(self.send("GET", "/v1/packages")[1]["items"][0]["package_id"], id)
        self.assertEqual(self.send("GET", f"/v1/packages/{id}")[1]["name"], "My Test Arena")
        code, result = self.send("GET", f"/v1/packages/{id}/verify")
        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])

    def test_http_auth_and_wrong_native_kind(self):
        code, raw = self.send("POST", "/v1/native", b"terrain-binary", {
            "Content-Type": "application/octet-stream", "X-REA-Kind": "terrain", "X-REA-Name": "tile"
        })
        self.assertEqual(code, 201)
        self.assertEqual(raw["kind"], "terrain")
        self.assertEqual(self.store.read_native(raw["native_id"]), b"terrain-binary")
        code, err = self.send("POST", "/v1/native", b"bad-kind", {
            "Content-Type": "application/octet-stream", "X-REA-Kind": "script"
        })
        self.assertEqual(code, 400)
        self.assertIn("kind", err["error"])


if __name__ == "__main__":
    unittest.main()
