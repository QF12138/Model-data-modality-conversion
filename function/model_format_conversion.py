from __future__ import annotations

import csv
import json
import math
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


TARGET_PLATFORM_FORMATS: dict[str, tuple[str, ...]] = {
    "GIS平台": ("GeoJSON", "CSV"),
    "三维建模软件": ("OBJ", "STL", "PLY"),
    "BIM平台": ("IFC",),
    "数值模拟软件": ("VTK",),
}

# 本模块可以真实解析并转换的输入格式。专有格式不在这里伪装支持。
SUPPORTED_SOURCE_SUFFIXES = {".obj", ".stl", ".ply", ".vtk", ".geojson", ".json", ".csv", ".txt"}
SUPPORTED_TARGET_FORMATS = tuple(
    fmt for formats in TARGET_PLATFORM_FORMATS.values() for fmt in formats
)

FORMAT_ALIASES = {
    "JSON": "GEOJSON",
    "GEO JSON": "GEOJSON",
    ".GEOJSON": "GEOJSON",
    ".JSON": "GEOJSON",
    ".OBJ": "OBJ",
    ".STL": "STL",
    ".PLY": "PLY",
    ".VTK": "VTK",
    ".IFC": "IFC",
    ".CSV": "CSV",
}

PROPRIETARY_FORMAT_HINTS = {
    ".shp": "建议通过 GDAL/GeoPandas 适配器读取 Shapefile。",
    ".gpkg": "建议通过 GDAL/GeoPandas 适配器读取 GeoPackage。",
    ".tif": "建议通过 GDAL/rasterio 读取 GeoTIFF，并先明确栅格转点、等值线或表面网格规则。",
    ".las": "建议通过 laspy/PDAL 读取 LAS/LAZ 点云。",
    ".laz": "建议通过 laspy/PDAL 读取 LAS/LAZ 点云。",
    ".fbx": "FBX 属于厂商生态格式，建议使用 Autodesk FBX SDK 或 Blender 命令行转换。",
    ".glb": "建议通过 trimesh/pygltflib 读取 glTF/GLB。",
    ".gltf": "建议通过 trimesh/pygltflib 读取 glTF/GLB。",
    ".rvt": "RVT 需要 Revit API/Design Automation，不能仅靠标准 Python 直接可靠转换。",
    ".nwd": "NWD/NWC 需要 Navisworks API 或 Autodesk 平台服务。",
    ".nwc": "NWD/NWC 需要 Navisworks API 或 Autodesk 平台服务。",
    ".dwg": "DWG 建议通过 ODA/AutoCAD API；开源环境可优先交换 DXF。",
    ".dgn": "DGN 建议通过 Bentley iTwin/MicroStation SDK。",
    ".inp": "Abaqus INP 需要单元、材料、集合和边界条件专用解析器。",
    ".cdb": "ANSYS CDB 需要节点、单元、材料和组件专用解析器。",
    ".msh": "Gmsh MSH 建议通过 meshio 适配，并保留物理组与单元类型。",
    ".h5": "HDF5 需要项目数据模式说明后才能可靠映射。",
}

COORDINATE_RULES = ("保留源坐标", "平移到局部原点", "模型中心归零")
ATTRIBUTE_RULES = ("全部保留", "仅保留标识字段", "不保留属性")


class ConversionError(ValueError):
    """输入数据不能按当前规则完成转换。"""


@dataclass
class ModelData:
    """跨 GIS、三维、BIM 和数值模拟格式使用的轻量中间模型。"""

    name: str
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[list[int]] = field(default_factory=list)  # 0-based vertex indices
    lines: list[list[int]] = field(default_factory=list)
    vertex_properties: list[dict[str, Any]] = field(default_factory=list)
    face_properties: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.vertices:
            raise ConversionError("未识别到可转换的坐标或顶点。")
        count = len(self.vertices)
        for face in self.faces:
            if len(face) < 3:
                raise ConversionError("存在少于 3 个顶点的面。")
            if any(index < 0 or index >= count for index in face):
                raise ConversionError("面引用了不存在的顶点。")
        for line in self.lines:
            if len(line) < 2:
                raise ConversionError("存在线段顶点数不足。")
            if any(index < 0 or index >= count for index in line):
                raise ConversionError("线引用了不存在的顶点。")

    @property
    def bounds(self) -> dict[str, list[float]]:
        if not self.vertices:
            return {"min": [], "max": []}
        xs, ys, zs = zip(*self.vertices)
        return {
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        }

    @property
    def attribute_fields(self) -> list[str]:
        fields: set[str] = set()
        for item in self.vertex_properties:
            fields.update(str(key) for key in item)
        for item in self.face_properties:
            fields.update(str(key) for key in item)
        return sorted(fields)


