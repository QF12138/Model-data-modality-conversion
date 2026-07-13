from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Bounds:
    """三维包围盒。"""
    min_x: float = 0.0
    max_x: float = 0.0
    min_y: float = 0.0
    max_y: float = 0.0
    min_z: float = 0.0
    max_z: float = 0.0

    @property
    def span_x(self) -> float:
        return self.max_x - self.min_x

    @property
    def span_y(self) -> float:
        return self.max_y - self.min_y

    @property
    def span_z(self) -> float:
        return self.max_z - self.min_z

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.min_x + self.max_x) / 2,
            (self.min_y + self.max_y) / 2,
            (self.min_z + self.max_z) / 2,
        )

    @property
    def diagonal(self) -> float:
        return math.sqrt(self.span_x ** 2 + self.span_y ** 2 + self.span_z ** 2)

    def to_dict(self) -> dict[str, float]:
        return {
            "min_x": self.min_x, "max_x": self.max_x,
            "min_y": self.min_y, "max_y": self.max_y,
            "min_z": self.min_z, "max_z": self.max_z,
            "span_x": self.span_x, "span_y": self.span_y, "span_z": self.span_z,
        }


@dataclass
class ModelSnapshot:
    """模型快照——从文件中提取的关键可比较参数。"""
    file_name: str
    vertex_count: int = 0
    face_count: int = 0
    line_count: int = 0
    bounds: Bounds = field(default_factory=Bounds)
    attribute_fields: list[str] = field(default_factory=list)
    attribute_count: int = 0
    file_size_bytes: int = 0
    format: str = ""
    center: tuple[float, float, float] = (0, 0, 0)
    scale: float = 1.0
    parse_ok: bool = False
    parse_message: str = ""
    source_path: str = ""
    sha256: str = ""
    vertices: list[tuple[float, float, float]] = field(default_factory=list, repr=False)
    faces: list[list[int]] = field(default_factory=list, repr=False)


@dataclass
class ComparisonItem:
    """单项对比结果。"""
    dimension: str           # 坐标位置 / 空间范围 / 属性映射 / 模型尺度 / 关键边界
    metric: str              # 对比指标名
    value_before: Any
    value_after: Any
    deviation: float | None  # 相对偏差
    threshold: float         # 偏差阈值
    passed: bool
    severity: str = "提示"   # 严重 / 警告 / 提示
    message: str = ""


# 对比维度
COMPARISON_DIMENSIONS = (
    "坐标位置",
    "空间范围",
    "属性映射",
    "模型尺度",
    "关键边界",
)

VIEW_MODES = ("二维叠加", "三维并排", "剖切对比", "差异热图")


# ============================================================================
# 模型快照提取
# ============================================================================

def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_snapshot(file_path: str | Path) -> ModelSnapshot:
    """从文件中提取模型快照。"""
    path = Path(file_path)
    snap = ModelSnapshot(
        file_name=path.name,
        format=path.suffix.lower(),
        file_size_bytes=path.stat().st_size if path.exists() else 0,
        source_path=str(path.resolve()) if path.exists() else str(path),
        sha256=_sha256(path) if path.exists() and path.is_file() else "",
    )
    if not path.exists():
        snap.parse_message = "文件不存在"
        return snap

    suffix = path.suffix.lower()
    supported = {".obj", ".stl", ".geojson", ".json", ".csv", ".txt", ".ply", ".vtk"}
    if suffix not in supported:
        snap.parse_message = f"暂不支持的格式：{suffix or '无扩展名'}"
        return snap

    try:
        if suffix == ".obj":
            _extract_obj(path, snap)
        elif suffix == ".stl":
            _extract_stl(path, snap)
        elif suffix in {".geojson", ".json"}:
            _extract_geojson(path, snap)
        elif suffix in {".csv", ".txt"}:
            _extract_csv(path, snap)
        elif suffix == ".ply":
            _extract_ply(path, snap)
        elif suffix == ".vtk":
            _extract_vtk(path, snap)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, ValueError, struct.error) as exc:
        snap.parse_message = f"解析失败：{exc}"
        return snap

    snap.parse_ok = bool(snap.vertex_count or snap.face_count or snap.line_count or snap.attribute_fields)
    if snap.vertex_count > 0:
        snap.scale = snap.bounds.diagonal or 1.0
        snap.center = snap.bounds.center
    if not snap.parse_ok:
        snap.parse_message = "未提取到可比较的坐标、网格或属性信息"
    else:
        snap.parse_message = "解析成功"
    return snap


