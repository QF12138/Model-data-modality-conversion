from __future__ import annotations

import csv
import json
import math
import re
import struct
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


CATEGORY_NAMES = {
    "geometry": "几何闭合性",
    "topology": "拓扑关系",
    "attributes": "属性完整性",
    "consistency": "一致性",
    "coordinate": "坐标精度",
}

SUPPORTED_FORMATS = (".obj", ".stl", ".ply", ".vtk", ".json", ".geojson", ".csv", ".txt", ".ifc")

ISSUE_SUGGESTIONS = {
    "FILE_NOT_FOUND": "确认文件路径、访问权限和成果交付清单后重新检查。",
    "UNSUPPORTED_FORMAT": "先转换为 OBJ、STL、PLY、VTK、GeoJSON、CSV 或 IFC，或接入对应格式解析器。",
    "PARSE_ERROR": "使用原始软件重新导出 ASCII/标准格式，并检查文件是否完整。",
    "EMPTY_GEOMETRY": "重新导出模型几何，确认顶点与单元没有被过滤。",
    "NO_FACES": "补充面片或单元拓扑；点数据应改用 CSV/GeoJSON 点要素表达。",
    "INVALID_INDEX": "删除或重建引用越界顶点的面片/单元。",
    "DEGENERATE_FACE": "删除零面积面，或合并重合顶点后重新三角化。",
    "OPEN_BOUNDARY": "定位边界边并补面、缝合或执行封闭实体修复。",
    "NON_MANIFOLD_EDGE": "拆分多重连接边或重建局部拓扑，使每条实体边恰由两个面共享。",
    "INCONSISTENT_ORIENTATION": "统一相邻面片的顶点绕序与法向方向。",
    "DUPLICATE_VERTEX": "按配置容差合并重复顶点并更新面片索引。",
    "DUPLICATE_FACE": "删除重复面片并重新计算法向和拓扑关系。",
    "MISSING_ATTRIBUTE": "补齐必填属性，或在质量规则中明确允许为空的字段。",
    "INCONSISTENT_SCHEMA": "统一全部记录的字段集合、字段类型和空值表示。",
    "DUPLICATE_ID": "为对象分配唯一标识并修复关联表中的外键。",
    "INVALID_COORDINATE": "修复非数值或 NaN/Inf 坐标，并核对源数据解析规则。",
    "COORDINATE_RANGE": "核对坐标系、单位和轴顺序，必要时执行坐标转换。",
    "COORDINATE_PRECISION": "按项目精度要求重新导出坐标，避免过度取整。",
    "INVALID_RING": "补足环顶点并确保首尾坐标一致。",
    "MISSING_GEOMETRY": "补充 feature 的 geometry，或从成果中移除无空间对象记录。",
    "INVALID_IFC_STRUCTURE": "使用 IFC 校验器或 BIM 软件重新导出完整 IFC STEP 文件。",
    "MISSING_MATERIAL": "补充材质/属性引用，或关联独立属性表。",
}


@dataclass(slots=True)
class QualityRules:
    """模型质量检查规则；所有数值均可由界面或 API 覆盖。"""

    require_closed_geometry: bool = True
    check_topology: bool = True
    check_attributes: bool = True
    check_consistency: bool = True
    check_coordinate: bool = True
    required_attributes: tuple[str, ...] = ()
    max_missing_ratio: float = 0.0
    coordinate_max_abs: float = 100_000_000.0
    minimum_decimal_places: int = 0
    duplicate_vertex_tolerance: float = 1e-9
    degenerate_area_tolerance: float = 1e-12

    def normalized(self) -> "QualityRules":
        return QualityRules(
            require_closed_geometry=bool(self.require_closed_geometry),
            check_topology=bool(self.check_topology),
            check_attributes=bool(self.check_attributes),
            check_consistency=bool(self.check_consistency),
            check_coordinate=bool(self.check_coordinate),
            required_attributes=tuple(dict.fromkeys(str(item).strip() for item in self.required_attributes if str(item).strip())),
            max_missing_ratio=max(0.0, min(1.0, float(self.max_missing_ratio))),
            coordinate_max_abs=max(0.0, float(self.coordinate_max_abs)),
            minimum_decimal_places=max(0, int(self.minimum_decimal_places)),
            duplicate_vertex_tolerance=max(0.0, float(self.duplicate_vertex_tolerance)),
            degenerate_area_tolerance=max(0.0, float(self.degenerate_area_tolerance)),
        )


