"""v0.2 spatial analytics, safety audit, SVG preview and HTTP compare tests."""

import copy
import http.client
import json
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from roblox_rea.analysis import compare_scenes
from roblox_rea.audit import audit_reconstruction
from roblox_rea.bridge import REABridge
from roblox_rea.preview import render_svg
from roblox_rea.schema import SceneError, validate_scene
from roblox_rea.spatial import part_bounds, query_nearby
from roblox_rea.storage import CaptureStore

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_scene.json"


class SpatialAndAuditTests(unittest.TestCase):
    def setUp(self):
        self.scene = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_query_nearby_goal(self):
        result = query_nearby(self.scene, 0, 3, 19, 0.1)
        self.assertEqual(result["matches_total"], 1)
        self.assertEqual(result["matches"][0]["name"], "Goal")
        self.assertEqual(result["matches"][0]["distance_to_bounds"], 0)

    def test_query_finds_floor_by_bbox_not_center(self):
        result = query_nearby(self.scene, 19, 0, -19, 0.1, collidable_only=True)
        self.assertEqual([n["name"] for n in result["matches"]], ["Floor"])
        self.assertEqual(result["matches"][0]["center"], [0.0, -0.5, 0.0])

    def test_rotated_aabb(self):
        part = {"properties": {
            "size": [2, 4, 8],
            "cframe": [0, 0, 0, 0, 0, 1, 0, 1, 0, -1, 0, 0],
        }}
        self.assertEqual(part_bounds(part), ([-4.0, -2.0, -1.0], [4.0, 2.0, 1.0]))

    def test_query_sort_and_limit(self):
        result = query_nearby(self.scene, 0, 3, 19, 20, limit=1)
        self.assertEqual(result["matches_total"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["matches"][0]["name"], "Goal")

    def test_query_rejects_nonfinite_and_bad_limits(self):
        for kwargs in ({"x": float("nan")}, {"radius": float("inf")},
                       {"radius": -1}, {"limit": 0}, {"limit": 101},
                       {"limit": True}, {"collidable_only": 1}):
            params = {"x": 0, "y": 0, "z": 0, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                query_nearby(self.scene, **params)

    def test_audit_identifies_placeholders_unsupported_and_assets(self):
        scene = copy.deepcopy(self.scene)
        scene["nodes"][1]["class"] = "MeshPart"
        scene["nodes"][1]["properties"]["mesh_id"] = "rbxassetid://1234"
        scene["nodes"][2]["class"] = "Script"
        scene["nodes"][2]["properties"] = {}
        result = audit_reconstruction(scene)
        self.assertEqual(result["placeholder_classes"], {"MeshPart": 1})
        self.assertEqual(result["unsupported_classes"], {"Script": 1})
        self.assertEqual(result["supported_nodes"], 2)
        self.assertEqual(result["missing_geometry_properties"]["count"], 0)
        self.assertEqual(result["asset_references"]["items"][0]["reference"], "rbxassetid://1234")

    def test_audit_missing_geometry_and_truncated_assets(self):
        scene = copy.deepcopy(self.scene)
        scene["nodes"][1]["properties"].pop("size")
        scene["nodes"][2]["properties"]["texture_id"] = "rbxassetid://5"
        scene["nodes"][1]["properties"]["texture_id"] = "rbxassetid://6"
        result = audit_reconstruction(scene, limit=1)
        self.assertEqual(result["missing_geometry_properties"]["count"], 1)
        self.assertEqual(result["asset_references"]["count"], 2)
        self.assertTrue(result["truncated"])

    def test_svg_is_standalone_valid_xml_and_escapes_names(self):
        scene = copy.deepcopy(self.scene)
        scene["scene_name"] = "<script>alert('x')</script> & map"
        scene["nodes"][2]["name"] = '<img onerror="oops">'
        svg = render_svg(scene)
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertNotIn("<script>", svg)
        self.assertNotIn("<img", svg)
        self.assertIn("&lt;script&gt;", svg)
        self.assertEqual(len(root.findall("{http://www.w3.org/2000/svg}polygon")), 2)
        self.assertNotIn("http://www.", svg.replace('http://www.w3.org/2000/svg', ''))

    def test_svg_projection_rotation_and_part_limit(self):
        scene = copy.deepcopy(self.scene)
        scene["nodes"][2]["properties"]["cframe"] = [0, 3, 0, 0, 0, 1, 0, 1, 0, -1, 0, 0]
        svg = render_svg(scene, max_parts=1)
        root = ET.fromstring(svg)
        self.assertEqual(len(root.findall("{http://www.w3.org/2000/svg}polygon")), 1)
        self.assertIn("1 / 2 projected parts", svg)

    def test_svg_rejects_no_geometry(self):
        scene = copy.deepcopy(self.scene)
        for node in scene["nodes"]:
            node["properties"] = {}
        with self.assertRaises(ValueError):
            render_svg(scene)

    def test_geometry_bounds_check(self):
        for key, value in (("size", [-1, 2, 3]), ("size", [1e10, 2, 3]),
                           ("color", [2, 0.3, 0.5]),
                           ("cframe", [1e90, 0, 0] + [1, 0, 0, 0, 1, 0, 0, 0, 1])):
            scene = copy.deepcopy(self.scene)
            scene["nodes"][1]["properties"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(SceneError):
                validate_scene(scene)

    def test_detailed_compare(self):
        scene2 = copy.deepcopy(self.scene)
        scene2["nodes"][1]["properties"]["material"] = "Slate"
        scene2["nodes"][1]["properties"].pop("anchored")
        report = compare_scenes(self.scene, scene2)
        self.assertEqual(report["counts"]["modified"], 1)
        delta = report["modified_details"][0]["changes"]["properties"]
        self.assertEqual(delta["material"]["before"], "Grass")
        self.assertEqual(delta["material"]["after"], "Slate")
        self.assertTrue(delta["anchored"]["before_present"])
        self.assertFalse(delta["anchored"]["after_present"])

    def test_audit_validates_limit(self):
        with self.assertRaises(ValueError):
            audit_reconstruction(self.scene, limit=0)


class BridgeV02Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CaptureStore(Path(self.temp.name))
        self.scene = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.capture = self.store.save_capture(self.scene)["capture_id"]
        self.server = REABridge(0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self, method, path, body=None, token=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {"X-REA-Token": self.server.token} if token else {}
        request_headers.update(headers or {})
        conn.request(method, path, body, request_headers)
        response = conn.getresponse()
        code, data = response.status, response.read()
        conn.close()
        return code, json.loads(data)

    def test_read_audit_endpoint(self):
        code, result = self.send("GET", f"/v1/captures/{self.capture}/audit")
        self.assertEqual(code, 200)
        self.assertEqual(result["supported_nodes"], 3)

    def test_compare_endpoint_is_read_only(self):
        after = copy.deepcopy(self.scene)
        after["nodes"][1]["properties"]["material"] = "Glass"
        code, report = self.send("POST", f"/v1/compare/{self.capture}",
                                 json.dumps(after).encode(), headers={"Content-Type": "application/json"})
        self.assertEqual(code, 200)
        self.assertEqual(report["counts"], {"added": 0, "removed": 0, "modified": 1})
        self.assertEqual(len(self.store.list_captures()), 1)
        self.assertEqual(self.store.read_capture(self.capture)["nodes"][1]["properties"]["material"], "Grass")

    def test_compare_authentication_and_invalid_id(self):
        body = json.dumps(self.scene).encode()
        self.assertEqual(self.send("POST", f"/v1/compare/{self.capture}", body, token=False,
                                   headers={"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self.send("POST", "/v1/compare/no-such-id", body,
                                   headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.send("POST", "/v1/compare/" + "f" * 32, body,
                                   headers={"Content-Type": "application/json"})[0], 404)

    def test_compare_rejects_invalid_scene(self):
        body = json.dumps({"schema": "unknown", "nodes": []}).encode()
        code, _ = self.send("POST", f"/v1/compare/{self.capture}", body,
                            headers={"Content-Type": "application/json"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
