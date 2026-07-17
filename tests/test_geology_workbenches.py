from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from function.borehole_3d import generate as generate_borehole
from function.borehole_attr import structure_borehole_attributes
from function.geology_workbenches import (
    GEOLOGY_MODULES,
    GEOLOGY_WORKBENCH_METHODS,
    GeologyWorkbenchMixin,
)
from function.mesh_model import generate as generate_mesh
from function.obj_renderer import parse_obj
from function.voxel_model import generate as generate_voxel, read_vox
from main import GeoConversionApp
from pyvox.parser import VoxParser


class FakeVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class BlankCanvas:
    def __init__(self) -> None:
        self.deleted = 0

    def delete(self, _tag: str) -> None:
        self.deleted += 1

    def __getattr__(self, name: str):
        raise AssertionError(f"blank canvas unexpectedly drew with {name}")


class FakeGeologyApp(GeologyWorkbenchMixin):
    def __init__(self, module_name: str) -> None:
        self.active_module = SimpleNamespace(name=module_name)
        self.selected_files: list[str] = []
        self.quality_report = {"old": True}
        self.conversion_report = {"old": True}
        self.run_completed = True
        self.run_status_var = FakeVar()
        self.status_var = FakeVar()
        self.logs: list[str] = []
        self.rendered = 0

    def _append_log(self, message: str) -> None:
        self.logs.append(message)

    def _render_progress_strip(self) -> None:
        pass

    def _render_current_page(self) -> None:
        self.rendered += 1


def csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


class GeologyWorkbenchTests(unittest.TestCase):
    def test_four_modules_have_distinct_workbenches(self) -> None:
        self.assertEqual(4, len(GEOLOGY_MODULES))
        self.assertEqual(4, len(set(GEOLOGY_WORKBENCH_METHODS.values())))
        self.assertTrue(issubclass(GeoConversionApp, GeologyWorkbenchMixin))
        for method_name in GEOLOGY_WORKBENCH_METHODS.values():
            self.assertTrue(callable(getattr(GeologyWorkbenchMixin, method_name, None)))

    def test_one_click_loader_uses_module_specific_example_packages(self) -> None:
        expected = {
            "钻孔数据三维化模块": {"borehole_layers.csv", "groundwater.csv", "tests.csv", "joints.csv"},
            "钻孔属性结构化模块": {"BH01_log.csv", "BH01_water.csv"},
            "网格模型生成模块": {"mesh_config.json", "geologic_surfaces.csv", "fault_trace.csv"},
            "体素模型生成模块": {"model_boundary.json", "lithology_dictionary.json", "geologic_samples.csv"},
        }
        for module_name, names in expected.items():
            app = FakeGeologyApp(module_name)
            app._load_geology_sample_data()
            self.assertEqual(names, {Path(item).name for item in app.selected_files})
            self.assertFalse(app.run_completed)
            self.assertIsNone(app.quality_report)
            self.assertEqual("示例数据已加载", app.run_status_var.value)
            self.assertEqual(1, app.rendered)

    def test_examples_are_nontrivial_and_cover_required_data_types(self) -> None:
        self.assertGreaterEqual(csv_rows(ROOT / "example_source" / "borehole" / "borehole_layers.csv"), 5)
        self.assertGreaterEqual(csv_rows(ROOT / "example_source" / "borehole" / "tests.csv"), 4)
        self.assertGreaterEqual(csv_rows(ROOT / "example_source" / "borehole" / "joints.csv"), 3)
        self.assertGreaterEqual(csv_rows(ROOT / "example_source" / "borehole_attr" / "BH01_log.csv"), 5)
        self.assertGreaterEqual(csv_rows(ROOT / "example_source" / "mesh" / "geologic_surfaces.csv"), 70)
        self.assertGreaterEqual(csv_rows(ROOT / "example_source" / "voxel" / "geologic_samples.csv"), 20)

    def test_generation_buttons_have_reproducible_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            reports = (
                generate_borehole(ROOT / "example_source" / "borehole", output / "borehole"),
                structure_borehole_attributes(
                    ROOT / "example_source" / "borehole_attr" / "BH01_log.csv",
                    ROOT / "example_source" / "borehole_attr" / "BH01_water.csv",
                    output / "attribute",
                ),
                generate_mesh(ROOT / "example_source" / "mesh", output / "mesh"),
                generate_voxel(ROOT / "example_source" / "voxel", output / "voxel"),
            )
            for report in reports:
                files = report.get("files", report.get("output_files", []))
                self.assertIn(report["status"], {"success", "warning"})
                self.assertTrue(files)
                self.assertTrue(all(Path(item).is_file() for item in files))

            mesh_obj = next(Path(item) for item in reports[2]["files"] if Path(item).suffix == ".obj")
            parsed = parse_obj(mesh_obj)
            self.assertFalse(parsed.is_empty)
            self.assertGreater(parsed.vertex_count, 1000)
            self.assertGreater(parsed.face_count, 100)

            voxel_path = next(Path(item) for item in reports[3]["files"] if Path(item).suffix == ".vox")
            self.assertEqual(b"VOX ", voxel_path.read_bytes()[:4])
            voxel_model = read_vox(voxel_path)
            self.assertEqual((12, 10, 12), voxel_model["dimensions"])
            self.assertEqual(1440, len(voxel_model["voxels"]))
            self.assertGreaterEqual(len(set(color_index for *_position, color_index in voxel_model["voxels"])), 3)
            specialized_model = VoxParser(str(voxel_path)).parse().models[0]
            self.assertEqual((12, 10, 12), (specialized_model.size.x, specialized_model.size.y, specialized_model.size.z))
            self.assertEqual(1440, len(specialized_model.voxels))

            voxel_app = FakeGeologyApp("体素模型生成模块")
            voxel_app.quality_report = {"output_files": reports[3]["files"]}
            self.assertEqual(1440, len(voxel_app._voxel_result_model()["voxels"]))

    def test_initial_result_canvases_are_empty(self) -> None:
        app = FakeGeologyApp("钻孔数据三维化模块")
        app.run_completed = False
        for draw in (
            app._draw_borehole_scene,
            app._draw_attribute_relation_scene,
            app._draw_voxel_scene,
        ):
            canvas = BlankCanvas()
            draw(canvas)
            self.assertEqual(1, canvas.deleted)

    def test_clear_resets_geology_state_and_stops_preview(self) -> None:
        module_name = "网格模型生成模块"
        app = object.__new__(GeoConversionApp)
        app.active_module = SimpleNamespace(name=module_name)
        app._module_files = {module_name: ["mesh.obj", "mesh.vtk"]}
        app.run_completed = True
        app.quality_report = {"output_files": ["mesh.obj"]}
        app.conversion_report = {"status": "success"}
        app.version_report = {"versions": [1]}
        app.task_payload_text = "old"
        app._3d_models = [object()]
        app._3d_preview_canvas = object()
        app.run_status_var = FakeVar()
        app.status_var = FakeVar()
        app.logs = []
        app._append_log = app.logs.append
        app._render_progress_strip = lambda: None
        app._render_current_page = lambda: None
        stopped: list[bool] = []
        app._stop_3d_preview = lambda: stopped.append(True)

        GeoConversionApp._clear_files(app)

        self.assertEqual([], app.selected_files)
        self.assertFalse(app.run_completed)
        self.assertIsNone(app.quality_report)
        self.assertIsNone(app._3d_preview_canvas)
        self.assertEqual([True], stopped)


if __name__ == "__main__":
    unittest.main()
