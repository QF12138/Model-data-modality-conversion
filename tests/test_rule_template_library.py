from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from function.rule_template_library import (
    FieldMappingRule,
    RuleTemplate,
    apply_template_to_file,
    audit_template_library,
    build_template_report,
    delete_template,
    duplicate_template,
    export_template_library,
    get_template,
    import_template,
    list_templates,
    save_template,
    template_fingerprint,
    validate_template,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_source" / "rule_template_examples"


class RuleTemplateLibraryTests(unittest.TestCase):
    def test_builtin_library_is_valid_and_fingerprinted(self) -> None:
        audit = audit_template_library()
        self.assertTrue(audit["valid"])
        self.assertGreaterEqual(audit["built_in_count"], 18)
        self.assertFalse(audit["invalid_templates"])
        self.assertTrue(all(len(template_fingerprint(item)) == 64 for item in list_templates()))

    def test_tunnel_borehole_example_recommends_specific_template(self) -> None:
        source = EXAMPLES / "tunnel_boreholes.csv"
        report = build_template_report([str(source)], "隧道工程", "钻孔数据")
        self.assertEqual("隧道工程钻孔地质建模模板", report["summary"]["best_match"])
        self.assertGreaterEqual(report["summary"]["best_score"], 80)
        self.assertTrue(report["library_audit"]["valid"])
        self.assertEqual(64, len(report["files"][0]["sha256"]))

    def test_template_application_is_atomic_and_traceable(self) -> None:
        source = EXAMPLES / "tunnel_boreholes.csv"
        name = "隧道工程钻孔地质建模模板"
        with tempfile.TemporaryDirectory() as directory:
            result = apply_template_to_file(name, source, directory)
            output = Path(result["output_file"])
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(output.is_file())
            self.assertFalse(list(Path(directory).glob("*.tmp")))
        self.assertEqual(64, len(result["input_sha256"]))
        self.assertEqual(64, len(result["output_sha256"]))
        self.assertEqual(template_fingerprint(get_template(name)), result["template_fingerprint"])
        self.assertEqual(result["application_id"], payload["application_id"])
        self.assertGreater(len(result["rows"]), 0)

    def test_user_template_persists_and_can_be_reimported(self) -> None:
        source_name = "隧道工程钻孔地质建模模板"
        user_name = "测试项目持久化模板"
        with tempfile.TemporaryDirectory() as directory:
            duplicate = duplicate_template(source_name, user_name, storage_dir=directory)
            self.assertIsNotNone(duplicate)
            stored = next(Path(directory).glob("*.json"))
            self.assertTrue(stored.is_file())
            delete_template(user_name)
            self.assertIsNone(get_template(user_name))
            imported = import_template(stored)
            self.assertEqual(user_name, imported)
            self.assertIsNotNone(get_template(user_name))
            delete_template(user_name)

    def test_exported_library_index_contains_hash_validation_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exported = export_template_library(directory)
            index = json.loads((Path(directory) / "template_index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(exported) - 1, index["template_count"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in index["templates"]))
        self.assertTrue(all(len(item["fingerprint"]) == 64 for item in index["templates"]))
        self.assertTrue(all(item["validation"]["valid"] for item in index["templates"]))

    def test_invalid_template_is_rejected(self) -> None:
        template = RuleTemplate(
            name="", project_type="不存在", data_source="不存在", input_formats=[],
            field_mappings=[FieldMappingRule(source_field="a", target_field="")],
        )
        validation = validate_template(template)
        self.assertFalse(validation.valid)
        with self.assertRaises(ValueError):
            save_template(template)


if __name__ == "__main__":
    unittest.main()