def _extract_obj(path: Path, snap: ModelSnapshot) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for line in _read_text(path).splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append(tuple(float(v) for v in parts[1:4]))
        elif parts[0] == "f" and len(parts) >= 4:
            snap.face_count += 1
            face: list[int] = []
            for token in parts[1:]:
                raw_index = int(token.split("/")[0])
                face.append(raw_index - 1 if raw_index > 0 else len(vertices) + raw_index)
            faces.append(face)
        elif parts[0] == "l" and len(parts) >= 3:
            snap.line_count += 1
    snap.vertex_count = len(vertices)
    snap.vertices = vertices
    snap.faces = faces
    if vertices:
        xs, ys, zs = zip(*vertices)
        snap.bounds = Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _extract_stl(path: Path, snap: ModelSnapshot) -> None:
    """同时支持 ASCII STL 和常见二进制 STL。"""
    raw = path.read_bytes()
    vertices: list[tuple[float, float, float]] = []

    # 二进制 STL：80 字节头 + 4 字节三角形数量 + 每面 50 字节
    if len(raw) >= 84:
        tri_count = struct.unpack_from("<I", raw, 80)[0]
        expected_size = 84 + tri_count * 50
        if tri_count > 0 and expected_size == len(raw):
            offset = 84
            for _ in range(tri_count):
                values = struct.unpack_from("<12fH", raw, offset)
                vertices.extend([
                    (values[3], values[4], values[5]),
                    (values[6], values[7], values[8]),
                    (values[9], values[10], values[11]),
                ])
                offset += 50
            snap.face_count = tri_count

    if not vertices:
        for line in _read_text(path).splitlines():
            parts = line.strip().split()
            if len(parts) == 4 and parts[0].lower() == "vertex":
                vertices.append(tuple(float(v) for v in parts[1:4]))
        snap.face_count = len(vertices) // 3

    snap.vertex_count = len(vertices)
    snap.vertices = vertices
    snap.faces = [[index, index + 1, index + 2] for index in range(0, len(vertices) - 2, 3)]
    if vertices:
        xs, ys, zs = zip(*vertices)
        snap.bounds = Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

def _extract_geojson(path: Path, snap: ModelSnapshot) -> None:
    """提取 GeoJSON/JSON 中的二维或三维坐标和 Feature 属性。"""
    data = json.loads(_read_text(path))
    vertices: list[tuple[float, float, float]] = []
    attrs: set[str] = set()

    def _collect_positions(coords: Any) -> None:
        if not isinstance(coords, list):
            return
        # 一个坐标位置：[x, y] 或 [x, y, z]
        if len(coords) >= 2 and all(isinstance(v, (int, float)) for v in coords[:2]):
            x = float(coords[0])
            y = float(coords[1])
            z = float(coords[2]) if len(coords) >= 3 and isinstance(coords[2], (int, float)) else 0.0
            vertices.append((x, y, z))
            return
        for item in coords:
            _collect_positions(item)

    def _collect(obj: Any) -> None:
        if isinstance(obj, dict):
            obj_type = obj.get("type")
            if obj_type == "FeatureCollection":
                for feature in obj.get("features", []):
                    _collect(feature)
            elif obj_type == "Feature":
                props = obj.get("properties", {})
                if isinstance(props, dict):
                    attrs.update(str(k) for k in props.keys() if k is not None)
                _collect(obj.get("geometry"))
            elif obj_type == "GeometryCollection":
                for geometry in obj.get("geometries", []):
                    _collect(geometry)
            elif "coordinates" in obj:
                _collect_positions(obj.get("coordinates"))
            else:
                # 兼容普通 JSON 中嵌套的 GeoJSON 对象
                for value in obj.values():
                    _collect(value)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item)

    _collect(data)
    snap.vertex_count = len(vertices)
    snap.vertices = vertices
    snap.attribute_fields = sorted(attrs)
    snap.attribute_count = len(attrs)
    if vertices:
        xs, ys, zs = zip(*vertices)
        snap.bounds = Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

