from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from function.semantic_encoding import (
    ALL_DICTIONARIES,
    LIBRARY_METADATA,
    audit_semantic_library,
    build_semantic_report,
    semantic_library_stats,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "example_source" / "semantic"


class SemanticEncodingTests(unittest.TestCase):
    def test_default_library_is_full_and_audited(self) -> None:
        stats = semantic_library_stats()
        audit = audit_semantic_library()
        self.assertGreaterEqual(stats["terms"], 250)
        self.assertGreaterEqual(stats["aliases"], 590)
        self.assertNotIn("fallback", str(LIBRARY_METADATA.get("version", "")).lower())
        self.assertTrue(Path(LIBRARY_METADATA["loaded_from"]).is_file())
        self.assertTrue(audit["valid"])
        self.assertFalse(audit["missing_project_codes"])

    def test_standard_examples_reach_full_coverage_and_generate_traceable_outputs(self) -> None:
        files = [
            SAMPLES / "semantic_sample_project_dictionary.csv",
            SAMPLES / "semantic_sample_attributes.csv",
            SAMPLES / "semantic_sample_features.geojson",
        ]
        with tempfile.TemporaryDirectory() as directory:
            report = build_semantic_report([str(path) for path in files], output_dir=directory)
            manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
            self.assertTrue(all(Path(path).is_file() for path in report["normalized_files"]))
        self.assertEqual(1.0, report["coverage_ratio"])
        self.assertEqual(100, report["score"])
        self.assertEqual(2, len(report["output_artifacts"]))
        self.assertTrue(all(len(item["source_sha256"]) == 64 and len(item["output_sha256"]) == 64 for item in report["output_artifacts"]))
        self.assertGreater(len(report["relations"]), 0)
        self.assertEqual(report["run_id"], manifest["run_id"])

    def test_target_code_system_is_applied_to_report_and_output(self) -> None:
        source = SAMPLES / "semantic_sample_attributes.csv"
        with tempfile.TemporaryDirectory() as directory:
            report = build_semantic_report([str(source)], output_dir=directory, target_code_system="SYMBOL")
            output = Path(report["normalized_files"][0])
            with output.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
        self.assertTrue(all(item["code_system"] == "SYMBOL" for item in report["mappings"]))
        self.assertIn("地层名称_目标编码", rows[0])
        self.assertEqual("SYMBOL", rows[0]["地层名称_编码体系"])

    def test_unmapped_terms_are_never_given_fabricated_codes(self) -> None:
        source = SAMPLES / "semantic_unmapped_terms.csv"
        report = build_semantic_report([str(source)])
        self.assertGreater(len(report["unmapped_terms"]), 0)
        self.assertTrue(all(not item["target_code"] for item in report["unmapped_terms"]))
        self.assertLess(report["coverage_ratio"], 1.0)

    def test_conflict_strategy_preserves_original_and_blanks_code(self) -> None:
        custom = {
            "岩性": {
                "测试岩A": {"aliases": ["ambiguous"], "codes": {"PROJECT": "A"}},
                "测试岩B": {"aliases": ["ambiguous"], "codes": {"PROJECT": "B"}},
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.csv"
            source.write_text("id,岩性\n1,ambiguous\n", encoding="utf-8")
            report = build_semantic_report(
                [str(source)], custom_dictionaries=custom, conflict_resolution="保留原始", output_dir=directory,
            )
            with Path(report["normalized_files"][0]).open(encoding="utf-8-sig", newline="") as file:
                row = next(csv.DictReader(file))
        self.assertTrue(report["conflicts"])
        self.assertEqual("ambiguous", row["岩性_规范名"])
        self.assertEqual("", row["岩性_目标编码"])

    def test_all_seven_domains_are_available(self) -> None:
        self.assertEqual(7, len(ALL_DICTIONARIES))
        self.assertTrue(all(ALL_DICTIONARIES.values()))


if __name__ == "__main__":
    unittest.main()
