from __future__ import annotations

import json
import unittest
from pathlib import Path

from function.visual_comparison import (
    VIEW_MODES,
    build_comparison_report,
    compute_slice,
    extract_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_source" / "visual_comparison_examples"


class VisualComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = sorted(str(path) for path in (EXAMPLES / "before").iterdir() if path.is_file())
        self.after = sorted(str(path) for path in (EXAMPLES / "after").iterdir() if path.is_file())

    def test_snapshot_keeps_geometry_and_hash_for_visualization(self) -> None:
        snapshot = extract_snapshot(EXAMPLES / "before" / "tunnel_model.obj")
        self.assertTrue(snapshot.parse_ok)
        self.assertEqual(8, len(snapshot.vertices))
        self.assertEqual(6, len(snapshot.faces))
        self.assertEqual(64, len(snapshot.sha256))
        self.assertEqual(100.0, snapshot.bounds.span_x)

    def test_cube_slice_has_real_profile_area_and_perimeter(self) -> None:
        snapshot = extract_snapshot(EXAMPLES / "before" / "tunnel_model.obj")
        profile = compute_slice(snapshot.vertices, snapshot.faces, axis="XY", position=1010.0)
        self.assertEqual(4, len(profile.points))
        self.assertAlmostEqual(5000.0, profile.area, places=5)
        self.assertAlmostEqual(300.0, profile.perimeter, places=5)

    def test_report_contains_all_four_real_visualization_modes(self) -> None:
        report = build_comparison_report(self.before, self.after, slice_axis="XY", slice_ratio=0.5)
        self.assertEqual("2.0", report["schema_version"])
        self.assertEqual(list(VIEW_MODES), report["visualization_summary"]["modes"])
        self.assertEqual(3, report["visualization_summary"]["pair_count"])
        self.assertGreater(report["visualization_summary"]["heatmap_points"], 0)
        self.assertEqual(1, report["visualization_summary"]["slice_profiles"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in report["files_before"] + report["files_after"]))

    def test_five_percent_example_baseline_is_current(self) -> None:
        baseline = json.loads((EXAMPLES / "expected_report_5percent.json").read_text(encoding="utf-8"))
        expected = baseline["expected"]
        report = build_comparison_report(
            self.before, self.after,
            coordinate_threshold=0.05, extent_threshold=0.05, scale_threshold=0.05,
            attribute_threshold=0.05, boundary_threshold=0.05,
            slice_axis="XY", slice_ratio=0.5, heatmap_limit=800,
        )
        self.assertEqual(expected["score"], report["score"])
        self.assertEqual(expected["total_checks"], report["total_checks"])
        self.assertEqual(expected["passed_checks"], report["passed_checks"])
        self.assertEqual(expected["heatmap_points"], report["visualization_summary"]["heatmap_points"])

    def test_obj_pair_slice_and_heatmap_quantify_known_change(self) -> None:
        before = [str(EXAMPLES / "before" / "tunnel_model.obj")]
        after = [str(EXAMPLES / "after" / "tunnel_model.obj")]
        report = build_comparison_report(before, after, slice_axis="XY", slice_ratio=0.5)
        visual = report["visualizations"][0]
        section = visual["slice_comparison"]
        heatmap = visual["difference_heatmap"]
        self.assertAlmostEqual(5000.0, section["before"]["area"], places=5)
        self.assertAlmostEqual(5050.0, section["after"]["area"], places=5)
        self.assertAlmostEqual(0.01, section["area_deviation"], places=6)
        self.assertAlmostEqual(3.0, heatmap["max_distance"], places=6)
        self.assertGreater(heatmap["p95_distance"], 0)

    def test_two_dimensional_geojson_overlay_and_attribute_loss(self) -> None:
        before = [str(EXAMPLES / "before" / "geologic_boundary.geojson")]
        after = [str(EXAMPLES / "after" / "geologic_boundary.geojson")]
        report = build_comparison_report(before, after)
        overlay = report["visualizations"][0]["two_dimensional_overlay"]
        self.assertEqual(5, len(overlay["before_points"]))
        self.assertEqual(5, len(overlay["after_points"]))
        losses = [item for item in report["comparisons"] if item["metric"].endswith("丢失属性字段")]
        self.assertEqual(1, len(losses))
        self.assertIn("source", losses[0]["value_before"])

    def test_slice_axis_and_ratio_are_respected(self) -> None:
        before = [str(EXAMPLES / "before" / "tunnel_model.obj")]
        after = [str(EXAMPLES / "after" / "tunnel_model.obj")]
        report = build_comparison_report(before, after, slice_axis="YZ", slice_ratio=0.25)
        section = report["visualizations"][0]["slice_comparison"]
        self.assertEqual("YZ", section["axis"])
        self.assertAlmostEqual(500025.75, section["position"], places=6)
        self.assertEqual(4, len(section["before"]["points"]))

    def test_unmatched_file_is_explicit_failure_not_self_comparison(self) -> None:
        report = build_comparison_report([self.before[0]], [])
        self.assertEqual(1, report["total_checks"])
        self.assertEqual(0, report["passed_checks"])
        self.assertIn("转换后文件缺失", report["comparisons"][0]["message"])
        self.assertEqual([], report["visualizations"][0]["difference_heatmap"]["points"])

    def test_empty_input_has_zero_pairs_and_no_fabricated_score(self) -> None:
        report = build_comparison_report([], [])
        self.assertEqual(0, report["score"])
        self.assertEqual(0, report["total_checks"])
        self.assertEqual(0, report["visualization_summary"]["pair_count"])


if __name__ == "__main__":
    unittest.main()