def _extract_csv(path: Path, snap: ModelSnapshot) -> None:
    rows = list(csv.DictReader(_read_text(path).splitlines()))
    if not rows:
        return
    snap.attribute_count = len(rows)
    snap.attribute_fields = sorted(str(key) for key in rows[0].keys() if key is not None)
    coord_aliases = {
        "x": {"x", "lon", "lng", "longitude", "easting"},
        "y": {"y", "lat", "latitude", "northing"},
        "z": {"z", "elevation", "height", "altitude"},
    }
    mapping: dict[str, str] = {}
    for field in rows[0].keys():
        if field is None:
            continue
        f_lower = field.strip().lower()
        for axis, names in coord_aliases.items():
            if f_lower in names:
                mapping[axis] = field
    if "x" in mapping and "y" in mapping:
        vertices: list[tuple[float, float, float]] = []
        for row in rows:
            try:
                x = float(row[mapping["x"]])
                y = float(row[mapping["y"]])
                z = float(row[mapping["z"]]) if "z" in mapping and row.get(mapping["z"], "") not in ("", None) else 0.0
            except (TypeError, ValueError, KeyError):
                continue
            vertices.append((x, y, z))
        snap.vertex_count = len(vertices)
        snap.vertices = vertices
        if vertices:
            xs, ys, zs = zip(*vertices)
            snap.bounds = Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

def _extract_ply(path: Path, snap: ModelSnapshot) -> None:
    """读取 ASCII PLY 的 vertex 元素；二进制 PLY 会明确提示。"""
    lines = _read_text(path).splitlines()
    if not lines or lines[0].strip().lower() != "ply":
        raise ValueError("不是有效的 PLY 文件")
    vertex_count = 0
    header_end = -1
    ascii_format = False
    for index, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("format ascii"):
            ascii_format = True
        elif stripped.startswith("element vertex"):
            vertex_count = int(stripped.split()[-1])
        elif stripped == "end_header":
            header_end = index
            break
    if not ascii_format:
        raise ValueError("当前仅支持 ASCII PLY")
    if header_end < 0:
        raise ValueError("PLY 缺少 end_header")
    vertices: list[tuple[float, float, float]] = []
    for line in lines[header_end + 1: header_end + 1 + vertex_count]:
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        vertices.append((float(parts[0]), float(parts[1]), float(parts[2])))
    snap.vertex_count = len(vertices)
    snap.vertices = vertices
    faces: list[list[int]] = []
    for line in lines[header_end + 1 + vertex_count:]:
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= int(parts[0]) + 1:
            count = int(parts[0])
            faces.append([int(value) for value in parts[1:1 + count]])
    snap.faces = faces
    snap.face_count = len(faces)
    if vertices:
        xs, ys, zs = zip(*vertices)
        snap.bounds = Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _extract_vtk(path: Path, snap: ModelSnapshot) -> None:
    """读取传统 ASCII VTK 中的 POINTS 数据段。"""
    lines = _read_text(path).splitlines()
    point_count = 0
    start_index = -1
    for index, line in enumerate(lines):
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0].upper() == "POINTS":
            point_count = int(parts[1])
            start_index = index + 1
            break
    if start_index < 0:
        raise ValueError("VTK 中未找到 POINTS 数据段")
    values: list[float] = []
    for line in lines[start_index:]:
        for token in line.strip().split():
            try:
                values.append(float(token))
            except ValueError:
                break
        if len(values) >= point_count * 3:
            break
    vertices = [tuple(values[i:i + 3]) for i in range(0, min(len(values), point_count * 3), 3) if len(values[i:i + 3]) == 3]
    snap.vertex_count = len(vertices)
    snap.vertices = vertices
    if vertices:
        xs, ys, zs = zip(*vertices)
        snap.bounds = Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


# ============================================================================
# 对比引擎
# ============================================================================

def _pair_key(file_name: str) -> str:
    """生成前后文件配对键，忽略 before/after 等常见前后缀。"""
    stem = Path(file_name).stem.lower()
    stem = re.sub(r"(^|[_\-\s])(before|after|pre|post|转换前|转换后|原始|结果)(?=$|[_\-\s])", "_", stem)
    stem = re.sub(r"[_\-\s]+", "_", stem).strip("_")
    return stem


