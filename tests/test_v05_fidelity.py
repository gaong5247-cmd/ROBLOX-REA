"""v0.5 structured fidelity checks, Studio script metadata and authenticated local API."""

import contextlib
import copy
import http.client
import io
import json
import math
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from roblox_rea.bridge import REABridge
from roblox_rea.cli import main
from roblox_rea.fidelity import assess_fidelity
from roblox_rea.schema import SceneError, validate_scene
from roblox_rea.script_inventory import (
    INVENTORY_SCHEMA, validate_script_inventory, compare_script_inventories,
    summarize_script_inventory,
)
from roblox_rea.storage import CaptureStore

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/sample_scene.json"
PLUGIN = Path(__file__).resolve().parents[1] / "plugin/RobloxREA.plugin.lua"


def sample_scene():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def sample_inventory():
    return {
        "schema": INVENTORY_SCHEMA,
        "scope": "authorized-studio-project",
        "mode": "metadata-only",
        "includes_source": False,
        "place_id": 0,
        "captured_at": 1793980000,
        "items": [
            {"path": "ServerScriptService/Script:ServerMain[1]", "name": "ServerMain",
             "class": "Script", "service": "ServerScriptService", "enabled": True, "run_context": "Server"},
            {"path": "StarterPlayer/StarterPlayerScripts:StarterPlayerScripts[1]/LocalScript:ClientMain[1]",
             "name": "ClientMain", "class": "LocalScript", "service": "StarterPlayer", "enabled": True},
            {"path": "ReplicatedStorage/ModuleScript:Shared[1]", "name": "Shared",
             "class": "ModuleScript", "service": "ReplicatedStorage"},
        ],
    }