def build_model_quality_report(
    file_paths: list[str],
    rules: QualityRules | dict[str, Any] | None = None,
    *,
    required_attributes: Iterable[str] | None = None,
    minimum_decimal_places: int | None = None,
) -> dict[str, Any]:
    """检查转换成果并返回包含定位、问题码和修复建议的结构化质量报告。"""

    effective = _coerce_rules(rules, required_attributes, minimum_decimal_places)
    report = _new_quality_report(effective)
    if not file_paths:
        _add_issue(report, "consistency", "未选择文件", "严重", "FILE_NOT_FOUND", "未选择需要检查的模型或成果文件。", "输入列表")

    for file_path in file_paths:
        _inspect_file(Path(file_path), report, effective)

    if effective.check_coordinate:
        records = report["_coordinate_records"]
        if not records:
            _add_issue(
                report, "coordinate", "全部文件", "警告", "INVALID_COORDINATE",
                "未识别到可用于坐标精度检查的坐标序列。", "全部文件",
            )
        else:
            _check_coordinate_precision(records, report, effective)

    _finalize_report(report, file_paths)
    report.pop("_coordinate_records", None)
    return report


def _coerce_rules(
    rules: QualityRules | dict[str, Any] | None,
    required_attributes: Iterable[str] | None,
    minimum_decimal_places: int | None,
) -> QualityRules:
    if isinstance(rules, QualityRules):
        effective = rules
    elif isinstance(rules, dict):
        allowed = set(QualityRules.__dataclass_fields__)
        effective = QualityRules(**{key: value for key, value in rules.items() if key in allowed})
    else:
        effective = QualityRules()
    data = asdict(effective)
    if required_attributes is not None:
        data["required_attributes"] = tuple(required_attributes)
    if minimum_decimal_places is not None:
        data["minimum_decimal_places"] = minimum_decimal_places
    return QualityRules(**data).normalized()


def _new_quality_report(rules: QualityRules) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "supported_formats": list(SUPPORTED_FORMATS),
        "parameters": asdict(rules),
        "files": [],
        "issues": [],
        "_coordinate_records": [],
        "categories": [
            {"key": "geometry", "name": "几何闭合性", "status": "通过", "issues": 0, "summary": "几何边界闭合且未发现退化单元。"},
            {"key": "topology", "name": "拓扑关系", "status": "通过", "issues": 0, "summary": "索引、流形关系和面片方向正常。"},
            {"key": "attributes", "name": "属性完整性", "status": "通过", "issues": 0, "summary": "必填属性和标识字段完整。"},
            {"key": "consistency", "name": "一致性", "status": "通过", "issues": 0, "summary": "数据结构、字段类型和重复关系正常。"},
            {"key": "coordinate", "name": "坐标精度", "status": "通过", "issues": 0, "summary": "坐标值、范围和小数精度符合当前规则。"},
        ],
    }


def _finalize_report(report: dict[str, Any], file_paths: list[str]) -> None:
    severity_cost = {"严重": 10, "警告": 4, "提示": 1}
    severity_counts = Counter(issue["severity"] for issue in report["issues"])
    report["severity_counts"] = {key: severity_counts.get(key, 0) for key in ("严重", "警告", "提示")}
    report["score"] = max(0, min(100, 100 - sum(severity_cost.get(issue["severity"], 1) for issue in report["issues"])))
    report["grade"] = _quality_grade(report["score"], bool(file_paths))
    report["issue_count"] = len(report["issues"])
    report["file_count"] = len(file_paths)
    report["passed"] = bool(file_paths) and severity_counts.get("严重", 0) == 0 and severity_counts.get("警告", 0) == 0

    for category in report["categories"]:
        related = [issue for issue in report["issues"] if issue["category_key"] == category["key"]]
        category["issues"] = len(related)
        severities = {issue["severity"] for issue in related}
        if "严重" in severities:
            category["status"] = "未通过"
        elif "警告" in severities:
            category["status"] = "需复核"
        else:
            category["status"] = "通过"
        if related:
            category["summary"] = related[0]["message"]

    issues_by_file = Counter(issue["file"] for issue in report["issues"])
    for entry in report["files"]:
        entry["issue_count"] = issues_by_file.get(entry["name"], 0)
        if entry["status"] == "已检查" and entry["issue_count"]:
            entry["status"] = "发现问题"


def _quality_grade(score: int, has_input: bool) -> str:
    if not has_input:
        return "待检查"
    if score >= 95:
        return "优秀"
    if score >= 85:
        return "良好"
    if score >= 70:
        return "合格"
    return "需复核"


