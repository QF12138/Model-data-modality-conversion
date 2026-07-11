from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


CATEGORY_NAMES = {
    "geometry": "几何闭合性",
    "topology": "拓扑关系",
    "attributes": "属性完整性",
    "consistency": "一致性",
    "coordinate": "坐标精度",
}


def build_model_quality_report(file_paths: list[str]) -> dict[str, Any]:
    report = _new_quality_report()
    if not file_paths:
        _add_issue(report, "consistency", "未选择文件", "严重", "请先加载需要检查的模型或成果文件。")

    for file_path in file_paths:
        _inspect_file(Path(file_path), report)

    coords = report["coordinates"]
    if not coords:
        _add_issue(report, "coordinate", "全部文件", "警告", "未识别到可用于坐标精度检查的坐标序列。")
    else:
        _check_coordinate_precision(coords, report)

    severity_cost = {"严重": 10, "警告": 4, "提示": 1}
    score = 100 - sum(severity_cost.get(issue["severity"], 1) for issue in report["issues"])
    report["score"] = max(0, min(100, score))
    report["grade"] = _quality_grade(report["score"])
    report["issue_count"] = len(report["issues"])
    report["file_count"] = len(file_paths)

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

    report.pop("coordinates", None)
    return report


def _new_quality_report() -> dict[str, Any]:
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "files": [],
        "issues": [],
        "coordinates": [],
        "categories": [
            {"key": "geometry", "name": "几何闭合性", "status": "通过", "issues": 0, "summary": "几何边界未发现明显开口。"},
            {"key": "topology", "name": "拓扑关系", "status": "通过", "issues": 0, "summary": "拓扑引用和重复关系正常。"},
            {"key": "attributes", "name": "属性完整性", "status": "通过", "issues": 0, "summary": "属性字段未发现明显缺失。"},
            {"key": "consistency", "name": "一致性", "status": "通过", "issues": 0, "summary": "数据结构和类型保持一致。"},
            {"key": "coordinate", "name": "坐标精度", "status": "通过", "issues": 0, "summary": "坐标值与精度未发现明显异常。"},
        ],
    }


def _quality_grade(score: int) -> str:
    if score == 0:
        return "待检查"
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "合格"
    return "需复核"


def _add_issue(report: dict[str, Any], category_key: str, file_name: str, severity: str, message: str) -> None:
    report["issues"].append(
        {
            "category_key": category_key,
            "category": CATEGORY_NAMES.get(category_key, category_key),
            "file": file_name,
            "severity": severity,
            "message": message,
        }
    )


