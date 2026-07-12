from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from function.model_format_conversion import convert_model_files
from function.model_quality_check import QualityRules, SUPPORTED_FORMATS, build_model_quality_report


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "example_source" / "model_quality"


class ModelQualityCheckTests(unittest.TestCase):
    def test_closed_mesh_formats_pass_geometry_and_topology(self) -> None:
        for suffix in ("obj", "stl", "ply", "vtk"):
            with self.subTest(suffix=suffix):
                report = build_model_quality_report([str(SAMPLES / f"model_quality_closed_mesh.{suffix}")])
                statuses = {item["key"]: item["status"] for item in report["categories"]}
                self.assertEqual("通过", statuses["geometry"])
                self.assertEqual("通过", statuses["topology"])
                self.assertTrue(report["files"][0]["supported"])
                self.assertGreater(report["files"][0]["metrics"]["vertex_count"], 0)

    def test_valid_attribute_table_and_ifc_are_supported(self) -> None:
        paths = [SAMPLES / "model_quality_valid_attributes.csv", SAMPLES / "model_quality_valid.ifc"]
        report = build_model_quality_report([str(path) for path in paths])
        self.assertEqual(2, report["file_count"])
        self.assertTrue(all(item["supported"] for item in report["files"]))
        self.assertNotIn("PARSE_ERROR", {issue["code"] for issue in report["issues"]})

    def test_fault_samples_have_stable_codes_locations_and_suggestions(self) -> None:
        paths = [
            SAMPLES / "model_quality_open_mesh.obj",
            SAMPLES / "model_quality_attributes.csv",
            SAMPLES / "model_quality_boundary.geojson",
        ]
        report = build_model_quality_report([str(path) for path in paths])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertTrue({"OPEN_BOUNDARY", "DUPLICATE_ID", "MISSING_ATTRIBUTE", "INVALID_COORDINATE", "COORDINATE_RANGE"}.issubset(codes))
        for issue in report["issues"]:
            self.assertRegex(issue["issue_id"], r"^Q-\d{4}$")
            self.assertTrue(issue["location"])
            self.assertTrue(issue["suggestion"])

    def test_required_attributes_and_coordinate_precision_are_configurable(self) -> None:
        rules = QualityRules(required_attributes=("lithology", "density"), minimum_decimal_places=3)
        report = build_model_quality_report([str(SAMPLES / "model_quality_attributes.csv")], rules)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("MISSING_ATTRIBUTE", codes)
        self.assertIn("COORDINATE_PRECISION", codes)
        self.assertEqual(3, report["parameters"]["minimum_decimal_places"])

    def test_no_input_is_not_reported_as_success(self) -> None:
        report = build_model_quality_report([])
        self.assertEqual("待检查", report["grade"])
        self.assertFalse(report["passed"])
        self.assertEqual(0, report["file_count"])

    def test_unknown_format_is_explicitly_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.las"
            path.write_text("placeholder", encoding="utf-8")
            report = build_model_quality_report([str(path)])
        self.assertIn("UNSUPPORTED_FORMAT", {issue["code"] for issue in report["issues"]})
        self.assertFalse(report["files"][0]["supported"])

    def test_supported_format_contract_matches_outputs(self) -> None:
        self.assertTrue({".obj", ".stl", ".ply", ".vtk", ".geojson", ".csv", ".ifc"}.issubset(SUPPORTED_FORMATS))

    def test_quality_parser_accepts_every_converter_output(self) -> None:
        source = ROOT / "example_source" / "model_format_conversion" / "01_封闭地质块体.obj"
        with tempfile.TemporaryDirectory() as directory:
            outputs: list[str] = []
            for target in ("OBJ", "STL", "PLY", "VTK", "GEOJSON", "CSV", "IFC"):
                conversion = convert_model_files([str(source)], Path(directory) / target.lower(), target, overwrite=True)
                self.assertEqual(1, conversion["success_count"], target)
                outputs.extend(str(item["output"]) for item in conversion["artifacts"])
            report = build_model_quality_report(outputs)
        self.assertEqual(7, report["file_count"])
        self.assertNotIn("PARSE_ERROR", {issue["code"] for issue in report["issues"]})
        self.assertNotIn("UNSUPPORTED_FORMAT", {issue["code"] for issue in report["issues"]})
        self.assertTrue(all(item["supported"] for item in report["files"]))


if __name__ == "__main__":
    unittest.main()
