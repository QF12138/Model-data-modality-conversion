from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from function.model_format_conversion import convert_model_files


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "example_source" / "model_format_conversion"


class ModelFormatConversionTests(unittest.TestCase):
    def test_every_target_is_written_atomically_and_roundtrip_validated(self) -> None:
        source = next(SAMPLES.glob("01_*.obj"))
        with tempfile.TemporaryDirectory() as directory:
            for target in ("OBJ", "STL", "PLY", "VTK", "GEOJSON", "CSV", "IFC"):
                with self.subTest(target=target):
                    output = Path(directory) / target.lower()
                    report = convert_model_files([str(source)], output, target, overwrite=True)
                    self.assertEqual("完成", report["status"])
                    artifact = report["artifacts"][0]
                    self.assertEqual("通过", artifact["validation"]["status"])
                    self.assertEqual(64, len(artifact["source_checksum_sha256"]))
                    self.assertEqual(64, len(artifact["output_checksum_sha256"]))
                    self.assertTrue(Path(artifact["output"]).is_file())
                    self.assertFalse(list(output.glob("*.tmp")))
                    manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
                    self.assertEqual(report["conversion_id"], manifest["conversion_id"])
                    self.assertEqual(report["manifest_path"], manifest["manifest_path"])

    def test_attribute_loss_is_explicit_and_sidecar_preserves_payload(self) -> None:
        source = next(SAMPLES.glob("03_*.ply"))
        with tempfile.TemporaryDirectory() as directory:
            report = convert_model_files([str(source)], directory, "OBJ", overwrite=True)
            artifact = report["artifacts"][0]
            self.assertTrue(artifact["information_losses"])
            self.assertEqual(1, len(artifact["sidecar_files"]))
            sidecar = json.loads(Path(artifact["sidecar_files"][0]).read_text(encoding="utf-8"))
        self.assertEqual(5, len(sidecar["vertex_properties"]))
        self.assertIn("lithology_code", sidecar["vertex_properties"][0])
        self.assertEqual(artifact["output"].split("\\")[-1], sidecar["primary_artifact"])

    def test_coordinate_translation_is_recorded_and_reversible(self) -> None:
        source = next(SAMPLES.glob("01_*.obj"))
        with tempfile.TemporaryDirectory() as directory:
            report = convert_model_files([str(source)], directory, "VTK", coordinate_rule="平移到局部原点", overwrite=True)
            artifact = report["artifacts"][0]
        self.assertEqual([500000.0, 3400000.0, 100.0], artifact["coordinate_transform"]["offset"])
        self.assertEqual([0.0, 0.0, 0.0], artifact["bounds"]["min"])
        self.assertEqual("通过", artifact["validation"]["status"])

    def test_point_data_to_surface_only_formats_fails_without_partial_output(self) -> None:
        source = next(SAMPLES.glob("06_*.csv"))
        with tempfile.TemporaryDirectory() as directory:
            for target in ("STL", "IFC"):
                with self.subTest(target=target):
                    output = Path(directory) / target.lower()
                    report = convert_model_files([str(source)], output, target, overwrite=True)
                    self.assertEqual("失败", report["status"])
                    self.assertEqual(0, report["success_count"])
                    self.assertFalse([path for path in output.iterdir() if path.suffix.lower() in {".stl", ".ifc"}])
                    self.assertFalse(list(output.glob("*.tmp")))

    def test_invalid_source_does_not_leave_partial_artifact(self) -> None:
        source = next(SAMPLES.glob("07_*.obj"))
        with tempfile.TemporaryDirectory() as directory:
            report = convert_model_files([str(source)], directory, "OBJ", overwrite=True)
            self.assertEqual("失败", report["status"])
            self.assertFalse(list(Path(directory).glob("*_converted.obj")))

    def test_existing_outputs_receive_unique_names_when_overwrite_is_disabled(self) -> None:
        source = next(SAMPLES.glob("01_*.obj"))
        with tempfile.TemporaryDirectory() as directory:
            first = convert_model_files([str(source)], directory, "OBJ", overwrite=False)
            second = convert_model_files([str(source)], directory, "OBJ", overwrite=False)
        self.assertNotEqual(first["artifacts"][0]["output"], second["artifacts"][0]["output"])


if __name__ == "__main__":
    unittest.main()