def _add_issue(
    report: dict[str, Any], category_key: str, file_name: str, severity: str,
    code: str, message: str, location: str = "", suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    report["issues"].append({
        "issue_id": f"Q-{len(report['issues']) + 1:04d}",
        "code": code,
        "category_key": category_key,
        "category": CATEGORY_NAMES.get(category_key, category_key),
        "file": file_name,
        "location": location or "文件级",
        "severity": severity,
        "message": message,
        "suggestion": suggestion or ISSUE_SUGGESTIONS.get(code, "结合源数据和项目质量规则进行人工复核。"),
        "details": details or {},
    })


def _inspect_file(path: Path, report: dict[str, Any], rules: QualityRules) -> None:
    entry = {
        "path": str(path), "name": path.name, "type": path.suffix.lower() or "unknown",
        "status": "已检查", "supported": path.suffix.lower() in SUPPORTED_FORMATS, "metrics": {},
    }
    report["files"].append(entry)
    if not path.is_file():
        entry["status"] = "不存在"
        _add_issue(report, "consistency", path.name, "严重", "FILE_NOT_FOUND", "文件不存在或路径不可访问。", str(path))
        return

    handlers = {
        ".obj": _inspect_obj,
        ".stl": _inspect_stl,
        ".ply": _inspect_ply,
        ".vtk": _inspect_vtk,
        ".json": _inspect_json,
        ".geojson": _inspect_json,
        ".csv": _inspect_csv,
        ".txt": _inspect_csv,
        ".ifc": _inspect_ifc,
    }
    handler = handlers.get(path.suffix.lower())
    if handler is None:
        entry["status"] = "格式不支持"
        _add_issue(report, "consistency", path.name, "警告", "UNSUPPORTED_FORMAT", f"{path.suffix or '未知'} 格式没有内置质量解析器。", "文件格式")
        return
    try:
        handler(path, report, entry, rules)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, ValueError, struct.error) as exc:
        entry["status"] = "解析失败"
        _add_issue(report, "consistency", path.name, "严重", "PARSE_ERROR", f"文件解析失败：{exc}", "文件内容")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _record_point(
    report: dict[str, Any], file_name: str, location: str,
    values: Iterable[Any], raw_values: Iterable[str] | None = None,
) -> tuple[float, float, float] | None:
    raw = list(raw_values or [])
    parsed: list[float] = []
    for index, value in enumerate(values):
        try:
            number = float(value)
        except (TypeError, ValueError):
            _add_issue(report, "coordinate", file_name, "严重", "INVALID_COORDINATE", f"坐标值 {value!r} 不是有效数字。", location)
            return None
        decimals = _decimal_places(raw[index] if index < len(raw) else str(value))
        report["_coordinate_records"].append({"value": number, "file": file_name, "location": location, "decimals": decimals})
        parsed.append(number)
    if len(parsed) < 3:
        parsed.extend([0.0] * (3 - len(parsed)))
    return parsed[0], parsed[1], parsed[2]


def _decimal_places(text: str) -> int:
    token = str(text).strip().lower()
    if "e" in token:
        try:
            mantissa, exponent = token.split("e", 1)
            return max(0, len(mantissa.partition(".")[2]) - int(exponent))
        except ValueError:
            return 0
    return len(token.partition(".")[2].rstrip("0"))