def _pair_snapshots(
    before_items: list[ModelSnapshot],
    after_items: list[ModelSnapshot],
) -> list[tuple[ModelSnapshot | None, ModelSnapshot | None]]:
    """优先按同名文件或规范化名称配对，再按剩余顺序配对。"""
    pairs: list[tuple[ModelSnapshot | None, ModelSnapshot | None]] = []
    remaining_after = list(after_items)
    for before in before_items:
        match_index = next((i for i, item in enumerate(remaining_after) if item.file_name.lower() == before.file_name.lower()), None)
        if match_index is None:
            key = _pair_key(before.file_name)
            match_index = next((i for i, item in enumerate(remaining_after) if _pair_key(item.file_name) == key), None)
        after = remaining_after.pop(match_index) if match_index is not None else None
        pairs.append((before, after))
    pairs.extend((None, item) for item in remaining_after)
    return pairs


def _sample_points(points: list[tuple[float, float, float]], limit: int) -> list[tuple[float, float, float]]:
    if len(points) <= limit:
        return list(points)
    step = len(points) / limit
    return [points[min(int(index * step), len(points) - 1)] for index in range(limit)]


def _project_point(point: tuple[float, float, float], plane: str) -> tuple[float, float]:
    if plane == "XZ":
        return point[0], point[2]
    if plane == "YZ":
        return point[1], point[2]
    return point[0], point[1]


def _profile_dict(profile: "SliceProfile") -> dict[str, Any]:
    return {
        "axis": profile.axis, "position": profile.position,
        "points": [[x, y] for x, y in profile.points],
        "area": profile.area, "perimeter": profile.perimeter,
    }


def _heatmap_payload(
    before: ModelSnapshot | None,
    after: ModelSnapshot | None,
    plane: str,
    limit: int,
) -> dict[str, Any]:
    if not before or not after or not before.vertices or not after.vertices:
        return {"points": [], "mean_distance": None, "max_distance": None, "p95_distance": None, "normalized_max": None}
    references = _sample_points(before.vertices, max(limit, 1000))
    targets = _sample_points(after.vertices, limit)
    distances: list[float] = []
    points: list[dict[str, float]] = []
    diagonal = max(before.bounds.diagonal, 1e-9)
    for target in targets:
        distance = min(
            math.sqrt(sum((target[index] - source[index]) ** 2 for index in range(3)))
            for source in references
        )
        distances.append(distance)
        px, py = _project_point(target, plane)
        points.append({"x": px, "y": py, "distance": distance, "normalized": distance / diagonal})
    ordered = sorted(distances)
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return {
        "points": points,
        "mean_distance": sum(distances) / len(distances),
        "max_distance": max(distances),
        "p95_distance": ordered[p95_index],
        "normalized_max": max(distances) / diagonal,
    }


def _build_visualization_pair(
    before: ModelSnapshot | None,
    after: ModelSnapshot | None,
    *,
    slice_axis: str,
    slice_ratio: float,
    heatmap_limit: int,
) -> dict[str, Any]:
    axis = slice_axis if slice_axis in {"XY", "XZ", "YZ"} else "XY"
    label = (before and before.file_name) or (after and after.file_name) or "未知"
    before_points = _sample_points(before.vertices, heatmap_limit) if before else []
    after_points = _sample_points(after.vertices, heatmap_limit) if after else []
    all_axis_values: list[float] = []
    axis_index = {"YZ": 0, "XZ": 1, "XY": 2}[axis]
    if before:
        all_axis_values.extend(point[axis_index] for point in before.vertices)
    if after:
        all_axis_values.extend(point[axis_index] for point in after.vertices)
    minimum = min(all_axis_values) if all_axis_values else 0.0
    maximum = max(all_axis_values) if all_axis_values else 0.0
    position = minimum + (maximum - minimum) * slice_ratio
    before_slice = compute_slice(before.vertices, before.faces, axis, position) if before else SliceProfile(axis, position)
    after_slice = compute_slice(after.vertices, after.faces, axis, position) if after else SliceProfile(axis, position)
    area_deviation = (
        abs(before_slice.area - after_slice.area) / max(before_slice.area, 1e-9)
        if before_slice.area or after_slice.area else None
    )
    return {
        "pair": label,
        "before_file": before.file_name if before else "",
        "after_file": after.file_name if after else "",
        "projection": axis,
        "two_dimensional_overlay": {
            "before_points": [list(_project_point(point, axis)) for point in before_points],
            "after_points": [list(_project_point(point, axis)) for point in after_points],
            "before_bounds": before.bounds.to_dict() if before else {},
            "after_bounds": after.bounds.to_dict() if after else {},
        },
        "three_dimensional_preview": {
            "before_points": [list(point) for point in before_points],
            "after_points": [list(point) for point in after_points],
            "before_face_count": len(before.faces) if before else 0,
            "after_face_count": len(after.faces) if after else 0,
        },
        "slice_comparison": {
            "axis": axis, "position": position, "ratio": slice_ratio,
            "before": _profile_dict(before_slice), "after": _profile_dict(after_slice),
            "area_deviation": area_deviation,
        },
        "difference_heatmap": _heatmap_payload(before, after, axis, heatmap_limit),
        "key_boundaries": {
            "before": before.bounds.to_dict() if before else {},
            "after": after.bounds.to_dict() if after else {},
        },
    }