def _inspect_file(path: Path, report: dict[str, Any]) -> None:
    file_entry = {"path": str(path), "name": path.name, "type": path.suffix.lower() or "unknown", "status": "已检查"}
    report["files"].append(file_entry)

    if not path.exists():
        file_entry["status"] = "不存在"
        _add_issue(report, "consistency", path.name, "严重", "文件不存在或路径不可访问。")
        return

    suffix = path.suffix.lower()
    try:
        if suffix == ".obj":
            _inspect_obj(path, report)
        elif suffix in {".json", ".geojson"}:
            _inspect_json(path, report)
        elif suffix in {".csv", ".txt"}:
            _inspect_csv(path, report)
        else:
            _add_issue(report, "consistency", path.name, "提示", f"{suffix or '未知'} 格式暂未内置解析，已登记文件，后续交由后端模型解析器检查。")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, ValueError) as exc:
        file_entry["status"] = "解析失败"
        _add_issue(report, "consistency", path.name, "严重", f"文件解析失败：{exc}")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _inspect_obj(path: Path, report: dict[str, Any]) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    material_used = False

    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if parts[0] == "v" and len(parts) >= 4:
            xyz = tuple(float(value) for value in parts[1:4])
            vertices.append(xyz)
            report["coordinates"].extend(xyz)
        elif parts[0] == "f" and len(parts) >= 4:
            face: list[int] = []
            for token in parts[1:]:
                raw = token.split("/")[0]
                if raw:
                    index = int(raw)
                    face.append(index if index > 0 else len(vertices) + 1 + index)
            faces.append(face)
        elif parts[0] in {"usemtl", "mtllib"}:
            material_used = True

    if not vertices:
        _add_issue(report, "geometry", path.name, "严重", "OBJ 文件未读取到顶点数据。")
    if not faces:
        _add_issue(report, "geometry", path.name, "警告", "OBJ 文件未读取到面片，无法判断几何闭合性。")

    vertex_count = len(vertices)
    invalid_faces = [face for face in faces if any(index < 1 or index > vertex_count for index in face)]
    if invalid_faces:
        _add_issue(report, "topology", path.name, "严重", f"存在 {len(invalid_faces)} 个面片引用了不存在的顶点。")

    edge_count: dict[tuple[int, int], int] = {}
    for face in faces:
        for pos, start in enumerate(face):
            end = face[(pos + 1) % len(face)]
            edge = tuple(sorted((start, end)))
            edge_count[edge] = edge_count.get(edge, 0) + 1

    if edge_count:
        boundary_edges = sum(1 for count in edge_count.values() if count == 1)
        nonmanifold_edges = sum(1 for count in edge_count.values() if count > 2)
        if boundary_edges:
            _add_issue(report, "geometry", path.name, "严重", f"检测到 {boundary_edges} 条边界边，模型可能未闭合。")
        if nonmanifold_edges:
            _add_issue(report, "topology", path.name, "严重", f"检测到 {nonmanifold_edges} 条非流形边。")

    duplicate_vertices = len(vertices) - len(set(vertices))
    if duplicate_vertices:
        _add_issue(report, "consistency", path.name, "警告", f"存在 {duplicate_vertices} 个重复顶点。")
    if not material_used:
        _add_issue(report, "attributes", path.name, "提示", "OBJ 未发现材质或属性引用，属性完整性需结合外部属性表复核。")


def _inspect_json(path: Path, report: dict[str, Any]) -> None:
    data = json.loads(_read_text(path))
    coordinates: list[float] = []
    _collect_json_coordinates(data, coordinates)
    report["coordinates"].extend(coordinates)
    if not coordinates:
        _add_issue(report, "coordinate", path.name, "警告", "JSON/GeoJSON 中未识别到 coordinates 坐标。")

    features = data.get("features", []) if isinstance(data, dict) else []
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        if not isinstance(features, list) or not features:
            _add_issue(report, "geometry", path.name, "严重", "FeatureCollection 不包含有效 feature。")
        property_keys: list[set[str]] = []
        empty_properties = 0
        missing_geometry = 0
        for feature in features:
            if not isinstance(feature, dict):
                _add_issue(report, "consistency", path.name, "警告", "存在非对象类型 feature。")
                continue
            if not feature.get("geometry"):
                missing_geometry += 1
            props = feature.get("properties")
            if not isinstance(props, dict) or not props:
                empty_properties += 1
            else:
                property_keys.append(set(props.keys()))
            _check_geojson_geometry_closed(feature.get("geometry"), path.name, report)
        if missing_geometry:
            _add_issue(report, "geometry", path.name, "严重", f"存在 {missing_geometry} 个 feature 缺少 geometry。")
        if empty_properties:
            _add_issue(report, "attributes", path.name, "警告", f"存在 {empty_properties} 个 feature 属性为空。")
        if property_keys and len({tuple(sorted(keys)) for keys in property_keys}) > 1:
            _add_issue(report, "consistency", path.name, "警告", "Feature 属性字段集合不一致。")
    else:
        geometry = data.get("geometry", data) if isinstance(data, dict) else data
        _check_geojson_geometry_closed(geometry, path.name, report)


