from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from function.data_preprocessing import build_preprocessing_report
from function.model_format_conversion import read_model


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "example_source" / "preprocessing_examples"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DataPreprocessingTests(unittest.TestCase):
    def test_numbered_examples_are_cleaned_without_modifying_sources(self) -> None:
        files = sorted(
            path for path in SAMPLES.iterdir()
            if path.name[:2].isdigit() and path.suffix.lower() in {".csv", ".geojson", ".obj", ".stl", ".ply", ".vtk"}
        )
        source_hashes = {path: sha256(path) for path in files}
        with tempfile.TemporaryDirectory() as directory:
            report = build_preprocessing_report([str(path) for path in files], auto_fix=True, output_dir=directory)
            manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(files), len(report["cleaned_files"]))
            self.assertTrue(all(Path(path).is_file() for path in report["cleaned_files"]))
            self.assertEqual(report["run_id"], manifest["run_id"])
            self.assertGreater(report["post_clean_validation"]["score"], report["score"])
        self.assertEqual(source_hashes, {path: sha256(path) for path in files})

    def test_tabular_cleaning_removes_duplicates_fills_missing_clips_outliers_and_normalizes_units(self) -> None:
        files = [next(SAMPLES.glob("01_*.csv")), next(SAMPLES.glob("08_*.csv"))]
        with tempfile.TemporaryDirectory() as directory:
            report = build_preprocessing_report([str(path) for path in files], auto_fix=True, output_dir=directory)
            unit_output = next(Path(path) for path in report["cleaned_files"] if path.endswith("08_单位归一与字段补全_cleaned.csv"))
            with unit_output.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
        self.assertEqual(5, len(rows))
        self.assertIn("thickness_m", rows[0])
        self.assertIn("pressure_Pa", rows[0])
        self.assertIn("dip_angle_rad", rows[0])
        self.assertAlmostEqual(1.25, float(rows[0]["thickness_m"]))
        self.assertAlmostEqual(2_500_000.0, float(rows[0]["pressure_Pa"]))
        self.assertTrue(all(row["material"] for row in rows))

    def test_geojson_cleaning_deduplicates_aligns_schema_and_normalizes_angle(self) -> None:
        source = next(SAMPLES.glob("05_*.geojson"))
        with tempfile.TemporaryDirectory() as directory:
            report = build_preprocessing_report([str(source)], auto_fix=True, output_dir=directory)
            data = json.loads(Path(report["cleaned_files"][0]).read_text(encoding="utf-8"))
        canonical = {json.dumps(feature, ensure_ascii=False, sort_keys=True) for feature in data["features"]}
        self.assertEqual(len(canonical), len(data["features"]))
        schemas = {tuple(sorted(feature["properties"])) for feature in data["features"]}
        self.assertEqual(1, len(schemas))
        self.assertIn("dip_angle_rad", next(iter(data["features"]))["properties"])

    def test_obj_cleaning_remaps_duplicate_vertices_and_removes_invalid_faces(self) -> None:
        source = next(SAMPLES.glob("06_*.obj"))
        with tempfile.TemporaryDirectory() as directory:
            report = build_preprocessing_report([str(source)], auto_fix=True, output_dir=directory)
            model = read_model(Path(report["cleaned_files"][0]))
            model.validate()
            cleaning = report["files"][0]["cleaning"]
        self.assertLess(cleaning["vertices_out"], cleaning["vertices_in"])
        self.assertLess(cleaning["faces_out"], cleaning["faces_in"])

    def test_issue_contract_contains_code_location_and_suggestion(self) -> None:
        source = next(SAMPLES.glob("01_*.csv"))
        report = build_preprocessing_report([str(source)])
        self.assertTrue(report["issues"])
        for issue in report["issues"]:
            self.assertTrue(issue["issue_id"])
            self.assertTrue(issue["code"])
            self.assertTrue(issue["location"])
            self.assertIn("suggestion", issue)

    def test_no_input_does_not_claim_cleaning_success(self) -> None:
        report = build_preprocessing_report([], auto_fix=True)
        self.assertFalse(report["cleaned_files"])
        self.assertEqual(0, report["file_count"])


if __name__ == "__main__":
    unittest.main()