def compare_models(
    files_before: list[str],
    files_after: list[str],
    coordinate_threshold: float = 0.01,
    extent_threshold: float = 0.05,
    scale_threshold: float = 0.10,
    attribute_threshold: float = 0.10,
    boundary_threshold: float = 0.05,
    slice_axis: str = "XY",
    slice_ratio: float = 0.5,
    heatmap_limit: int = 800,
) -> dict[str, Any]:
    """
    对比转换前后的模型数据，生成多维度偏差报告。

    参数
    ----
    files_before : 转换前文件列表
    files_after : 转换后文件列表
    coordinate_threshold : 坐标位置偏差阈值（相对值）
    extent_threshold : 空间范围偏差阈值
    scale_threshold : 模型尺度偏差阈值
    attribute_threshold : 属性字段允许丢失比例阈值
    boundary_threshold : 关键边界偏差阈值
    """
    report: dict[str, Any] = {
        "schema_version": "2.0",
        "comparison_id": f"CMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}",
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "files_before": [],
        "files_after": [],
        "comparisons": [],
        "dimension_results": {},
        "parameters": {
            "coordinate_threshold": coordinate_threshold, "extent_threshold": extent_threshold,
            "scale_threshold": scale_threshold, "attribute_threshold": attribute_threshold,
            "boundary_threshold": boundary_threshold, "slice_axis": slice_axis,
            "slice_ratio": max(0.0, min(float(slice_ratio), 1.0)),
            "heatmap_limit": max(10, min(int(heatmap_limit), 5000)),
        },
        "visualizations": [],
    }

    # 提取快照
    snaps_before: list[ModelSnapshot] = []
    snaps_after: list[ModelSnapshot] = []

    for fp in files_before:
        snap = extract_snapshot(fp)
        snaps_before.append(snap)
        report["files_before"].append({"name": snap.file_name, "path": snap.source_path, "sha256": snap.sha256, "format": snap.format,
                                        "vertices": snap.vertex_count, "faces": snap.face_count,
                                        "bounds": snap.bounds.to_dict(),
                                        "parse_ok": snap.parse_ok, "parse_message": snap.parse_message})

    for fp in files_after:
        snap = extract_snapshot(fp)
        snaps_after.append(snap)
        report["files_after"].append({"name": snap.file_name, "path": snap.source_path, "sha256": snap.sha256, "format": snap.format,
                                       "vertices": snap.vertex_count, "faces": snap.face_count,
                                       "bounds": snap.bounds.to_dict(),
                                       "parse_ok": snap.parse_ok, "parse_message": snap.parse_message})

    # 配对对比：优先同名/规范化名称，剩余项再按顺序补齐
    comparisons: list[ComparisonItem] = []
    pairs = _pair_snapshots(snaps_before, snaps_after)
    for before, after in pairs:
        _compare_pair(before, after, comparisons,
                      coordinate_threshold, extent_threshold, scale_threshold,
                      attribute_threshold, boundary_threshold)
        report["visualizations"].append(
            _build_visualization_pair(
                before, after, slice_axis=slice_axis,
                slice_ratio=max(0.0, min(float(slice_ratio), 1.0)),
                heatmap_limit=max(10, min(int(heatmap_limit), 5000)),
            )
        )

    report["comparisons"] = [
        {
            "dimension": c.dimension, "metric": c.metric,
            "value_before": c.value_before, "value_after": c.value_after,
            "deviation": c.deviation, "threshold": c.threshold,
            "passed": c.passed, "severity": c.severity, "message": c.message,
        }
        for c in comparisons
    ]

    # 各维度汇总
    for dim in COMPARISON_DIMENSIONS:
        dim_items = [c for c in comparisons if c.dimension == dim]
        passed = sum(1 for c in dim_items if c.passed)
        report["dimension_results"][dim] = {
            "total": len(dim_items),
            "passed": passed,
            "failed": len(dim_items) - passed,
            "pass_rate": round(passed / max(len(dim_items), 1), 4),
        }

    # 综合评分
    total = len(comparisons)
    passed_total = sum(1 for c in comparisons if c.passed)
    report["score"] = round(passed_total / max(total, 1) * 100)
    report["grade"] = _grade(report["score"])
    report["total_checks"] = total
    report["passed_checks"] = passed_total
    report["visualization_summary"] = {
        "pair_count": len(report["visualizations"]),
        "modes": list(VIEW_MODES),
        "slice_profiles": sum(
            bool(item.get("slice_comparison", {}).get("before", {}).get("points"))
            or bool(item.get("slice_comparison", {}).get("after", {}).get("points"))
            for item in report["visualizations"]
        ),
        "heatmap_points": sum(len(item.get("difference_heatmap", {}).get("points", [])) for item in report["visualizations"]),
    }

    return report