def _inspect_obj(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    face_locations: list[str] = []
    material_used = False
    for line_no, line in enumerate(_read_text(path).splitlines(), start=1):
        parts = line.strip().split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v" and len(parts) >= 4:
            point = _record_point(report, path.name, f"第 {line_no} 行顶点", parts[1:4], parts[1:4])
            if point is not None:
                vertices.append(point)
        elif parts[0] == "f" and len(parts) >= 4:
            face: list[int] = []
            for token in parts[1:]:
                raw = token.split("/", 1)[0]
                if raw:
                    index = int(raw)
                    face.append(index - 1 if index > 0 else len(vertices) + index)
            faces.append(face)
            face_locations.append(f"第 {line_no} 行面片")
        elif parts[0] in {"usemtl", "mtllib", "g", "o"}:
            material_used = True
    entry["metrics"].update(vertex_count=len(vertices), face_count=len(faces))
    _check_mesh(path.name, vertices, faces, face_locations, report, rules)
    if rules.check_attributes and not material_used:
        _add_issue(report, "attributes", path.name, "提示", "MISSING_MATERIAL", "OBJ 未发现材质、分组或对象属性引用。", "OBJ 属性")


def _inspect_stl(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    data = path.read_bytes()
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    locations: list[str] = []
    if len(data) >= 84 and 84 + struct.unpack("<I", data[80:84])[0] * 50 == len(data):
        triangle_count = struct.unpack("<I", data[80:84])[0]
        offset = 84
        for triangle in range(triangle_count):
            values = struct.unpack("<12fH", data[offset:offset + 50])
            face = []
            for point_index in range(3):
                xyz = values[3 + point_index * 3:6 + point_index * 3]
                point = _record_point(report, path.name, f"二进制三角形 {triangle + 1} 顶点 {point_index + 1}", xyz)
                if point is not None:
                    vertices.append(point)
                    face.append(len(vertices) - 1)
            faces.append(face)
            locations.append(f"二进制三角形 {triangle + 1}")
            offset += 50
    else:
        current: list[int] = []
        triangle = 0
        for line_no, line in enumerate(_read_text(path).splitlines(), start=1):
            parts = line.strip().split()
            if len(parts) == 4 and parts[0].lower() == "vertex":
                point = _record_point(report, path.name, f"第 {line_no} 行顶点", parts[1:4], parts[1:4])
                if point is not None:
                    vertices.append(point)
                    current.append(len(vertices) - 1)
                if len(current) == 3:
                    triangle += 1
                    faces.append(current)
                    locations.append(f"三角形 {triangle}")
                    current = []
    vertices, faces = _weld_mesh(vertices, faces, rules.duplicate_vertex_tolerance)
    entry["metrics"].update(vertex_count=len(vertices), face_count=len(faces))
    _check_mesh(path.name, vertices, faces, locations, report, rules)


def _inspect_ply(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    lines = _read_text(path).splitlines()
    if not lines or lines[0].strip().lower() != "ply":
        raise ValueError("PLY 缺少 ply 文件头。")
    if not any("format ascii" in line.lower() for line in lines[:10]):
        raise ValueError("当前质量检查仅支持 ASCII PLY。")
    vertex_count = face_count = 0
    vertex_properties: list[str] = []
    header_end = -1
    current_element = ""
    for index, line in enumerate(lines):
        parts = line.strip().split()
        if parts[:1] == ["element"] and len(parts) >= 3:
            current_element = parts[1].lower()
            if current_element == "vertex":
                vertex_count = int(parts[2])
            elif current_element == "face":
                face_count = int(parts[2])
        elif parts[:1] == ["property"] and current_element == "vertex" and len(parts) >= 3:
            vertex_properties.append(parts[-1])
        elif line.strip() == "end_header":
            header_end = index
            break
    if header_end < 0:
        raise ValueError("PLY 缺少 end_header。")
    lower_props = [item.lower() for item in vertex_properties]
    try:
        xyz_indexes = [lower_props.index(axis) for axis in ("x", "y", "z")]
    except ValueError as exc:
        raise ValueError("PLY 顶点属性缺少 x/y/z。") from exc
    vertices = []
    for offset, line in enumerate(lines[header_end + 1:header_end + 1 + vertex_count]):
        parts = line.split()
        raw = [parts[index] for index in xyz_indexes]
        point = _record_point(report, path.name, f"顶点 {offset + 1}", raw, raw)
        if point is not None:
            vertices.append(point)
    faces: list[list[int]] = []
    locations: list[str] = []
    face_start = header_end + 1 + vertex_count
    for offset, line in enumerate(lines[face_start:face_start + face_count]):
        parts = line.split()
        count = int(parts[0]) if parts else 0
        faces.append([int(value) for value in parts[1:1 + count]])
        locations.append(f"面片 {offset + 1}")
    entry["metrics"].update(vertex_count=len(vertices), face_count=len(faces), vertex_properties=vertex_properties)
    _check_mesh(path.name, vertices, faces, locations, report, rules)


def _inspect_vtk(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    tokens = _read_text(path).replace("\r", " ").split()
    upper = [token.upper() for token in tokens]
    if "BINARY" in upper[:20]:
        raise ValueError("当前质量检查仅支持 ASCII legacy VTK。")
    try:
        point_index = upper.index("POINTS")
        point_count = int(tokens[point_index + 1])
    except (ValueError, IndexError) as exc:
        raise ValueError("VTK 缺少 POINTS 段。") from exc
    start = point_index + 3
    vertices = []
    for index in range(point_count):
        raw = tokens[start + index * 3:start + index * 3 + 3]
        point = _record_point(report, path.name, f"POINTS[{index}]", raw, raw)
        if point is not None:
            vertices.append(point)
    faces: list[list[int]] = []
    locations: list[str] = []
    section = next((name for name in ("POLYGONS", "CELLS") if name in upper), None)
    if section:
        index = upper.index(section)
        cell_count = int(tokens[index + 1])
        cursor = index + 3
        for cell in range(cell_count):
            count = int(tokens[cursor])
            cursor += 1
            faces.append([int(value) for value in tokens[cursor:cursor + count]])
            locations.append(f"{section}[{cell}]")
            cursor += count
    entry["metrics"].update(vertex_count=len(vertices), cell_count=len(faces))
    _check_mesh(path.name, vertices, faces, locations, report, rules)


def _check_mesh(
    file_name: str, vertices: list[tuple[float, float, float]], faces: list[list[int]],
    locations: list[str], report: dict[str, Any], rules: QualityRules,
) -> None:
    if not vertices:
        _add_issue(report, "geometry", file_name, "严重", "EMPTY_GEOMETRY", "文件未读取到顶点数据。", "几何数据")
        return
    if not faces:
        _add_issue(report, "geometry", file_name, "警告", "NO_FACES", "文件未读取到面片或单元，无法判断闭合性。", "拓扑数据")
        return

    valid_faces: list[tuple[int, list[int]]] = []
    invalid_locations: list[str] = []
    degenerate_locations: list[str] = []
    canonical_faces: Counter[tuple[int, ...]] = Counter()
    for index, face in enumerate(faces):
        location = locations[index] if index < len(locations) else f"面片 {index + 1}"
        if len(face) < 3 or any(vertex < 0 or vertex >= len(vertices) for vertex in face):
            invalid_locations.append(location)
            continue
        valid_faces.append((index, face))
        canonical_faces[tuple(sorted(face))] += 1
        if _face_area(vertices, face) <= rules.degenerate_area_tolerance:
            degenerate_locations.append(location)
    if invalid_locations:
        _add_issue(report, "topology", file_name, "严重", "INVALID_INDEX", f"存在 {len(invalid_locations)} 个无效面片或越界索引。", _location_summary(invalid_locations), details={"locations": invalid_locations})
    if degenerate_locations:
        _add_issue(report, "geometry", file_name, "严重", "DEGENERATE_FACE", f"存在 {len(degenerate_locations)} 个零面积或退化面片。", _location_summary(degenerate_locations), details={"locations": degenerate_locations})
    duplicate_faces = sum(count - 1 for count in canonical_faces.values() if count > 1)
    if rules.check_consistency and duplicate_faces:
        _add_issue(report, "consistency", file_name, "警告", "DUPLICATE_FACE", f"存在 {duplicate_faces} 个重复面片。", "面片集合")

    edge_uses: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for face_index, face in valid_faces:
        for pos, start in enumerate(face):
            end = face[(pos + 1) % len(face)]
            edge_uses[tuple(sorted((start, end)))].append((start, end))
    boundary = [edge for edge, uses in edge_uses.items() if len(uses) == 1]
    nonmanifold = [edge for edge, uses in edge_uses.items() if len(uses) > 2]
    bad_orientation = [edge for edge, uses in edge_uses.items() if len(uses) == 2 and uses[0] == uses[1]]
    if rules.require_closed_geometry and boundary:
        _add_issue(report, "geometry", file_name, "严重", "OPEN_BOUNDARY", f"检测到 {len(boundary)} 条边界边，模型未形成封闭实体。", _location_summary([str(edge) for edge in boundary]), details={"edge_count": len(boundary), "sample_edges": boundary[:20]})
    if rules.check_topology and nonmanifold:
        _add_issue(report, "topology", file_name, "严重", "NON_MANIFOLD_EDGE", f"检测到 {len(nonmanifold)} 条非流形边。", _location_summary([str(edge) for edge in nonmanifold]), details={"edge_count": len(nonmanifold), "sample_edges": nonmanifold[:20]})
    if rules.check_topology and bad_orientation:
        _add_issue(report, "topology", file_name, "警告", "INCONSISTENT_ORIENTATION", f"检测到 {len(bad_orientation)} 条相邻面同向使用的边。", _location_summary([str(edge) for edge in bad_orientation]), details={"edge_count": len(bad_orientation), "sample_edges": bad_orientation[:20]})

    duplicate_vertices = _duplicate_vertex_groups(vertices, rules.duplicate_vertex_tolerance)
    if rules.check_consistency and duplicate_vertices:
        duplicate_count = sum(len(group) - 1 for group in duplicate_vertices)
        _add_issue(report, "consistency", file_name, "警告", "DUPLICATE_VERTEX", f"在容差 {rules.duplicate_vertex_tolerance:g} 内存在 {duplicate_count} 个重复顶点。", _location_summary([str(group) for group in duplicate_vertices]), details={"groups": duplicate_vertices[:20]})


def _face_area(vertices: list[tuple[float, float, float]], face: list[int]) -> float:
    origin = vertices[face[0]]
    area = 0.0
    for index in range(1, len(face) - 1):
        a, b = vertices[face[index]], vertices[face[index + 1]]
        ux, uy, uz = a[0] - origin[0], a[1] - origin[1], a[2] - origin[2]
        vx, vy, vz = b[0] - origin[0], b[1] - origin[1], b[2] - origin[2]
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        area += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return area


def _duplicate_vertex_groups(vertices: list[tuple[float, float, float]], tolerance: float) -> list[list[int]]:
    if tolerance <= 0:
        groups: dict[tuple[float, float, float], list[int]] = defaultdict(list)
        for index, vertex in enumerate(vertices):
            groups[vertex].append(index)
    else:
        scale = 1.0 / tolerance
        groups = defaultdict(list)
        for index, vertex in enumerate(vertices):
            groups[tuple(round(value * scale) for value in vertex)].append(index)
    return [items for items in groups.values() if len(items) > 1]


def _weld_mesh(
    vertices: list[tuple[float, float, float]], faces: list[list[int]], tolerance: float,
) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    """将 STL 等逐面重复顶点的格式焊接为共享拓扑。"""
    effective = tolerance if tolerance > 0 else 1e-12
    scale = 1.0 / effective
    lookup: dict[tuple[int, int, int], int] = {}
    welded: list[tuple[float, float, float]] = []
    remap: dict[int, int] = {}
    for old_index, vertex in enumerate(vertices):
        key = tuple(round(value * scale) for value in vertex)
        if key not in lookup:
            lookup[key] = len(welded)
            welded.append(vertex)
        remap[old_index] = lookup[key]
    return welded, [[remap.get(index, index) for index in face] for face in faces]


def _location_summary(locations: list[str], limit: int = 5) -> str:
    if not locations:
        return "文件级"
    shown = "、".join(locations[:limit])
    return shown if len(locations) <= limit else f"{shown} 等 {len(locations)} 处"


def _inspect_json(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    data = json.loads(_read_text(path))
    if not isinstance(data, dict):
        raise ValueError("JSON 根节点必须是对象。")
    features = data.get("features") if data.get("type") == "FeatureCollection" else [data]
    if not isinstance(features, list) or not features:
        _add_issue(report, "geometry", path.name, "严重", "EMPTY_GEOMETRY", "FeatureCollection 不包含有效 feature。", "features")
        return
    schemas: list[set[str]] = []
    geometry_count = 0
    for index, feature in enumerate(features):
        location = f"features[{index}]"
        if not isinstance(feature, dict):
            _add_issue(report, "consistency", path.name, "严重", "INCONSISTENT_SCHEMA", "feature 不是 JSON 对象。", location)
            continue
        geometry = feature.get("geometry") if feature.get("type") == "Feature" else feature.get("geometry", feature)
        properties = feature.get("properties", {}) if feature.get("type") == "Feature" else feature.get("properties", {})
        if not isinstance(geometry, dict):
            _add_issue(report, "geometry", path.name, "严重", "MISSING_GEOMETRY", "feature 缺少有效 geometry。", f"{location}.geometry")
        else:
            geometry_count += 1
            _inspect_geojson_geometry(geometry, path.name, f"{location}.geometry", report, rules)
        if rules.check_attributes:
            if not isinstance(properties, dict):
                _add_issue(report, "attributes", path.name, "严重", "INCONSISTENT_SCHEMA", "properties 不是对象。", f"{location}.properties")
            else:
                schemas.append(set(properties))
                missing = [name for name in rules.required_attributes if not _present(properties.get(name))]
                if missing:
                    _add_issue(report, "attributes", path.name, "严重", "MISSING_ATTRIBUTE", f"缺少必填属性：{', '.join(missing)}。", f"{location}.properties", details={"fields": missing})
                empty = [name for name, value in properties.items() if not _present(value)]
                if empty:
                    _add_issue(report, "attributes", path.name, "警告", "MISSING_ATTRIBUTE", f"存在空属性：{', '.join(empty)}。", f"{location}.properties", details={"fields": empty})
    if rules.check_consistency and schemas and len({tuple(sorted(schema)) for schema in schemas}) > 1:
        _add_issue(report, "consistency", path.name, "警告", "INCONSISTENT_SCHEMA", "Feature 属性字段集合不一致。", "features[*].properties")
    entry["metrics"].update(feature_count=len(features), geometry_count=geometry_count)


def _inspect_geojson_geometry(
    geometry: dict[str, Any], file_name: str, location: str,
    report: dict[str, Any], rules: QualityRules,
) -> None:
    geo_type = str(geometry.get("type", ""))
    coordinates = geometry.get("coordinates")
    if geo_type == "GeometryCollection":
        for index, child in enumerate(geometry.get("geometries", []) or []):
            if isinstance(child, dict):
                _inspect_geojson_geometry(child, file_name, f"{location}.geometries[{index}]", report, rules)
        return
    if coordinates is None:
        _add_issue(report, "geometry", file_name, "严重", "MISSING_GEOMETRY", f"{geo_type or 'Geometry'} 缺少 coordinates。", location)
        return
    _collect_coordinate_tuples(coordinates, file_name, f"{location}.coordinates", report)
    if geo_type in {"Polygon", "MultiPolygon"}:
        polygons = [coordinates] if geo_type == "Polygon" else coordinates
        for polygon_index, polygon in enumerate(polygons if isinstance(polygons, list) else []):
            for ring_index, ring in enumerate(polygon if isinstance(polygon, list) else []):
                ring_location = f"{location}.coordinates[{polygon_index}][{ring_index}]" if geo_type == "MultiPolygon" else f"{location}.coordinates[{ring_index}]"
                if not isinstance(ring, list) or len(ring) < 4:
                    _add_issue(report, "geometry", file_name, "严重", "INVALID_RING", "面环至少需要 4 个坐标点。", ring_location)
                elif rules.require_closed_geometry and ring[0] != ring[-1]:
                    _add_issue(report, "geometry", file_name, "严重", "OPEN_BOUNDARY", "Polygon 面环首尾坐标不一致。", ring_location)


def _collect_coordinate_tuples(value: Any, file_name: str, location: str, report: dict[str, Any]) -> None:
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float, str)) for item in value[:3]):
        _record_point(report, file_name, location, value[:3])
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_coordinate_tuples(child, file_name, f"{location}[{index}]", report)


def _inspect_csv(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    text = _read_text(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        _add_issue(report, "attributes", path.name, "严重", "MISSING_ATTRIBUTE", "表格缺少表头。", "第 1 行")
        return
    fieldnames = [str(name).strip() for name in reader.fieldnames if name is not None]
    rows = list(reader)
    entry["metrics"].update(row_count=len(rows), field_count=len(fieldnames), fields=fieldnames)
    if not rows:
        _add_issue(report, "attributes", path.name, "警告", "MISSING_ATTRIBUTE", "表格没有数据行。", "第 2 行")
        return

    lower_to_original = {name.lower(): name for name in fieldnames}
    missing_headers = [name for name in rules.required_attributes if name.lower() not in lower_to_original]
    if rules.check_attributes and missing_headers:
        _add_issue(report, "attributes", path.name, "严重", "MISSING_ATTRIBUTE", f"缺少必填字段：{', '.join(missing_headers)}。", "表头", details={"fields": missing_headers})
    coordinate_columns = _detect_coordinate_columns(fieldnames)
    id_column = next((lower_to_original[name] for name in ("id", "object_id", "feature_id", "global_id") if name in lower_to_original), None)
    id_locations: dict[str, list[int]] = defaultdict(list)
    column_types: dict[str, set[str]] = defaultdict(set)
    missing_by_field: Counter[str] = Counter()
    malformed_rows: list[int] = []
    for row_index, row in enumerate(rows, start=2):
        if None in row:
            malformed_rows.append(row_index)
        for field_name in fieldnames:
            value = row.get(field_name)
            if not _present(value):
                missing_by_field[field_name] += 1
            else:
                column_types[field_name].add(_value_type(str(value)))
        if id_column and _present(row.get(id_column)):
            id_locations[str(row[id_column])].append(row_index)
        if coordinate_columns:
            raw = [row.get(column, "") for column in coordinate_columns[:3]]
            _record_point(report, path.name, f"第 {row_index} 行坐标", raw, [str(value) for value in raw])
    if rules.check_attributes:
        for field_name, missing_count in missing_by_field.items():
            ratio = missing_count / len(rows)
            if ratio > rules.max_missing_ratio:
                severity = "严重" if field_name in rules.required_attributes or ratio >= 0.5 else "警告"
                _add_issue(report, "attributes", path.name, severity, "MISSING_ATTRIBUTE", f"字段“{field_name}”缺失 {missing_count}/{len(rows)}（{ratio:.1%}），超过阈值 {rules.max_missing_ratio:.1%}。", f"列 {field_name}", details={"field": field_name, "missing_count": missing_count, "ratio": ratio})
    if malformed_rows and rules.check_consistency:
        _add_issue(report, "consistency", path.name, "严重", "INCONSISTENT_SCHEMA", f"存在 {len(malformed_rows)} 行列数与表头不一致。", _location_summary([f"第 {row} 行" for row in malformed_rows]), details={"rows": malformed_rows})
    mixed = [field for field, types in column_types.items() if len(types) > 1 and types != {"integer", "number"}]
    if mixed and rules.check_consistency:
        _add_issue(report, "consistency", path.name, "警告", "INCONSISTENT_SCHEMA", f"字段类型不一致：{', '.join(mixed)}。", "数据列", details={"fields": mixed})
    duplicates = {value: locations for value, locations in id_locations.items() if len(locations) > 1}
    if duplicates and rules.check_topology:
        locations = [f"ID={value} 行 {rows}" for value, rows in list(duplicates.items())[:10]]
        _add_issue(report, "topology", path.name, "严重", "DUPLICATE_ID", f"存在 {len(duplicates)} 个重复对象标识。", _location_summary(locations), details={"duplicates": duplicates})
    if not coordinate_columns and rules.check_coordinate:
        _add_issue(report, "coordinate", path.name, "提示", "INVALID_COORDINATE", "未识别到常见坐标字段，坐标精度检查范围受限。", "表头")


def _detect_coordinate_columns(fieldnames: list[str]) -> list[str]:
    groups = (
        ("x", "easting", "longitude", "lon", "lng", "经度", "东坐标"),
        ("y", "northing", "latitude", "lat", "纬度", "北坐标"),
        ("z", "elevation", "height", "altitude", "高程", "标高"),
    )
    normalized = {name.strip().lower(): name for name in fieldnames}
    result = []
    for aliases in groups:
        match = next((normalized[alias] for alias in aliases if alias in normalized), None)
        if match:
            result.append(match)
    return result


def _value_type(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return "text"
    return "integer" if number.is_integer() else "number"


def _present(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in {"", "null", "none", "nan", "n/a"}


def _inspect_ifc(path: Path, report: dict[str, Any], entry: dict[str, Any], rules: QualityRules) -> None:
    text = _read_text(path)
    upper = text.upper()
    if "ISO-10303-21;" not in upper or "HEADER;" not in upper or "DATA;" not in upper or "END-ISO-10303-21;" not in upper:
        _add_issue(report, "consistency", path.name, "严重", "INVALID_IFC_STRUCTURE", "IFC STEP 文件头、DATA 段或结束标记不完整。", "IFC 文件结构")
    entities = re.findall(r"(?im)^\s*#(\d+)\s*=\s*(IFC[A-Z0-9_]+)\s*\(", text)
    ids = [item[0] for item in entities]
    duplicate_ids = [value for value, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        _add_issue(report, "topology", path.name, "严重", "DUPLICATE_ID", f"IFC 实体编号重复：{', '.join(duplicate_ids[:10])}。", "DATA 段")
    points = re.finditer(r"(?i)IFCCARTESIANPOINT\s*\(\s*\(([^)]*)\)\s*\)", text)
    point_count = 0
    for point_count, match in enumerate(points, start=1):
        raw = [item.strip() for item in match.group(1).split(",")]
        _record_point(report, path.name, f"IfcCartesianPoint {point_count}", raw, raw)
    products = len(re.findall(r"(?i)=\s*IFC(?:BUILDINGELEMENTPROXY|WALL|SLAB|BEAM|COLUMN|FOOTING|PILE|SITE)\s*\(", text))
    global_ids = re.findall(r"(?im)^\s*#\d+\s*=\s*IFC(?:BUILDINGELEMENTPROXY|WALL|SLAB|BEAM|COLUMN|FOOTING|PILE|SITE)\s*\(\s*'([^']*)'", text)
    if rules.check_attributes and products and any(not value.strip() for value in global_ids):
        _add_issue(report, "attributes", path.name, "严重", "MISSING_ATTRIBUTE", "IFC 产品存在空 GlobalId。", "IFC 产品实体")
    if rules.check_topology and global_ids and len(global_ids) != len(set(global_ids)):
        _add_issue(report, "topology", path.name, "严重", "DUPLICATE_ID", "IFC 产品 GlobalId 不唯一。", "IFC 产品实体")
    if not entities:
        _add_issue(report, "geometry", path.name, "严重", "EMPTY_GEOMETRY", "IFC DATA 段未识别到实体。", "DATA 段")
    entry["metrics"].update(entity_count=len(entities), cartesian_point_count=point_count, product_count=products)


def _check_coordinate_precision(records: list[dict[str, Any]], report: dict[str, Any], rules: QualityRules) -> None:
    nonfinite = [record for record in records if not math.isfinite(record["value"])]
    if nonfinite:
        _add_issue(report, "coordinate", "坐标序列", "严重", "INVALID_COORDINATE", f"发现 {len(nonfinite)} 个 NaN/Inf 坐标值。", _location_summary([record["location"] for record in nonfinite]), details={"locations": [record["location"] for record in nonfinite[:50]]})
    finite = [record for record in records if math.isfinite(record["value"])]
    out_of_range = [record for record in finite if abs(record["value"]) > rules.coordinate_max_abs]
    if out_of_range:
        files = sorted({record["file"] for record in out_of_range})
        _add_issue(report, "coordinate", "、".join(files), "警告", "COORDINATE_RANGE", f"发现 {len(out_of_range)} 个坐标绝对值超过 {rules.coordinate_max_abs:g}。", _location_summary([record["location"] for record in out_of_range]), details={"threshold": rules.coordinate_max_abs, "count": len(out_of_range)})
    if rules.minimum_decimal_places > 0:
        low_precision = [record for record in finite if record["decimals"] < rules.minimum_decimal_places]
        ratio = len(low_precision) / len(finite) if finite else 0.0
        if ratio > 0.2:
            files = sorted({record["file"] for record in low_precision})
            _add_issue(report, "coordinate", "、".join(files), "警告", "COORDINATE_PRECISION", f"有 {len(low_precision)}/{len(finite)} 个坐标小数位少于 {rules.minimum_decimal_places} 位。", _location_summary([record["location"] for record in low_precision]), details={"minimum_decimal_places": rules.minimum_decimal_places, "ratio": ratio})


__all__ = ["CATEGORY_NAMES", "SUPPORTED_FORMATS", "QualityRules", "build_model_quality_report"]