def normalize_target_format(value: str) -> str:
    """把界面输入的目标格式归一为 GEOJSON/OBJ/STL/PLY/VTK/IFC/CSV。"""
    raw = (value or "").strip().upper()
    raw = FORMAT_ALIASES.get(raw, raw)
    if raw in {fmt.upper() for fmt in SUPPORTED_TARGET_FORMATS}:
        return raw

    # 兼容界面中曾使用的“GeoJSON / VTK / IFC”写法，选择第一个可识别格式。
    tokens = [token.strip().upper() for token in re.split(r"[/,，;；|\s]+", raw) if token.strip()]
    for token in tokens:
        token = FORMAT_ALIASES.get(token, token)
        if token in {fmt.upper() for fmt in SUPPORTED_TARGET_FORMATS}:
            return token
    raise ConversionError(
        f"不支持的目标格式：{value!r}。当前可直接输出：{', '.join(SUPPORTED_TARGET_FORMATS)}。"
    )


def infer_target_platform(target_format: str) -> str:
    normalized = normalize_target_format(target_format)
    for platform, formats in TARGET_PLATFORM_FORMATS.items():
        if normalized in {item.upper() for item in formats}:
            return platform
    return "通用交换"


def build_conversion_plan(
    file_paths: list[str],
    target_format: str,
    coordinate_rule: str = "保留源坐标",
    attribute_rule: str = "全部保留",
) -> dict[str, Any]:
    """只生成转换可行性计划，不创建成果文件。"""
    normalized = normalize_target_format(target_format)
    items: list[dict[str, Any]] = []
    for file_path in file_paths:
        path = Path(file_path)
        suffix = path.suffix.lower()
        supported = suffix in SUPPORTED_SOURCE_SUFFIXES
        items.append(
            {
                "source": str(path),
                "source_format": suffix or "unknown",
                "target_format": normalized,
                "supported": supported,
                "message": "可直接转换" if supported else PROPRIETARY_FORMAT_HINTS.get(
                    suffix, "当前未内置该源格式解析器。"
                ),
            }
        )
    return {
        "task": "model_format_conversion_plan",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target_platform": infer_target_platform(normalized),
        "target_format": normalized,
        "coordinate_rule": coordinate_rule,
        "attribute_rule": attribute_rule,
        "items": items,
    }