def _compare_pair(
    before: ModelSnapshot | None,
    after: ModelSnapshot | None,
    out: list[ComparisonItem],
    coord_th: float,
    extent_th: float,
    scale_th: float,
    attr_th: float,
    bound_th: float,
) -> None:
    if not before and not after:
        return
    label = (before and before.file_name) or (after and after.file_name) or "未知"

    if before and after and (not before.parse_ok or not after.parse_ok):
        problems = []
        if not before.parse_ok:
            problems.append(f"转换前：{before.parse_message}")
        if not after.parse_ok:
            problems.append(f"转换后：{after.parse_message}")
        out.append(ComparisonItem(
            dimension="坐标位置", metric=f"{label} 文件解析",
            value_before=before.parse_message, value_after=after.parse_message,
            deviation=None, threshold=0.0, passed=False, severity="严重",
            message="；".join(problems),
        ))
        return

    if before and after:
        # ---- 模型尺度 ----
        dev_scale = abs(before.scale - after.scale) / max(before.scale, 1e-9)
        out.append(ComparisonItem(
            dimension="模型尺度", metric=f"{label} 对角线长度",
            value_before=f"{before.scale:.4g}", value_after=f"{after.scale:.4g}",
            deviation=round(dev_scale, 6), threshold=scale_th,
            passed=dev_scale <= scale_th,
            severity="警告" if dev_scale > scale_th else "提示",
            message="模型尺度一致" if dev_scale <= scale_th else f"模型尺度偏差 {dev_scale:.2%}，超过阈值 {scale_th:.1%}",
        ))

        # ---- 顶点数变化 ----
        if before.vertex_count and after.vertex_count:
            dev_v = abs(before.vertex_count - after.vertex_count) / max(before.vertex_count, 1)
            out.append(ComparisonItem(
                dimension="模型尺度", metric=f"{label} 顶点数",
                value_before=before.vertex_count, value_after=after.vertex_count,
                deviation=round(dev_v, 6), threshold=scale_th,
                passed=dev_v <= scale_th,
                severity="警告" if dev_v > scale_th else "提示",
                message=f"顶点数变化 {dev_v:.2%}",
            ))

        # ---- 空间范围 ----
        for axis, bf_val, af_val in [
            ("X 跨度", before.bounds.span_x, after.bounds.span_x),
            ("Y 跨度", before.bounds.span_y, after.bounds.span_y),
            ("Z 跨度", before.bounds.span_z, after.bounds.span_z),
        ]:
            denom = max(abs(bf_val), 1e-9)
            dev = abs(bf_val - af_val) / denom
            out.append(ComparisonItem(
                dimension="空间范围", metric=f"{label} {axis}",
                value_before=f"{bf_val:.4g}", value_after=f"{af_val:.4g}",
                deviation=round(dev, 6), threshold=extent_th,
                passed=dev <= extent_th,
                severity="严重" if dev > extent_th * 3 else "警告" if dev > extent_th else "提示",
                message=f"{axis} 范围一致" if dev <= extent_th else f"{axis} 范围偏差 {dev:.2%}",
            ))

        # ---- 坐标位置（中心偏移） ----
        bc = before.center
        ac = after.center
        center_dist = math.sqrt(sum((bc[i] - ac[i]) ** 2 for i in range(3)))
        ref_span = max(before.bounds.diagonal, 1e-9)
        dev_center = center_dist / ref_span
        out.append(ComparisonItem(
            dimension="坐标位置", metric=f"{label} 模型中心偏移",
            value_before=f"({bc[0]:.4g}, {bc[1]:.4g}, {bc[2]:.4g})",
            value_after=f"({ac[0]:.4g}, {ac[1]:.4g}, {ac[2]:.4g})",
            deviation=round(dev_center, 6), threshold=coord_th,
            passed=dev_center <= coord_th,
            severity="严重" if dev_center > coord_th * 5 else "警告" if dev_center > coord_th else "提示",
            message=f"中心偏移 {center_dist:.4g}（相对跨度 {dev_center:.2%}）",
        ))

        # ---- 关键边界（min/max 各轴） ----
        for axis, b_min, b_max, a_min, a_max in [
            ("X 轴", before.bounds.min_x, before.bounds.max_x, after.bounds.min_x, after.bounds.max_x),
            ("Y 轴", before.bounds.min_y, before.bounds.max_y, after.bounds.min_y, after.bounds.max_y),
            ("Z 轴", before.bounds.min_z, before.bounds.max_z, after.bounds.min_z, after.bounds.max_z),
        ]:
            for bound_name, bv, av in [("min", b_min, a_min), ("max", b_max, a_max)]:
                # 边界差异按源模型对角线归一化，避免大坐标值掩盖实际偏移，
                # 也避免边界值接近 0 时产生无意义的超大百分比。
                denom = max(before.bounds.diagonal, 1e-9)
                dev = abs(bv - av) / denom
                out.append(ComparisonItem(
                    dimension="关键边界", metric=f"{label} {axis} {bound_name}",
                    value_before=f"{bv:.4g}", value_after=f"{av:.4g}",
                    deviation=round(dev, 6), threshold=bound_th,
                    passed=dev <= bound_th,
                    severity="警告" if dev > bound_th else "提示",
                    message=f"{axis} {bound_name} 边界一致" if dev <= bound_th else f"{axis} {bound_name} 边界偏差 {dev:.2%}",
                ))

        # ---- 属性映射 ----
        before_attrs = set(before.attribute_fields)
        after_attrs = set(after.attribute_fields)
        if before_attrs or after_attrs:
            lost = before_attrs - after_attrs
            added = after_attrs - before_attrs
            kept = before_attrs & after_attrs
            retention = len(kept) / max(len(before_attrs), 1) if before_attrs else 1.0
            out.append(ComparisonItem(
                dimension="属性映射", metric=f"{label} 属性字段保留率",
                value_before=f"{len(before_attrs)} 字段", value_after=f"{len(after_attrs)} 字段",
                deviation=round(1 - retention, 6), threshold=attr_th,
                passed=retention >= (1 - attr_th),
                severity="严重" if retention < 0.5 else "警告" if lost else "提示",
                message=f"保留 {len(kept)}/{len(before_attrs)} 字段" + (f"，丢失 {len(lost)} 个" if lost else ""),
            ))
            if lost:
                out.append(ComparisonItem(
                    dimension="属性映射", metric=f"{label} 丢失属性字段",
                    value_before=", ".join(sorted(lost)), value_after="无",
                    deviation=1.0, threshold=0.0, passed=False, severity="严重",
                    message=f"转换后丢失属性字段：{', '.join(sorted(lost))}",
                ))

    elif before and not after:
        out.append(ComparisonItem(
            dimension="坐标位置", metric=f"{before.file_name}",
            value_before="存在", value_after="缺失", deviation=1.0, threshold=0.0,
            passed=False, severity="严重", message="转换后文件缺失，无法对比。",
        ))
    elif after and not before:
        out.append(ComparisonItem(
            dimension="坐标位置", metric=f"{after.file_name}",
            value_before="缺失", value_after="存在", deviation=1.0, threshold=0.0,
            passed=False, severity="提示", message="转换前无对应文件，已跳过。",
        ))