class FidelityTests(unittest.TestCase):
    def setUp(self):
        self.ref = sample_scene()

    def test_identical_is_metadata_match_not_certified_visual_match(self):
        report = assess_fidelity(self.ref, copy.deepcopy(self.ref))
        self.assertEqual(report["observed_status"], "match")
        self.assertEqual(report["counts"]["matching_nodes"], 3)
        self.assertEqual(report["measurements"]["node_coverage_percent"], 100)
        self.assertIn("metadata only", report["limitations"][0])

    def test_detects_missing_extra_and_class_drift(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"].pop()
        changed["nodes"][1]["class"] = "MeshPart"
        changed["nodes"].append({"id": "n9", "parent_id": "n1", "name": "Extra",
                                 "class": "Part", "path": "root/Part:Extra[1]", "properties": {}})
        result = assess_fidelity(self.ref, changed)
        self.assertEqual(result["counts"]["missing"], 1)
        self.assertEqual(result["counts"]["unexpected"], 1)
        self.assertEqual(result["counts"]["class_mismatches"], 1)
        self.assertEqual(result["observed_status"], "different")

    def test_ignores_small_position_rotation_size_jitter(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"][1]["properties"]["cframe"][0] += 0.01
        changed["nodes"][1]["properties"]["size"][0] += 0.01
        report = assess_fidelity(self.ref, changed)
        self.assertEqual(report["observed_status"], "match")
        self.assertAlmostEqual(report["measurements"]["maximum_position_error_studs"], 0.01)

    def test_detects_positional_drift(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"][1]["properties"]["cframe"][0] += 1.5
        report = assess_fidelity(self.ref, changed)
        self.assertEqual(report["counts"]["transform_mismatches"], 1)
        self.assertEqual(report["measurements"]["maximum_position_error_studs"], 1.5)
        self.assertEqual(report["changed_details"][0]["problems"][0]["kind"], "transform")

    def test_detects_rotation(self):
        changed = copy.deepcopy(self.ref)
        angle = math.radians(12)
        changed["nodes"][1]["properties"]["cframe"][3:] = [
            math.cos(angle), 0, -math.sin(angle), 0, 1, 0,
            math.sin(angle), 0, math.cos(angle),
        ]
        report = assess_fidelity(self.ref, changed)
        self.assertAlmostEqual(report["measurements"]["maximum_rotation_error_degrees"], 12, places=4)

    def test_size_and_property_changes(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"][1]["properties"]["size"][0] += 1
        changed["nodes"][1]["properties"]["material"] = "Glass"
        report = assess_fidelity(self.ref, changed)
        kinds = {p["kind"] for p in report["changed_details"][0]["problems"]}
        self.assertEqual(kinds, {"size", "property"})
        self.assertEqual(report["measurements"]["maximum_size_error_studs"], 1)

    def test_reference_ids_are_capture_local(self):
        ref = copy.deepcopy(self.ref)
        ref["nodes"].append({"id": "a", "parent_id": "n1", "name": "Connection", "class": "WeldConstraint",
                             "path": "root/WeldConstraint:Connection[1]", "properties": {},
                             "references": {"Part0": "n2", "Part1": "n3"}})
        other = copy.deepcopy(ref)
        other["nodes"][1]["id"] = "b"
        other["nodes"][2]["id"] = "c"
        other["nodes"][3]["references"] = {"Part0": "b", "Part1": "c"}
        report = assess_fidelity(ref, other)
        self.assertEqual(report["observed_status"], "match")
        self.assertEqual(report["counts"]["references_matched"], 2)
        other["nodes"][3]["references"]["Part1"] = "b"
        broken = assess_fidelity(ref, other)
        self.assertEqual(broken["counts"]["references_matched"], 1)
        self.assertEqual(broken["mismatch_types"].get("reference"), 1)

    def test_scripts_and_mesh_are_unverifiable(self):
        ref = copy.deepcopy(self.ref)
        ref["nodes"].append({"id": "n4", "parent_id": "n1", "name": "Client",
                             "class": "LocalScript", "path": "root/LocalScript:Client[1]", "properties": {}})
        ref["nodes"][1]["class"] = "MeshPart"
        report = assess_fidelity(ref, ref)
        self.assertEqual(report["unverifiable_class_counts"], {"MeshPart": 1, "LocalScript": 1})
        self.assertEqual(report["observed_status"], "match")

    def test_attribute_tag_external_ref_detection(self):
        ref = copy.deepcopy(self.ref)
        ref["nodes"][1]["tags"] = ["Arena"]
        ref["nodes"][1]["attributes"] = {"Level": 5}
        other = copy.deepcopy(ref)
        other["nodes"][1]["tags"] = ["ArenaB"]
        other["nodes"][1]["attributes"]["Level"] = 6
        report = assess_fidelity(ref, other)
        self.assertEqual(set(report["mismatch_types"]), {"tags", "attributes"})

    def test_invalid_args_and_limit_bounds(self):
        for kwargs in ({"position_tolerance": float('nan')}, {"rotation_tolerance": -1},
                       {"size_tolerance": True}, {"numeric_tolerance": float("inf")},
                       {"limit": 0}, {"limit": True}, {"limit": 101}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                assess_fidelity(self.ref, self.ref, **kwargs)

    def test_truncation(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"][1]["properties"]["anchored"] = False
        changed["nodes"][2]["properties"]["anchored"] = False
        result = assess_fidelity(self.ref, changed, limit=1)
        self.assertEqual(result["counts"]["changed"], 2)
        self.assertEqual(len(result["changed_details"]), 1)
        self.assertTrue(result["truncated"])

    def test_unshared_properties_not_claimed(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"][1]["properties"].pop("material")
        report = assess_fidelity(self.ref, changed)
        self.assertLess(report["measurements"]["observed_property_match_percent"], 100)


class InventoryTests(unittest.TestCase):
    def test_summary_by_service_class(self):
        m = sample_inventory()
        validate_script_inventory(m)
        x = summarize_script_inventory(m)
        self.assertEqual(x["count"], 3)
        self.assertEqual(x["by_class"], {"Script": 1, "LocalScript": 1, "ModuleScript": 1})
        self.assertFalse(x["includes_source"])

    def test_empty_authorized_inventory_allowed(self):
        m = sample_inventory()
        m["items"] = []
        self.assertEqual(summarize_script_inventory(m)["count"], 0)

    def test_rejects_source_payload_at_item_or_root(self):
        for field in ("source", "source_text", "bytecode", "Source"):
            m = sample_inventory()
            m["items"][0][field] = "print('sensitive')"
            with self.subTest(field=field), self.assertRaises(SceneError):
                validate_script_inventory(m)
        m = sample_inventory()
        m["source_code"] = "print(1)"
        with self.assertRaises(SceneError):
            validate_script_inventory(m)

    def test_rejects_false_scope_or_source_flag(self):
        for name, value in (("mode", "with-source"), ("scope", "remote-client"),
                            ("includes_source", True), ("place_id", True)):
            m = sample_inventory()
            m[name] = value
            with self.subTest(name=name), self.assertRaises(SceneError):
                validate_script_inventory(m)

    def test_rejects_duplicates_bogus_service_run_context(self):
        for change in (lambda m: m["items"].append(copy.deepcopy(m["items"][0])),
                       lambda m: m["items"][0].update(service="ServerStorage"),
                       lambda m: m["items"][0].update(run_context="Arbitrary"),
                       lambda m: m["items"][1].update(run_context="Server")):
            m = sample_inventory()
            change(m)
            with self.assertRaises(SceneError):
                validate_script_inventory(m)

    def test_rejects_oversized_script_metadata(self):
        m = sample_inventory()
        m["items"] = []
        for i in range(6000):
            m["items"].append({"path": "ReplicatedStorage/ModuleScript:" + ("A" * 170) + f"{i}",
                               "name": "X", "class": "ModuleScript", "service": "ReplicatedStorage"})
        with self.assertRaisesRegex(SceneError, "1 MiB"):
            validate_script_inventory(m)

    def test_inventory_diff(self):
        a = sample_inventory()
        b = copy.deepcopy(a)
        b["items"].pop()
        b["items"][0]["enabled"] = False
        x = compare_script_inventories(a, b)
        self.assertEqual(x["counts"], {"missing": 1, "added": 0, "metadata_changed": 1})
        self.assertFalse(x["source_code_verified"])

    def test_invalid_comparison_limit(self):
        with self.assertRaises(ValueError):
            compare_script_inventories(sample_inventory(), sample_inventory(), limit=False)


class StorageAndBridgeV05Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CaptureStore(Path(self.temp.name))
        self.ref = sample_scene()
        self.capture_id = self.store.save_capture(self.ref)["capture_id"]
        self.server = REABridge(0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self, method, path, body=None, *, token=True, content_type="application/json", origin=None):
        headers = {"Content-Type": content_type}
        if token:
            headers["X-REA-Token"] = self.server.token
        if origin:
            headers["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        conn.request(method, path, body, headers)
        res = conn.getresponse()
        status, raw = res.status, res.read()
        conn.close()
        return status, json.loads(raw)

    def test_script_inventory_roundtrip(self):
        code, doc = self.send("POST", "/v1/scripts", json.dumps(sample_inventory()).encode())
        self.assertEqual(code, 201)
        self.assertEqual(doc["count"], 3)
        ident = doc["inventory_id"]
        self.assertEqual(self.send("GET", f"/v1/scripts/{ident}")[1]["items"], sample_inventory()["items"])
        self.assertEqual(self.send("GET", f"/v1/scripts/{ident}/summary")[1]["count"], 3)
        self.assertEqual(self.send("GET", "/v1/scripts")[1]["items"][0]["inventory_id"], ident)
        self.assertEqual(self.store.read_script_inventory(ident)["includes_source"], False)

    def test_script_inventory_forbids_code(self):
        m = sample_inventory()
        m["items"][0]["source"] = "secret_code"
        self.assertEqual(self.send("POST", "/v1/scripts", json.dumps(m).encode())[0], 400)
        self.assertEqual(self.store.list_script_inventories(), [])

    def test_script_inventory_auth_and_mime(self):
        raw = json.dumps(sample_inventory()).encode()
        self.assertEqual(self.send("POST", "/v1/scripts", raw, token=False)[0], 401)
        self.assertEqual(self.send("POST", "/v1/scripts", raw, origin="http://untrusted.example")[0], 403)
        self.assertEqual(self.send("POST", "/v1/scripts", raw, content_type="text/plain")[0], 415)
        self.assertEqual(self.send("GET", "/v1/scripts", token=False)[0], 401)

    def test_script_inventory_path_traversal_is_rejected(self):
        self.assertEqual(self.send("GET", "/v1/scripts/../../etc/passwd")[0], 400)

    def test_fidelity_live_is_read_only(self):
        changed = copy.deepcopy(self.ref)
        changed["nodes"][1]["properties"]["material"] = "Glass"
        code, report = self.send("POST", f"/v1/fidelity/{self.capture_id}", json.dumps(changed).encode())
        self.assertEqual(code, 200)
        self.assertEqual(report["observed_status"], "different")
        self.assertEqual(report["counts"]["changed"], 1)
        self.assertEqual(len(self.store.list_captures()), 1)
        self.assertEqual(self.store.read_capture(self.capture_id)["nodes"][1]["properties"]["material"], "Grass")

    def test_fidelity_invalid_scene_or_auth(self):
        data = json.dumps(self.ref).encode()
        self.assertEqual(self.send("POST", f"/v1/fidelity/{self.capture_id}", data, token=False)[0], 401)
        self.assertEqual(self.send("POST", f"/v1/fidelity/{self.capture_id}", b"{}",)[0], 400)
        self.assertEqual(self.send("POST", f"/v1/fidelity/{'f'*32}", data)[0], 404)

    def test_storage_rejects_tampered_inventory_and_id(self):
        i = self.store.save_script_inventory(sample_inventory())["inventory_id"]
        file = self.store.script_inventories / (i + ".json")
        j = json.loads(file.read_text())
        j["includes_source"] = True
        file.write_text(json.dumps(j))
        with self.assertRaises(SceneError):
            self.store.read_script_inventory(i)
        with self.assertRaises(SceneError):
            self.store.read_script_inventory("../etc/passwd")

    def test_cli_fidelity_and_inventory_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            outfile = Path(tmp) / "restored.json"
            outfile.write_text(json.dumps(self.ref), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["fidelity", str(EXAMPLE), str(outfile), "--files"]), 0)
            self.assertEqual(json.loads(out.getvalue())["observed_status"], "match")
        with patch.dict(os.environ, {"REA_RBX_DATA_DIR": str(self.store.root)}):
            self.store.save_script_inventory(sample_inventory())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["scripts"]), 0)
            self.assertEqual(len(json.loads(out.getvalue())), 1)


class PluginContractV05Tests(unittest.TestCase):
    def test_studio_buttons_are_read_only_for_fidelity_and_source(self):
        lua = PLUGIN.read_text(encoding="utf-8")
        self.assertIn("15 · VERIFY map fidelity", lua)
        self.assertIn("16 · Inventory server/client scripts (NO source)", lua)
        self.assertIn("includes_source = false", lua)
        self.assertNotIn("ScriptEditorService:GetEditorSource", lua)
        self.assertIn('"/v1/fidelity/"', lua)
        self.assertIn('"/v1/scripts"', lua)


if __name__ == "__main__":
    unittest.main()
