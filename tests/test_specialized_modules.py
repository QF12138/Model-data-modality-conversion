from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from function.geospatial_common import read_obj
from function.specialized_modules import MODULE_SLUGS, example_directory, run_specialized_module


def example_files(module_name: str) -> list[str]:
    directory = example_directory(ROOT, module_name)
    return sorted(
        str(path) for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".csv", ".json", ".geojson", ".asc", ".obj", ".ply"}
    )


class SpecializedModuleTests(unittest.TestCase):
    def execute(self, module_name: str, parameters: dict[str, str] | None = None) -> tuple[dict, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        report = run_specialized_module(module_name, example_files(module_name), root, parameters)
        output_dir = root / MODULE_SLUGS[module_name]
        self.assertTrue(output_dir.is_dir())
        self.assertTrue(Path(report["manifest_path"]).is_file())
        self.assertTrue(report["outputs"])
        for artifact in report["artifacts"]:
            self.assertTrue(Path(artifact["path"]).is_file())
            self.assertEqual(64, len(artifact["sha256"]))
        return report, output_dir

    def test_coordinate_and_datum_unification(self) -> None:
        report, output = self.execute("坐标与基准统一模块")
        self.assertEqual(27, report["metrics"]["converted_points"])
        self.assertEqual(3, report["metrics"]["converted_files"])
        rows = (output / "survey_points_unified.csv").read_text(encoding="utf-8-sig").splitlines()
        self.assertIn("target_crs", rows[0])
        self.assertIn("EPSG:3857", rows[1])

    def test_section_and_map_positioning_with_topology(self) -> None:
        report, output = self.execute("剖面与平面图转换模块")
        self.assertGreaterEqual(report["metrics"]["output_features"], 10)
        topology = json.loads((output / "topology_check.json").read_text(encoding="utf-8"))
        self.assertTrue(topology["passed"])

    def test_geologic_line_reconstruction_joins_fragments(self) -> None:
        report, output = self.execute("地质解释线重建模块")
        self.assertGreaterEqual(report["metrics"]["joined_gaps"], 7)
        self.assertGreaterEqual(report["metrics"]["reconstructed_parts"], 6)
        self.assertGreater(report["metrics"]["anomaly_endpoints"], 0)
        data = json.loads((output / "reconstructed_boundaries.geojson").read_text(encoding="utf-8"))
        self.assertGreater(len(data["features"][0]["geometry"]["coordinates"]), 7)

    def test_raster_vector_bidirectional_conversion(self) -> None:
        report, output = self.execute("栅格与矢量转换模块")
        self.assertEqual(2, report["metrics"]["raster_to_vector_files"])
        self.assertEqual(1, report["metrics"]["vector_to_raster_files"])
        self.assertTrue((output / "hazard_index_vectorized.geojson").is_file())
        self.assertTrue((output / "geology_polygons_rasterized.asc").is_file())

    def test_point_cloud_downsampling_and_classification(self) -> None:
        report, output = self.execute("点云数据转换模块")
        self.assertEqual(90, report["metrics"]["input_points"])
        self.assertLess(report["metrics"]["output_points"], 90)
        self.assertEqual({"ground", "slope_surface", "high_feature"}, set(report["metrics"]["classes"]))
        self.assertTrue((output / "classified_point_cloud.ply").is_file())

    def test_attribute_mapping_is_complete_and_traceable(self) -> None:
        report, output = self.execute("地质属性映射模块")
        self.assertEqual(63, report["metrics"]["mapped_values"])
        self.assertEqual(1.0, report["metrics"]["coverage_ratio"])
        lineage = (output / "attribute_mapping_lineage.csv").read_text(encoding="utf-8-sig")
        self.assertIn("sample_ids", lineage)
        self.assertIn("MAP-U-01-permeability", lineage)

    def test_multiscale_conversion_records_mesh_accuracy(self) -> None:
        report, output = self.execute("多尺度模型转换模块")
        self.assertEqual(2, report["metrics"]["model_count"])
        model = report["metrics"]["models"][0]
        self.assertGreater(model["output_faces"], 0)
        self.assertIn("max_vertex_error", model)
        self.assertTrue(any(path.suffix == ".obj" for path in output.iterdir()))

    def test_local_detail_increases_face_density_and_checks_quality(self) -> None:
        report, output = self.execute("局部精细模型构建模块")
        self.assertEqual(2, report["metrics"]["model_count"])
        self.assertEqual(4, report["metrics"]["constraint_features"])
        model = report["metrics"]["models"][0]
        self.assertGreater(model["output_faces"], model["source_faces"])
        self.assertEqual(0, model["degenerate_faces"])
        vertices, faces = read_obj(output / model["output"])
        self.assertEqual(model["output_vertices"], len(vertices))
        self.assertEqual(model["output_faces"], len(faces))


if __name__ == "__main__":
    unittest.main()
