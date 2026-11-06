"""v0.4 relationship preservation, read-only doctor and bridge tests."""

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
from roblox_rea.audit import audit_reconstruction
from roblox_rea.bridge import REABridge
from roblox_rea.cli import main
from roblox_rea.doctor import plan_repairs
from roblox_rea.schema import SceneError, validate_scene
from roblox_rea.storage import CaptureStore

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_scene.json"
PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "RobloxREA.plugin.lua"


def with_linked_parts():
    scene = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    source = scene["nodes"][0]
    source["name"] = "Arena"
    scene["nodes"].extend([
        {"id": "n4", "name": "Weld", "class": "WeldConstraint", "parent_id": "n1",
         "path": "root/WeldConstraint:Weld[1]", "properties": {},
         "references": {"Part0": "n2", "Part1": "n3"}},
        {"id": "n5", "name": "Connector", "class": "Attachment", "parent_id": "n2",
         "path": "root/Part:Floor[1]/Attachment:Connector[1]", "properties": {}},
        {"id": "n6", "name": "Connector", "class": "Attachment", "parent_id": "n3",
         "path": "root/Part:Goal[1]/Attachment:Connector[1]", "properties": {}},
        {"id": "n7", "name": "Constraint", "class": "HingeConstraint", "parent_id": "n1",
         "path": "root/HingeConstraint:Constraint[1]", "properties": {},
         "references": {"Attachment0": "n5", "Attachment1": "n6"}},
    ])
    return validate_scene(scene)


class ReferencesTests(unittest.TestCase):
    def setUp(self):
        self.ref = with_linked_parts()

    def test_valid_links_and_audit(self):
        report = audit_reconstruction(self.ref)
        self.assertEqual(report["internal_object_references"], 4)
        self.assertEqual(report["unsupported_classes"], {})
        self.assertEqual(report["placeholder_classes"], {})

    def test_dangling_reference_rejected(self):
        scene = copy.deepcopy(self.ref)
        scene["nodes"][3]["references"]["Part0"] = "not-found"
        with self.assertRaisesRegex(SceneError, "dangling reference"):
            validate_scene(scene)

    def test_non_referenceable_node_rejected(self):
        scene = copy.deepcopy(self.ref)
        scene["nodes"][1]["references"] = {"Part0": "n3"}
        with self.assertRaisesRegex(SceneError, "disallowed reference"):
            validate_scene(scene)

    def test_reference_target_type_rejected(self):
        scene = copy.deepcopy(self.ref)
        scene["nodes"][6]["references"]["Attachment0"] = "n2"
        with self.assertRaisesRegex(SceneError, "incompatible reference"):
            validate_scene(scene)

    def test_external_link_captured_but_not_auto_restored(self):
        scene = copy.deepcopy(self.ref)
        scene["nodes"][3]["external_references"] = ["Part0"]
        scene["nodes"][3]["references"].pop("Part0")
        validate_scene(scene)
        self.assertEqual(audit_reconstruction(scene)["external_object_references"]["count"], 1)
        broken = copy.deepcopy(scene)
        broken["nodes"][3]["external_references"] = ["Part1"]
        with self.assertRaises(SceneError):
            validate_scene(broken)

    def test_compare_reference_only(self):
        scene = copy.deepcopy(self.ref)
        scene["nodes"][3]["references"].pop("Part1")
        result = compare_scenes(self.ref, scene)
        self.assertEqual(result["counts"]["modified"], 1)
        self.assertEqual(result["modified_details"][0]["changes"]["references"]["before"]["Part1"],
                         "root/Part:Goal[1]")

    def test_reference_id_reorder_does_not_trigger_false_change(self):
        scene = copy.deepcopy(self.ref)
        scene["nodes"][2]["id"] = "nX"
        scene["nodes"][3]["references"]["Part1"] = "nX"
        scene["nodes"][5]["parent_id"] = "nX"
        self.assertEqual(compare_scenes(self.ref, validate_scene(scene))["counts"]["modified"], 0)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.ref = with_linked_parts()

    def test_property_and_reference_plan(self):
        target = copy.deepcopy(self.ref)
        target["nodes"][1]["properties"]["material"] = "Slate"
        target["nodes"][1]["properties"]["can_collide"] = False
        target["nodes"][3]["references"]["Part1"] = "n2"
        report = plan_repairs(self.ref, target)
        self.assertEqual(report["counts"]["planned"], 3)
        kinds = {op["op"] for op in report["operations"]}
        self.assertEqual(kinds, {"set_property", "set_reference"})
        self.assertEqual(len(report["plan_id"]), 64)
        self.assertEqual(report["safety"].startswith("PREVIEW ONLY"), True)

    def test_ids_and_created_at_ignored_for_stale_hash(self):
        scene = copy.deepcopy(self.ref)
        r1 = plan_repairs(self.ref, scene)
        scene["capture_id"] = "f" * 32
        scene["captured_at"] = 20210101
        self.assertEqual(r1["plan_id"], plan_repairs(self.ref, scene)["plan_id"])

    def test_stale_change_changes_plan_id(self):
        scene = copy.deepcopy(self.ref)
        report = plan_repairs(self.ref, scene)
        scene["nodes"][1]["properties"]["can_collide"] = False
        self.assertNotEqual(report["plan_id"], plan_repairs(self.ref, scene)["plan_id"])

    def test_does_not_delete_extra_or_guess_missing_mesh(self):
        ref = copy.deepcopy(self.ref)
        mesh = {"id": "n8", "parent_id": "n1", "class": "MeshPart", "name": "CustomMesh",
                "path": "root/MeshPart:CustomMesh[1]", "properties": {"mesh_id": "rbxassetid://123"}}
        ref["nodes"].append(mesh)
        target = copy.deepcopy(self.ref)
        target["nodes"].append({"id": "n9", "parent_id": "n1", "class": "Script",
                                "name": "ExtraScript", "path": "root/Script:ExtraScript[1]", "properties": {}})
        plan = plan_repairs(ref, target)
        self.assertEqual(plan["counts"]["missing"], 1)
        self.assertEqual(plan["counts"]["extra_preserved"], 1)
        self.assertEqual(plan["counts"]["planned"], 0)
        self.assertEqual(plan["blocked"][0]["reason"], "missing_object")

    def test_referent_missing_requires_hybrid(self):
        current = copy.deepcopy(self.ref)
        current["nodes"] = [n for n in current["nodes"] if n["id"] != "n3"]
        for node in current["nodes"]:
            if node["id"] == "n4":
                node["references"].pop("Part1")
            if node["id"] == "n6":
                node["parent_id"] = "n1"
        # n7 still references n6. Other constraints stay internally valid.
        p = plan_repairs(self.ref, current)
        self.assertGreaterEqual(p["counts"]["missing"], 1)
        self.assertEqual(p["counts"]["planned"], 0)
        self.assertTrue(any(x["reason"] == "missing_reference_target" for x in p["blocked"]))

    def test_unsafe_asset_and_unknown_class_properties_never_executed(self):
        ref = copy.deepcopy(self.ref)
        ref["nodes"][0]["properties"] = {"source": "script code that must not execute"}
        target = copy.deepcopy(ref)
        target["nodes"][0]["properties"] = {}
        p = plan_repairs(ref, target)
        self.assertEqual(p["counts"]["planned"], 0)
        self.assertEqual(p["blocked"][0]["reason"], "unsupported_property")

    def test_limit_and_negative_validation(self):
        with self.assertRaises(ValueError):
            plan_repairs(self.ref, self.ref, True)
        scene = copy.deepcopy(self.ref)
        scene["nodes"][1]["properties"]["anchored"] = False
        scene["nodes"][1]["properties"]["can_collide"] = False
        p = plan_repairs(self.ref, scene, limit=1)
        self.assertEqual(len(p["operations"]), 1)
        self.assertTrue(p["truncated"])

    def test_studio_plugin_contains_verification_and_undo(self):
        s = PLUGIN.read_text(encoding="utf-8")
        self.assertIn('"/v1/repair/"', s)
        self.assertIn('plan.plan_id == currentRepair.id', s)
        self.assertIn('confirmRepair.Text == "APPLY REPAIR"', s)
        self.assertIn('"Hybrid rescue stage"', s)
        self.assertIn('recordChanges("Approved map repair"', s)
        self.assertIn('REFERENCE_FIELDS', s)
        self.assertIn('clearDiffMarkers()', s)
        self.assertIn('Unloading:Connect', s)
        self.assertIn('Instance.new("Highlight")', s)
        self.assertIn('object[field] = target', s)


class DoctorBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CaptureStore(Path(self.temp.name))
        self.ref = with_linked_parts()
        self.capture = self.store.save_capture(self.ref)["capture_id"]
        self.server = REABridge(0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def send(self, path, body, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request("POST", path, body, headers or {"X-REA-Token": self.server.token, "Content-Type": "application/json"})
        res = conn.getresponse()
        code, raw = res.status, res.read()
        conn.close()
        return code, json.loads(raw)

    def test_http_repair_is_authenticated_and_read_only(self):
        altered = copy.deepcopy(self.ref)
        altered["nodes"][1]["properties"]["material"] = "Brick"
        path = f"/v1/repair/{self.capture}"
        code, doc = self.send(path, json.dumps(altered).encode())
        self.assertEqual(code, 200)
        self.assertEqual(doc["counts"]["planned"], 1)
        self.assertEqual(len(self.store.list_captures()), 1)
        self.assertEqual(self.store.read_capture(self.capture)["nodes"][1]["properties"]["material"], "Grass")
        self.assertEqual(self.send(path, json.dumps(altered).encode(), headers={"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self.send("/v1/repair/not-an-id", json.dumps(altered).encode())[0], 400)
        self.assertEqual(self.send("/v1/repair/" + "0"*32, json.dumps(altered).encode())[0], 404)

    def test_http_repair_requires_valid_scene_and_json(self):
        path = f"/v1/repair/{self.capture}"
        code, _ = self.send(path, b"{}")
        self.assertEqual(code, 400)
        code, _ = self.send(path, b"{}", headers={"X-REA-Token": self.server.token, "Content-Type": "text/plain"})
        self.assertEqual(code, 415)

    def test_cli_doctor_files(self):
        target = copy.deepcopy(self.ref)
        target["nodes"][1]["properties"]["color"] = [0.2, 0.3, 0.4]
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "ref.json", Path(d) / "current.json"
            a.write_text(json.dumps(self.ref), encoding="utf-8")
            b.write_text(json.dumps(target), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["doctor", str(a), str(b), "--files"]), 0)
            self.assertEqual(json.loads(output.getvalue())["counts"]["planned"], 1)


if __name__ == "__main__":
    unittest.main()