def convert_model_files(
    file_paths: list[str],
    output_dir: str | Path,
    target_format: str,
    coordinate_rule: str = "保留源坐标",
    attribute_rule: str = "全部保留",
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    执行地质环境模型格式转换并返回可入库的任务报告。

    当前真实支持：
    - 输入：OBJ、ASCII STL、ASCII PLY、Legacy ASCII VTK、GeoJSON/JSON、CSV/TXT 坐标表；
    - 输出：GeoJSON、CSV、OBJ、ASCII STL、ASCII PLY、Legacy ASCII VTK、IFC4。

    坐标系投影转换没有在缺少源 CRS 与目标 CRS 的情况下强行猜测；这里只提供
    坐标保留、局部原点平移和模型中心归零。真实 CRS 转换应接入 pyproj/GDAL。
    """
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        normalized_format = normalize_target_format(target_format)
    except ConversionError as exc:
        return _failed_report(
            file_paths=file_paths,
            output_dir=output_path,
            target_format=str(target_format),
            coordinate_rule=coordinate_rule,
            attribute_rule=attribute_rule,
            message=str(exc),
        )

    report: dict[str, Any] = {
        "task": "model_format_conversion",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "运行中",
        "target_platform": infer_target_platform(normalized_format),
        "target_format": normalized_format,
        "output_dir": str(output_path.resolve()),
        "coordinate_rule": coordinate_rule,
        "attribute_rule": attribute_rule,
        "source_count": len(file_paths),
        "success_count": 0,
        "failure_count": 0,
        "warning_count": 0,
        "artifacts": [],
        "warnings": [],
        "errors": [],
    }

    if not file_paths:
        report["status"] = "失败"
        report["errors"].append("未选择待转换文件。")
        report["failure_count"] = 1
        report["quality_score"] = 0
        report["manifest_path"] = _write_manifest(output_path, report, overwrite=True)
        return report

    for file_path in file_paths:
        source = Path(file_path)
        artifact: dict[str, Any] = {
            "source": str(source),
            "source_name": source.name,
            "source_format": source.suffix.lower() or "unknown",
            "target_format": normalized_format,
            "target_platform": report["target_platform"],
            "status": "失败",
            "output": "",
            "message": "",
        }
        try:
            if not source.exists():
                raise ConversionError("文件不存在或路径不可访问。")
            if source.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
                hint = PROPRIETARY_FORMAT_HINTS.get(source.suffix.lower(), "当前未内置该源格式解析器。")
                raise ConversionError(hint)

            model = read_model(source)
            model.validate()
            coordinate_warning = apply_coordinate_rule(model, coordinate_rule)
            apply_attribute_rule(model, attribute_rule)

            target = _build_target_path(output_path, source.stem, normalized_format, overwrite)
            write_model(model, target, normalized_format)

            artifact.update(
                {
                    "status": "成功",
                    "output": str(target.resolve()),
                    "message": "转换完成",
                    "vertex_count": len(model.vertices),
                    "face_count": len(model.faces),
                    "line_count": len(model.lines),
                    "attribute_fields": model.attribute_fields,
                    "bounds": model.bounds,
                    "size_bytes": target.stat().st_size,
                }
            )
            report["success_count"] += 1
            if coordinate_warning:
                report["warnings"].append(f"{source.name}：{coordinate_warning}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, ConversionError, ValueError) as exc:
            message = str(exc)
            artifact["message"] = message
            report["failure_count"] += 1
            report["errors"].append(f"{source.name}：{message}")
        report["artifacts"].append(artifact)

    report["warning_count"] = len(report["warnings"])
    if report["success_count"] == len(file_paths):
        report["status"] = "完成"
    elif report["success_count"] > 0:
        report["status"] = "部分完成"
    else:
        report["status"] = "失败"

    success_ratio = report["success_count"] / max(1, len(file_paths))
    report["quality_score"] = max(
        0,
        min(100, round(success_ratio * 100 - report["warning_count"] * 3)),
    )
    report["manifest_path"] = _write_manifest(output_path, report, overwrite=True)
    return report


def read_model(path: Path) -> ModelData:
    suffix = path.suffix.lower()
    readers = {
        ".obj": _read_obj,
        ".stl": _read_ascii_stl,
        ".ply": _read_ascii_ply,
        ".vtk": _read_legacy_vtk,
        ".geojson": _read_geojson,
        ".json": _read_geojson,
        ".csv": _read_csv_points,
        ".txt": _read_csv_points,
    }
    reader = readers.get(suffix)
    if reader is None:
        raise ConversionError(f"未实现 {suffix or '未知'} 格式解析器。")
    return reader(path)


def write_model(model: ModelData, path: Path, target_format: str) -> None:
    writers = {
        "OBJ": _write_obj,
        "STL": _write_ascii_stl,
        "PLY": _write_ascii_ply,
        "VTK": _write_legacy_vtk,
        "GEOJSON": _write_geojson,
        "CSV": _write_csv,
        "IFC": _write_ifc4,
    }
    writer = writers.get(normalize_target_format(target_format))
    if writer is None:
        raise ConversionError(f"未实现 {target_format} 输出器。")
    writer(model, path)


def apply_coordinate_rule(model: ModelData, rule: str) -> str | None:
    normalized = (rule or "保留源坐标").strip()
    if normalized in {"", "默认", "保留源坐标", "原坐标", "源坐标"}:
        return None
    if not model.vertices:
        return None

    xs, ys, zs = zip(*model.vertices)
    if normalized == "平移到局部原点":
        offset = (min(xs), min(ys), min(zs))
    elif normalized == "模型中心归零":
        offset = (
            (min(xs) + max(xs)) / 2.0,
            (min(ys) + max(ys)) / 2.0,
            (min(zs) + max(zs)) / 2.0,
        )
    else:
        return (
            f"坐标规则“{normalized}”不属于内置平移规则，已保留源坐标。"
            "涉及 CGCS2000/WGS84/工程坐标系的真实投影转换应补充源 CRS、目标 CRS 并接入 pyproj/GDAL。"
        )

    model.vertices = [
        (x - offset[0], y - offset[1], z - offset[2])
        for x, y, z in model.vertices
    ]
    model.metadata["coordinate_offset"] = list(offset)
    model.metadata["coordinate_rule"] = normalized
    return None


def apply_attribute_rule(model: ModelData, rule: str) -> None:
    normalized = (rule or "全部保留").strip()
    if normalized in {"", "默认", "全部保留", "尽可能保留", "保留全部属性"}:
        return
    if normalized == "不保留属性":
        model.vertex_properties = []
        model.face_properties = []
        model.metadata.pop("properties", None)
        return
    if normalized == "仅保留标识字段":
        keep = {"id", "name", "type", "code", "layer", "source", "地层", "岩性", "编号", "名称", "类型"}
        model.vertex_properties = [
            {key: value for key, value in item.items() if str(key).lower() in keep or str(key) in keep}
            for item in model.vertex_properties
        ]
        model.face_properties = [
            {key: value for key, value in item.items() if str(key).lower() in keep or str(key) in keep}
            for item in model.face_properties
        ]
        return
    model.metadata["attribute_rule_warning"] = f"未识别属性规则“{normalized}”，按全部保留处理。"


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_obj(path: Path) -> ModelData:
    model = ModelData(path.stem, metadata={"source_format": "OBJ"})
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        tag = parts[0].lower()
        if tag == "v" and len(parts) >= 4:
            model.vertices.append(tuple(float(value) for value in parts[1:4]))
        elif tag in {"f", "l"}:
            indices: list[int] = []
            for token in parts[1:]:
                raw = token.split("/")[0]
                if not raw:
                    continue
                index = int(raw)
                index = index - 1 if index > 0 else len(model.vertices) + index
                indices.append(index)
            if tag == "f" and len(indices) >= 3:
                model.faces.append(indices)
            elif tag == "l" and len(indices) >= 2:
                model.lines.append(indices)
        elif tag == "o" and len(parts) > 1:
            model.metadata["object_name"] = " ".join(parts[1:])
        elif tag in {"mtllib", "usemtl", "g"}:
            model.metadata.setdefault("obj_directives", []).append(stripped)
        elif tag in {"vn", "vt", "s"}:
            continue
        elif tag.startswith("v") and len(parts) < 4:
            raise ConversionError(f"OBJ 第 {line_number} 行顶点字段不足。")
    return model


def _read_ascii_stl(path: Path) -> ModelData:
    text = _read_text(path)
    if "facet" not in text.lower() or "vertex" not in text.lower():
        raise ConversionError("当前仅支持 ASCII STL；检测到的文件可能是二进制 STL。")
    model = ModelData(path.stem, metadata={"source_format": "STL"})
    vertex_map: dict[tuple[float, float, float], int] = {}
    current: list[int] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            vertex = tuple(float(value) for value in parts[1:4])
            index = vertex_map.get(vertex)
            if index is None:
                index = len(model.vertices)
                model.vertices.append(vertex)
                vertex_map[vertex] = index
            current.append(index)
            if len(current) == 3:
                model.faces.append(current)
                current = []
    return model


def _read_ascii_ply(path: Path) -> ModelData:
    lines = _read_text(path).splitlines()
    if not lines or lines[0].strip().lower() != "ply":
        raise ConversionError("PLY 文件头无效。")
    if not any(line.strip().lower() == "format ascii 1.0" for line in lines[:20]):
        raise ConversionError("当前仅支持 ASCII PLY。")

    vertex_count = 0
    face_count = 0
    vertex_properties: list[str] = []
    current_element = ""
    header_end = -1
    for index, line in enumerate(lines):
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "element" and len(parts) >= 3:
            current_element = parts[1]
            if current_element == "vertex":
                vertex_count = int(parts[2])
            elif current_element == "face":
                face_count = int(parts[2])
        elif parts[0] == "property" and current_element == "vertex" and len(parts) >= 3:
            vertex_properties.append(parts[-1])
        elif parts[0] == "end_header":
            header_end = index
            break
    if header_end < 0:
        raise ConversionError("PLY 缺少 end_header。")
    required = {"x", "y", "z"}
    if not required.issubset(set(vertex_properties)):
        raise ConversionError("PLY 顶点属性必须包含 x、y、z。")

    model = ModelData(path.stem, metadata={"source_format": "PLY"})
    x_idx = vertex_properties.index("x")
    y_idx = vertex_properties.index("y")
    z_idx = vertex_properties.index("z")
    cursor = header_end + 1
    for _ in range(vertex_count):
        values = lines[cursor].strip().split()
        cursor += 1
        model.vertices.append((float(values[x_idx]), float(values[y_idx]), float(values[z_idx])))
        props = {
            name: _auto_number(values[pos])
            for pos, name in enumerate(vertex_properties)
            if name not in required and pos < len(values)
        }
        model.vertex_properties.append(props)
    for _ in range(face_count):
        values = lines[cursor].strip().split()
        cursor += 1
        if not values:
            continue
        count = int(values[0])
        model.faces.append([int(value) for value in values[1:1 + count]])
    return model


def _read_legacy_vtk(path: Path) -> ModelData:
    lines = _read_text(path).splitlines()
    if len(lines) < 4 or "ASCII" not in lines[2].upper():
        raise ConversionError("当前仅支持 Legacy ASCII VTK。")
    model = ModelData(path.stem, metadata={"source_format": "VTK"})
    i = 0
    while i < len(lines):
        parts = lines[i].strip().split()
        if not parts:
            i += 1
            continue
        key = parts[0].upper()
        if key == "POINTS" and len(parts) >= 3:
            count = int(parts[1])
            values: list[float] = []
            i += 1
            while i < len(lines) and len(values) < count * 3:
                values.extend(float(value) for value in lines[i].split())
                i += 1
            model.vertices = [tuple(values[pos:pos + 3]) for pos in range(0, count * 3, 3)]  # type: ignore[list-item]
            continue
        if key in {"POLYGONS", "LINES", "VERTICES"} and len(parts) >= 3:
            count = int(parts[1])
            records: list[list[int]] = []
            i += 1
            while i < len(lines) and len(records) < count:
                tokens = [int(value) for value in lines[i].split()]
                i += 1
                if not tokens:
                    continue
                n = tokens[0]
                records.append(tokens[1:1 + n])
            if key == "POLYGONS":
                model.faces.extend(record for record in records if len(record) >= 3)
            elif key == "LINES":
                model.lines.extend(record for record in records if len(record) >= 2)
            continue
        i += 1
    return model


def _read_geojson(path: Path) -> ModelData:
    data = json.loads(_read_text(path))
    model = ModelData(path.stem, metadata={"source_format": "GeoJSON"})
    vertex_map: dict[tuple[float, float, float], int] = {}

    def add_vertex(value: Iterable[Any]) -> int:
        coords = list(value)
        if len(coords) < 2:
            raise ConversionError("GeoJSON 坐标维数不足。")
        vertex = (float(coords[0]), float(coords[1]), float(coords[2]) if len(coords) > 2 else 0.0)
        index = vertex_map.get(vertex)
        if index is None:
            index = len(model.vertices)
            model.vertices.append(vertex)
            vertex_map[vertex] = index
        return index

    def add_geometry(geometry: Any, properties: dict[str, Any] | None = None) -> None:
        if not isinstance(geometry, dict):
            return
        geo_type = str(geometry.get("type", ""))
        coordinates = geometry.get("coordinates")
        props = dict(properties or {})
        if geo_type == "Point":
            index = add_vertex(coordinates)
            while len(model.vertex_properties) < len(model.vertices):
                model.vertex_properties.append({})
            model.vertex_properties[index].update(props)
        elif geo_type == "MultiPoint":
            for point in coordinates or []:
                index = add_vertex(point)
                while len(model.vertex_properties) < len(model.vertices):
                    model.vertex_properties.append({})
                model.vertex_properties[index].update(props)
        elif geo_type == "LineString":
            model.lines.append([add_vertex(point) for point in coordinates or []])
        elif geo_type == "MultiLineString":
            for line in coordinates or []:
                model.lines.append([add_vertex(point) for point in line])
        elif geo_type == "Polygon":
            rings = coordinates or []
            if rings:
                ring = list(rings[0])
                if len(ring) > 1 and ring[0] == ring[-1]:
                    ring = ring[:-1]
                face = [add_vertex(point) for point in ring]
                if len(face) >= 3:
                    model.faces.append(face)
                    model.face_properties.append(props)
        elif geo_type == "MultiPolygon":
            for polygon in coordinates or []:
                if not polygon:
                    continue
                ring = list(polygon[0])
                if len(ring) > 1 and ring[0] == ring[-1]:
                    ring = ring[:-1]
                face = [add_vertex(point) for point in ring]
                if len(face) >= 3:
                    model.faces.append(face)
                    model.face_properties.append(props)
        elif geo_type == "GeometryCollection":
            for child in geometry.get("geometries", []):
                add_geometry(child, props)

    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        for feature in data.get("features", []):
            if isinstance(feature, dict):
                add_geometry(feature.get("geometry"), feature.get("properties") if isinstance(feature.get("properties"), dict) else {})
    elif isinstance(data, dict) and data.get("type") == "Feature":
        add_geometry(data.get("geometry"), data.get("properties") if isinstance(data.get("properties"), dict) else {})
    else:
        add_geometry(data)
    return model


def _read_csv_points(path: Path) -> ModelData:
    text = _read_text(path)
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise ConversionError("CSV/TXT 缺少表头。")

    aliases = {
        "x": {"x", "lon", "lng", "longitude", "easting", "东坐标", "经度"},
        "y": {"y", "lat", "latitude", "northing", "北坐标", "纬度"},
        "z": {"z", "elevation", "height", "altitude", "高程", "标高"},
    }
    mapping: dict[str, str] = {}
    for field_name in reader.fieldnames:
        normalized = field_name.strip().lower()
        for axis, names in aliases.items():
            if normalized in {name.lower() for name in names}:
                mapping[axis] = field_name
                break
    if "x" not in mapping or "y" not in mapping:
        raise ConversionError("CSV/TXT 未识别到 X/Y 或经纬度坐标字段。")

    model = ModelData(path.stem, metadata={"source_format": "CSV"})
    for row_number, row in enumerate(reader, start=2):
        try:
            x = float(row[mapping["x"]])
            y = float(row[mapping["y"]])
            z = float(row[mapping["z"]]) if "z" in mapping and str(row.get(mapping["z"], "")).strip() else 0.0
        except (TypeError, ValueError, KeyError) as exc:
            raise ConversionError(f"CSV/TXT 第 {row_number} 行坐标无效：{exc}") from exc
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise ConversionError(f"CSV/TXT 第 {row_number} 行存在非有限坐标。")
        model.vertices.append((x, y, z))
        coordinate_fields = set(mapping.values())
        model.vertex_properties.append({key: _auto_number(value) for key, value in row.items() if key not in coordinate_fields})
    return model


def _write_obj(model: ModelData, path: Path) -> None:
    lines = ["# Generated by geological model format converter", f"o {_safe_name(model.name)}"]
    lines.extend(f"v {_fmt(x)} {_fmt(y)} {_fmt(z)}" for x, y, z in model.vertices)
    lines.extend("f " + " ".join(str(index + 1) for index in face) for face in model.faces)
    lines.extend("l " + " ".join(str(index + 1) for index in line) for line in model.lines)
    if not model.faces and not model.lines:
        lines.extend(f"p {index + 1}" for index in range(len(model.vertices)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ascii_stl(model: ModelData, path: Path) -> None:
    triangles = list(_triangulated_faces(model.faces))
    if not triangles:
        raise ConversionError("STL 只能表达三角表面；当前数据没有可输出的面。")
    lines = [f"solid {_safe_name(model.name)}"]
    for a, b, c in triangles:
        p1, p2, p3 = model.vertices[a], model.vertices[b], model.vertices[c]
        normal = _normal(p1, p2, p3)
        lines.append(f"  facet normal {_fmt(normal[0])} {_fmt(normal[1])} {_fmt(normal[2])}")
        lines.append("    outer loop")
        for point in (p1, p2, p3):
            lines.append(f"      vertex {_fmt(point[0])} {_fmt(point[1])} {_fmt(point[2])}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {_safe_name(model.name)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ascii_ply(model: ModelData, path: Path) -> None:
    lines = [
        "ply",
        "format ascii 1.0",
        "comment Generated by geological model format converter",
        f"element vertex {len(model.vertices)}",
        "property double x",
        "property double y",
        "property double z",
        f"element face {len(model.faces)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    lines.extend(f"{_fmt(x)} {_fmt(y)} {_fmt(z)}" for x, y, z in model.vertices)
    lines.extend(f"{len(face)} " + " ".join(str(index) for index in face) for face in model.faces)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_legacy_vtk(model: ModelData, path: Path) -> None:
    lines = [
        "# vtk DataFile Version 3.0",
        "Geological model conversion output",
        "ASCII",
        "DATASET POLYDATA",
        f"POINTS {len(model.vertices)} double",
    ]
    lines.extend(f"{_fmt(x)} {_fmt(y)} {_fmt(z)}" for x, y, z in model.vertices)
    if model.faces:
        size = sum(len(face) + 1 for face in model.faces)
        lines.append(f"POLYGONS {len(model.faces)} {size}")
        lines.extend(f"{len(face)} " + " ".join(str(index) for index in face) for face in model.faces)
    if model.lines:
        size = sum(len(line) + 1 for line in model.lines)
        lines.append(f"LINES {len(model.lines)} {size}")
        lines.extend(f"{len(line)} " + " ".join(str(index) for index in line) for line in model.lines)
    if not model.faces and not model.lines:
        lines.append(f"VERTICES {len(model.vertices)} {len(model.vertices) * 2}")
        lines.extend(f"1 {index}" for index in range(len(model.vertices)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_geojson(model: ModelData, path: Path) -> None:
    features: list[dict[str, Any]] = []
    if model.faces:
        for index, face in enumerate(model.faces):
            ring = [list(model.vertices[vertex_index]) for vertex_index in face]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            properties = {"source": model.name, "face_id": index + 1}
            if index < len(model.face_properties):
                properties.update(_json_safe_dict(model.face_properties[index]))
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
    if model.lines:
        for index, line in enumerate(model.lines):
            features.append(
                {
                    "type": "Feature",
                    "properties": {"source": model.name, "line_id": index + 1},
                    "geometry": {"type": "LineString", "coordinates": [list(model.vertices[i]) for i in line]},
                }
            )
    if not model.faces and not model.lines:
        for index, vertex in enumerate(model.vertices):
            properties = {"source": model.name, "point_id": index + 1}
            if index < len(model.vertex_properties):
                properties.update(_json_safe_dict(model.vertex_properties[index]))
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {"type": "Point", "coordinates": list(vertex)},
                }
            )
    payload = {
        "type": "FeatureCollection",
        "name": model.name,
        "metadata": _json_safe_dict(model.metadata),
        "features": features,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(model: ModelData, path: Path) -> None:
    fields = model.attribute_fields
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["vertex_id", "x", "y", "z", *fields])
        writer.writeheader()
        for index, (x, y, z) in enumerate(model.vertices):
            row: dict[str, Any] = {"vertex_id": index + 1, "x": x, "y": y, "z": z}
            if index < len(model.vertex_properties):
                row.update(model.vertex_properties[index])
            writer.writerow(row)


def _write_ifc4(model: ModelData, path: Path) -> None:
    triangles = list(_triangulated_faces(model.faces))
    if not triangles:
        raise ConversionError("IFC4 三角面集输出需要表面面片；点数据请先生成网格或输出 GeoJSON/CSV/VTK。")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    points = ",".join(
        f"({_fmt_ifc(x)},{_fmt_ifc(y)},{_fmt_ifc(z)})" for x, y, z in model.vertices
    )
    indices = ",".join(f"({a + 1},{b + 1},{c + 1})" for a, b, c in triangles)
    name = _ifc_escape(model.name)

    entities = [
        "#1=IFCPERSON($,$,'Geo Converter',$,$,$,$,$);",
        "#2=IFCORGANIZATION($,'Geological Model Conversion Toolkit',$,$,$);",
        "#3=IFCPERSONANDORGANIZATION(#1,#2,$);",
        "#4=IFCAPPLICATION(#2,'1.0','Geological Model Conversion Toolkit','GEO-CONVERTER');",
        "#5=IFCOWNERHISTORY(#3,#4,$,.ADDED.,$,$,$,0);",
        "#6=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);",
        "#7=IFCUNITASSIGNMENT((#6));",
        "#8=IFCCARTESIANPOINT((0.,0.,0.));",
        "#9=IFCDIRECTION((0.,0.,1.));",
        "#10=IFCDIRECTION((1.,0.,0.));",
        "#11=IFCAXIS2PLACEMENT3D(#8,#9,#10);",
        "#12=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#11,$);",
        f"#13=IFCPROJECT('{_ifc_guid()}',#5,'{name}',$,$,$,$,(#12),#7);",
        "#14=IFCLOCALPLACEMENT($,#11);",
        f"#15=IFCSITE('{_ifc_guid()}',#5,'Geological Model Site',$,$,#14,$,$,.ELEMENT.,$,$,$,$,$);",
        f"#16=IFCRELAGGREGATES('{_ifc_guid()}',#5,$,$,#13,(#15));",
        "#17=IFCLOCALPLACEMENT(#14,#11);",
        f"#18=IFCCARTESIANPOINTLIST3D(({points}));",
        f"#19=IFCTRIANGULATEDFACESET(#18,$,.T.,({indices}),$);",
        "#20=IFCSHAPEREPRESENTATION(#12,'Body','Tessellation',(#19));",
        "#21=IFCPRODUCTDEFINITIONSHAPE($,$,(#20));",
        f"#22=IFCBUILDINGELEMENTPROXY('{_ifc_guid()}',#5,'{name}',$,'Converted geological surface',#17,#21,$,$);",
        f"#23=IFCRELCONTAINEDINSPATIALSTRUCTURE('{_ifc_guid()}',#5,$,$,(#22),#15);",
    ]
    content = "\n".join(
        [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');",
            f"FILE_NAME('{_ifc_escape(path.name)}','{timestamp}',('Geo Converter'),('Geological Model Conversion Toolkit'),'Python','Geological Model Conversion Toolkit','');",
            "FILE_SCHEMA(('IFC4'));",
            "ENDSEC;",
            "DATA;",
            *entities,
            "ENDSEC;",
            "END-ISO-10303-21;",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _triangulated_faces(faces: list[list[int]]) -> Iterable[tuple[int, int, int]]:
    for face in faces:
        for index in range(1, len(face) - 1):
            yield face[0], face[index], face[index + 1]


def _normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-15:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def _build_target_path(output_dir: Path, stem: str, target_format: str, overwrite: bool) -> Path:
    suffix_map = {
        "GEOJSON": ".geojson",
        "CSV": ".csv",
        "OBJ": ".obj",
        "STL": ".stl",
        "PLY": ".ply",
        "VTK": ".vtk",
        "IFC": ".ifc",
    }
    suffix = suffix_map[target_format]
    candidate = output_dir / f"{stem}_converted{suffix}"
    if overwrite or not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = output_dir / f"{stem}_converted_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _write_manifest(output_dir: Path, report: dict[str, Any], overwrite: bool = True) -> str:
    manifest = output_dir / "conversion_manifest.json"
    if not overwrite and manifest.exists():
        manifest = _build_target_path(output_dir, "conversion_manifest", "GEOJSON", overwrite=False).with_suffix(".json")
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(manifest.resolve())


def _failed_report(
    file_paths: list[str],
    output_dir: Path,
    target_format: str,
    coordinate_rule: str,
    attribute_rule: str,
    message: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "task": "model_format_conversion",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "失败",
        "target_platform": "未知",
        "target_format": target_format,
        "output_dir": str(output_dir.resolve()),
        "coordinate_rule": coordinate_rule,
        "attribute_rule": attribute_rule,
        "source_count": len(file_paths),
        "success_count": 0,
        "failure_count": max(1, len(file_paths)),
        "warning_count": 0,
        "quality_score": 0,
        "artifacts": [],
        "warnings": [],
        "errors": [message],
    }
    report["manifest_path"] = _write_manifest(output_dir, report, overwrite=True)
    return report


def _fmt(value: float) -> str:
    return f"{value:.12g}"


def _fmt_ifc(value: float) -> str:
    text = f"{value:.12g}"
    if "e" in text.lower():
        return text.upper()
    if "." not in text:
        text += "."
    return text


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value).strip("_") or "model"


def _ifc_escape(value: str) -> str:
    return value.replace("'", "''")


def _ifc_guid() -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
    value = uuid.uuid4().int
    chars = []
    for _ in range(22):
        chars.append(alphabet[value & 0x3F])
        value >>= 6
    return "".join(reversed(chars))


def _auto_number(value: Any) -> Any:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer() and not any(ch in text.lower() for ch in (".", "e")):
        return int(number)
    return number


def _json_safe_dict(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if item is None or isinstance(item, (str, int, float, bool)):
            safe[str(key)] = item
        elif isinstance(item, (list, tuple)):
            safe[str(key)] = list(item)
        else:
            safe[str(key)] = str(item)
    return safe


__all__ = [
    "ATTRIBUTE_RULES",
    "COORDINATE_RULES",
    "SUPPORTED_SOURCE_SUFFIXES",
    "SUPPORTED_TARGET_FORMATS",
    "TARGET_PLATFORM_FORMATS",
    "ConversionError",
    "ModelData",
    "apply_attribute_rule",
    "apply_coordinate_rule",
    "build_conversion_plan",
    "convert_model_files",
    "infer_target_platform",
    "normalize_target_format",
    "read_model",
    "write_model",
]