def _grade(score: int) -> str:
    if score >= 95:
        return "优秀"
    if score >= 85:
        return "良好"
    if score >= 70:
        return "合格"
    return "需复核"


# ============================================================================
# 截面剖切（基于面片-截平面交点）
# ============================================================================

@dataclass
class SliceProfile:
    """剖切面轮廓。"""
    axis: str           # "XY" / "XZ" / "YZ"
    position: float     # 剖切位置（在垂直轴上的坐标）
    points: list[tuple[float, float]] = field(default_factory=list)
    area: float = 0.0
    perimeter: float = 0.0


def compute_slice(
    vertices: list[tuple[float, float, float]],
    faces: list[list[int]],
    axis: str = "XY",
    position: float = 0.0,
) -> SliceProfile:
    """
    计算模型在指定位置和方向的剖切轮廓：遍历面片边，提取与截平面的交点并构成轮廓。

    参数
    ----
    axis : 剖切平面法向轴 ("XY"=Z截面, "XZ"=Y截面, "YZ"=X截面)
    position : 在该轴上的截取位置
    """
    profile = SliceProfile(axis=axis, position=position, points=[])
    if not vertices or not faces:
        return profile

    axis_idx = {"YZ": 0, "XZ": 1, "XY": 2}[axis]
    crossings: list[tuple[float, float]] = []

    for face in faces:
        if any(i < 0 or i >= len(vertices) for i in face):
            continue
        for ei in range(len(face)):
            a_idx = face[ei]
            b_idx = face[(ei + 1) % len(face)]
            va = vertices[a_idx]
            vb = vertices[b_idx]
            da = va[axis_idx] - position
            db = vb[axis_idx] - position

            epsilon = 1e-9
            if abs(da) <= epsilon and abs(db) <= epsilon:
                candidates = (va, vb)
                for pt in candidates:
                    if axis == "XY":
                        crossings.append((pt[0], pt[1]))
                    elif axis == "XZ":
                        crossings.append((pt[0], pt[2]))
                    else:
                        crossings.append((pt[1], pt[2]))
                continue
            if da * db <= 0:  # 跨剖切面或端点位于剖切面
                denominator = abs(da) + abs(db)
                t = abs(da) / denominator if denominator > epsilon else 0.0
                pt = [
                    va[0] + t * (vb[0] - va[0]),
                    va[1] + t * (vb[1] - va[1]),
                    va[2] + t * (vb[2] - va[2]),
                ]
                # 投影到2D
                if axis == "XY":
                    crossings.append((pt[0], pt[1]))
                elif axis == "XZ":
                    crossings.append((pt[0], pt[2]))
                else:
                    crossings.append((pt[1], pt[2]))

    # 按角度排序形成多边形轮廓
    if crossings:
        # 同一交点常被相邻面重复记录，按坐标容差去重后再计算面积。
        unique: dict[tuple[int, int], tuple[float, float]] = {}
        for point in crossings:
            unique.setdefault((round(point[0] * 1e9), round(point[1] * 1e9)), point)
        crossings = list(unique.values())
        cx = sum(p[0] for p in crossings) / len(crossings)
        cy = sum(p[1] for p in crossings) / len(crossings)
        sorted_pts = sorted(crossings, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        profile.points = sorted_pts
        profile.area = _polygon_area(sorted_pts)
        profile.perimeter = _polygon_perimeter(sorted_pts)
    return profile


def _polygon_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _polygon_perimeter(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    if n < 2:
        return 0.0
    return sum(
        math.sqrt((pts[i][0] - pts[(i + 1) % n][0]) ** 2 + (pts[i][1] - pts[(i + 1) % n][1]) ** 2)
        for i in range(n)
    )


# ============================================================================
# 对比报告入口
# ============================================================================

def build_comparison_report(
    files_before: list[str],
    files_after: list[str],
    coordinate_threshold: float = 0.01,
    extent_threshold: float = 0.05,
    scale_threshold: float = 0.10,
    attribute_threshold: float = 0.10,
    boundary_threshold: float = 0.05,
    slice_axis: str = "XY",
    slice_ratio: float = 0.5,
    heatmap_limit: int = 800,
) -> dict[str, Any]:
    """便捷入口：对比转换前后的模型数据。"""
    return compare_models(
        files_before, files_after,
        coordinate_threshold, extent_threshold, scale_threshold,
        attribute_threshold, boundary_threshold,
        slice_axis, slice_ratio, heatmap_limit,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "COMPARISON_DIMENSIONS", "VIEW_MODES",
    "ModelSnapshot", "Bounds", "ComparisonItem", "SliceProfile",
    "extract_snapshot", "compare_models", "compute_slice",
    "build_comparison_report",
]
