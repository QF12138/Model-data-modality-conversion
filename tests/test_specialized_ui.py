from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from function.specialized_modules import MODULE_SLUGS, example_directory
from function.specialized_workbenches import SPECIALIZED_WORKBENCH_METHODS, SpecializedWorkbenchMixin
from main import FEATURE_MODULES, GeoConversionApp


class FakeVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class SpecializedUiTests(unittest.TestCase):
    def test_every_module_has_an_existing_default_data_directory(self) -> None:
        app = object.__new__(GeoConversionApp)
        for module in FEATURE_MODULES:
            app.active_module = module
            directory = GeoConversionApp._active_module_data_directory(app)
            self.assertTrue(directory.is_dir(), module.name)

    def test_eight_modules_have_distinct_workbench_renderers(self) -> None:
        self.assertEqual(set(MODULE_SLUGS), set(SPECIALIZED_WORKBENCH_METHODS))
        self.assertEqual(8, len(set(SPECIALIZED_WORKBENCH_METHODS.values())))
        for method_name in SPECIALIZED_WORKBENCH_METHODS.values():
            self.assertTrue(callable(getattr(SpecializedWorkbenchMixin, method_name, None)), method_name)

    def test_clear_is_idempotent_and_resets_all_visible_result_state(self) -> None:
        module = next(item for item in FEATURE_MODULES if item.name == "点云数据转换模块")
        app = object.__new__(GeoConversionApp)
        app.active_module = module
        app._module_files = {module.name: ["a.csv", "b.ply"]}
        app.run_completed = True
        app.quality_report = {"score": 95, "artifacts": [{"name": "old.ply"}]}
        app.conversion_report = {"status": "完成"}
        app.version_report = {"versions": [1]}
        app.task_payload_text = "old task"
        app._3d_models = [object()]
        app.run_status_var = FakeVar("完成")
        app.status_var = FakeVar("旧状态")
        app.logs = []
        app._append_log = app.logs.append
        app._render_progress_strip = lambda: None
        app._render_current_page = lambda: None

        GeoConversionApp._clear_files(app)
        self.assertEqual([], app.selected_files)
        self.assertFalse(app.run_completed)
        self.assertIsNone(app.quality_report)
        self.assertIsNone(app.conversion_report)
        self.assertIsNone(app.version_report)
        self.assertEqual([], app._3d_models)
        self.assertEqual("待处理", app.run_status_var.get())
        self.assertIn("已清空 2 个", app.status_var.get())

        GeoConversionApp._clear_files(app)
        self.assertEqual([], app.selected_files)
        self.assertIn("空白状态", app.status_var.get())

    def test_complex_examples_have_multiple_sources_and_nontrivial_records(self) -> None:
        minimum_data_files = {
            "坐标与基准统一模块": 3,
            "剖面与平面图转换模块": 2,
            "地质解释线重建模块": 1,
            "栅格与矢量转换模块": 3,
            "点云数据转换模块": 3,
            "地质属性映射模块": 2,
            "多尺度模型转换模块": 3,
            "局部精细模型构建模块": 4,
        }
        for module_name, minimum in minimum_data_files.items():
            directory = example_directory(ROOT, module_name)
            data_files = [path for path in directory.iterdir() if path.is_file() and path.name != "README.md"]
            self.assertGreaterEqual(len(data_files), minimum, module_name)
        point_rows = sum(
            max(0, len(path.read_text(encoding="utf-8-sig").splitlines()) - 1)
            for path in example_directory(ROOT, "点云数据转换模块").glob("*.csv")
        )
        attribute_rows = len((example_directory(ROOT, "地质属性映射模块") / "attribute_samples.csv").read_text(encoding="utf-8-sig").splitlines()) - 1
        self.assertGreaterEqual(point_rows, 80)
        self.assertGreaterEqual(attribute_rows, 20)


if __name__ == "__main__":
    unittest.main()
