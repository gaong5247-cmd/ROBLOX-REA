import copy
import json
import math
import unittest
from pathlib import Path

from roblox_rea.analysis import analyze_scene, compare_scenes, find_nodes
from roblox_rea.schema import SceneError, validate_scene

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_scene.json"


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.scene = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_valid_and_analyze(self):
        validate_scene(self.scene)
        report = analyze_scene(self.scene)
        self.assertEqual(report["node_count"], 3)
        self.assertEqual(report["class_counts"]["Part"], 2)
        self.assertEqual(report["collidable_parts"], 2)
        self.assertEqual(report["bounding_box"]["min"], [-20, -1, -20])
        self.assertEqual(report["bounding_box"]["max"], [20, 6, 20])

    def test_find_and_diff(self):
        result = find_nodes(self.scene, "goal")
        self.assertEqual(len(result), 1)
        changed = copy.deepcopy(self.scene)
        changed["nodes"][2]["properties"]["material"] = "Glass"
        self.assertEqual(compare_scenes(self.scene, changed)["counts"]["modified"], 1)
        changed["nodes"].pop()
        self.assertEqual(compare_scenes(self.scene, changed)["counts"]["removed"], 1)

    def test_cycle_rejected(self):
        bad = copy.deepcopy(self.scene)
        bad["nodes"][0]["parent_id"] = "n2"
        with self.assertRaises(SceneError):
            validate_scene(bad)

    def test_dangling_parent(self):
        bad = copy.deepcopy(self.scene)
        bad["nodes"][1]["parent_id"] = "nosuch"
        with self.assertRaises(SceneError):
            validate_scene(bad)

    def test_nonfinite_float(self):
        bad = copy.deepcopy(self.scene)
        bad["nodes"][1]["properties"]["size"][0] = float("nan")
        with self.assertRaises(SceneError):
            validate_scene(bad)

    def test_duplicate_id(self):
        bad = copy.deepcopy(self.scene)
        bad["nodes"][2]["id"] = "n2"
        with self.assertRaises(SceneError):
            validate_scene(bad)


if __name__ == "__main__":
    unittest.main()
