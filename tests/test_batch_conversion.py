from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import function.batch_conversion as batch
from function.batch_conversion import (
    BatchConfig,
    RetryPolicy,
    build_batch_report,
    create_batch_from_directories,
    create_batch_from_paths,
    get_manager,
    scan_directories,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_source" / "batch_conversion_examples"


def run_job(job: batch.BatchJob) -> batch.BatchJob:
    manager = get_manager()
    manager.submit(job.job_id)
    result = manager.run_job(job.job_id)
    assert result is not None
    return result


class BatchConversionTests(unittest.TestCase):
    def test_directory_scan_is_recursive_deduplicated_and_limited(self) -> None:
        config = BatchConfig(
            directories=[str(EXAMPLES), str(EXAMPLES / "02_3d_models")],
            recursive=True,
            max_files=5,
        )
        files = scan_directories(config)
        self.assertEqual(5, len(files))
        self.assertEqual(len(files), len({item.path for item in files}))
        self.assertTrue(all(Path(item.path).is_file() for item in files))

    def test_concurrent_mesh_batch_writes_manifest_and_sidecars(self) -> None:
        sources = sorted(str(path) for path in (EXAMPLES / "02_3d_models").iterdir() if path.is_file())
        with tempfile.TemporaryDirectory() as directory:
            job = run_job(create_batch_from_paths(
                sources, target_format="OBJ", output_dir=directory, concurrency=4,
                retry_policy=RetryPolicy(max_retries=0, retry_delay_seconds=0),
            ))
            manifests = [Path(item) for item in job.outputs if item.endswith("batch_manifest.json")]
            sidecars = [Path(item) for item in job.outputs if item.endswith(".attributes.json")]
            self.assertEqual("已完成", job.status)
            self.assertEqual(len(sources), job.success)
            self.assertEqual(1, len(manifests))
            self.assertTrue(sidecars)
            payload = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(job.job_id, payload["job_id"])
        self.assertEqual(len(sources), payload["summary"]["success"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in payload["outputs"]))

    def test_template_is_really_applied_before_conversion(self) -> None:
        source = EXAMPLES / "04_template_mapping" / "classified_points.csv"
        template = "点云标准化与分类模板"
        with tempfile.TemporaryDirectory() as directory:
            job = run_job(create_batch_from_paths(
                [str(source)], target_format="CSV", output_dir=directory,
                template_name=template,
                retry_policy=RetryPolicy(max_retries=0, retry_delay_seconds=0),
            ))
            application = job.artifacts[0]["template_application"]
            mapped = Path(application["mapped_file"])
            header = mapped.read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertEqual("已完成", job.status)
        self.assertEqual("applied", application["status"])
        self.assertEqual(64, len(application["template_fingerprint"]))
        self.assertEqual(64, len(application["mapped_sha256"]))
        self.assertIn("x,y,z", header)
        self.assertIn("classification_name", header)
        self.assertEqual("completed", job.workflow[2]["status"])
        self.assertIn("已应用 1", job.workflow[2]["detail"])

    def test_template_not_applicable_to_mesh_is_explicitly_skipped(self) -> None:
        source = EXAMPLES / "02_3d_models" / "tunnel_segment.obj"
        with tempfile.TemporaryDirectory() as directory:
            job = run_job(create_batch_from_paths(
                [str(source)], target_format="OBJ", output_dir=directory,
                template_name="点云标准化与分类模板",
                retry_policy=RetryPolicy(max_retries=0, retry_delay_seconds=0),
            ))
        application = job.artifacts[0]["template_application"]
        self.assertEqual("已完成", job.status)
        self.assertEqual("skipped", application["status"])
        self.assertIn("不适用于 OBJ", application["message"])

    def test_missing_template_fails_without_calling_converter(self) -> None:
        source = EXAMPLES / "02_3d_models" / "tunnel_segment.obj"
        with tempfile.TemporaryDirectory() as directory, patch.object(batch, "_convert_model_files") as converter:
            job = run_job(create_batch_from_paths(
                [str(source)], target_format="OBJ", output_dir=directory,
                template_name="不存在的模板",
                retry_policy=RetryPolicy(max_retries=2, retry_delay_seconds=0),
            ))
        self.assertEqual("已失败", job.status)
        self.assertEqual(0, job.retried)
        self.assertIn("规则模板不存在", job.errors[0]["message"])
        converter.assert_not_called()

    def test_transient_converter_error_is_retried_then_succeeds(self) -> None:
        source = EXAMPLES / "02_3d_models" / "tunnel_segment.obj"
        calls = {"count": 0}

        def flaky(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"success_count": 0, "failure_count": 1, "errors": ["临时读取错误"], "artifacts": []}
            output = Path(args[1]) / "retry.obj"
            output.write_text("v 0 0 0\n", encoding="utf-8")
            return {
                "success_count": 1, "failure_count": 0, "errors": [],
                "artifacts": [{"status": "成功", "output": str(output.resolve())}],
            }

        with tempfile.TemporaryDirectory() as directory, patch.object(batch, "_convert_model_files", side_effect=flaky):
            job = run_job(create_batch_from_paths(
                [str(source)], target_format="OBJ", output_dir=directory,
                retry_policy=RetryPolicy(max_retries=2, retry_delay_seconds=0, strategy="立即重试"),
            ))
        self.assertEqual("已完成", job.status)
        self.assertEqual(1, job.retried)
        self.assertEqual(2, calls["count"])

    def test_report_contains_full_artifact_and_log_audit(self) -> None:
        source = EXAMPLES / "02_3d_models" / "tunnel_segment.obj"
        with tempfile.TemporaryDirectory() as directory:
            job = run_job(create_batch_from_paths(
                [str(source)], target_format="OBJ", output_dir=directory,
                retry_policy=RetryPolicy(max_retries=0, retry_delay_seconds=0),
            ))
            report = build_batch_report([job.job_id])
        self.assertEqual("2.0", report["schema_version"])
        self.assertEqual("batch_conversion", report["report_type"])
        self.assertTrue(report["jobs"][0]["artifacts"])
        self.assertTrue(report["jobs"][0]["logs"])

    def test_cancelled_queued_job_is_not_executed(self) -> None:
        source = EXAMPLES / "02_3d_models" / "tunnel_segment.obj"
        job = create_batch_from_paths([str(source)], target_format="OBJ")
        manager = get_manager()
        manager.submit(job.job_id)
        self.assertTrue(manager.cancel_job(job.job_id))
        with patch.object(batch, "_convert_model_files") as converter:
            result = manager.run_job(job.job_id)
        self.assertIs(job, result)
        self.assertEqual("已取消", job.status)
        converter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