def _collect_json_coordinates(value: object, out: list[float]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "coordinates":
                _flatten_numeric_coordinates(child, out)
            else:
                _collect_json_coordinates(child, out)
    elif isinstance(value, list):
        for child in value:
            _collect_json_coordinates(child, out)


def _flatten_numeric_coordinates(value: object, out: list[float]) -> None:
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            out.append(float(value))
    elif isinstance(value, list):
        for child in value:
            _flatten_numeric_coordinates(child, out)


def _check_geojson_geometry_closed(geometry: object, file_name: str, report: dict[str, Any]) -> None:
    if not isinstance(geometry, dict):
        return
    geo_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geo_type == "Polygon" and isinstance(coordinates, list):
        for ring in coordinates:
            if isinstance(ring, list) and ring and ring[0] != ring[-1]:
                _add_issue(report, "geometry", file_name, "严重", "Polygon 存在未闭合环。")
    elif geo_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            for ring in polygon if isinstance(polygon, list) else []:
                if isinstance(ring, list) and ring and ring[0] != ring[-1]:
                    _add_issue(report, "geometry", file_name, "严重", "MultiPolygon 存在未闭合环。")


def _inspect_csv(path: Path, report: dict[str, Any]) -> None:
    text = _read_text(path)
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        _add_issue(report, "attributes", path.name, "严重", "表格文件缺少表头，无法检查属性完整性。")
        return

    rows = list(reader)
    if not rows:
        _add_issue(report, "attributes", path.name, "警告", "表格文件没有数据行。")
        return

    missing_cells = 0
    inconsistent_rows = 0
    id_values: list[str] = []
    coord_columns = _detect_coordinate_columns(reader.fieldnames)
    has_id = "id" in {name.lower() for name in reader.fieldnames}

    for row in rows:
        if None in row:
            inconsistent_rows += 1
        missing_cells += sum(1 for value in row.values() if value is None or not str(value).strip())
        if has_id:
            for key, value in row.items():
                if key and key.lower() == "id" and value:
                    id_values.append(value)
        for column in coord_columns:
            value = row.get(column, "")
            try:
                number = float(value)
            except (TypeError, ValueError):
                _add_issue(report, "coordinate", path.name, "警告", f"坐标字段 {column} 存在非数值：{value!r}")
                continue
            if math.isfinite(number):
                report["coordinates"].append(number)

    if missing_cells:
        _add_issue(report, "attributes", path.name, "警告", f"发现 {missing_cells} 个空属性值。")
    if inconsistent_rows:
        _add_issue(report, "consistency", path.name, "严重", f"发现 {inconsistent_rows} 行列数与表头不一致。")
    if id_values and len(id_values) != len(set(id_values)):
        _add_issue(report, "topology", path.name, "警告", "存在重复 id，可能造成模型对象关联冲突。")
    if not coord_columns:
        _add_issue(report, "coordinate", path.name, "提示", "未识别到常见坐标字段，坐标精度检查范围受限。")


def _detect_coordinate_columns(fieldnames: list[str]) -> list[str]:
    aliases = {"x", "y", "z", "lon", "lat", "lng", "longitude", "latitude", "easting", "northing", "elevation", "height"}
    return [name for name in fieldnames if name and name.strip().lower() in aliases]


def _check_coordinate_precision(coords: list[float], report: dict[str, Any]) -> None:
    nonfinite = [value for value in coords if not math.isfinite(value)]
    if nonfinite:
        _add_issue(report, "coordinate", "坐标序列", "严重", f"发现 {len(nonfinite)} 个非有限坐标值。")

    finite = [value for value in coords if math.isfinite(value)]
    if not finite:
        return

    max_abs = max(abs(value) for value in finite)
    if max_abs > 100000000:
        _add_issue(report, "coordinate", "坐标序列", "警告", "坐标绝对值超过 1e8，请确认坐标系或单位是否正确。")

    low_precision = sum(1 for value in finite if "." not in f"{value:.12f}".rstrip("0"))
    if low_precision and low_precision / len(finite) > 0.8:
        _add_issue(report, "coordinate", "坐标序列", "提示", "多数坐标为整数，若为工程模型需复核精度是否满足要求。")
