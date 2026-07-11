from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class FieldProfile:
    """单个字段的概要信息。"""

    name: str
    total: int = 0
    missing: int = 0
    null_ratio: float = 0.0
    unique: int = 0
    duplicate_count: int = 0
    outlier_count: int = 0
    dtype: str = "unknown"
    min_val: float | None = None
    max_val: float | None = None
    mean_val: float | None = None
    std_val: float | None = None
    unit_detected: str | None = None
    unit_standardized: bool = False
    sample_values: list[Any] = field(default_factory=list)


@dataclass
class DataIssue:
    """数据质量缺陷。"""
    severity: str          # 严重 / 警告 / 提示
    category: str          # 字段校验 / 缺失值 / 重复数据 / 异常值 / 单位规范
    file: str
    field: str | None
    row: int | None
    message: str
    suggestion: str = ""


CATEGORY_NAMES = {
    "field_validation": "字段校验",
    "missing_values": "缺失值识别",
    "duplicates": "重复数据清理",
    "outliers": "异常值检查",
    "unit_normalization": "单位规范化",
}

# 常见坐标字段别名
COORD_ALIASES: dict[str, set[str]] = {
    "x": {"x", "lon", "lng", "longitude", "easting", "东坐标", "经度", "e", "x_coord"},
    "y": {"y", "lat", "latitude", "northing", "北坐标", "纬度", "n", "y_coord"},
    "z": {"z", "elevation", "height", "altitude", "depth", "高程", "标高", "深度", "h", "z_coord"},
}

# 常见必填字段（按数据类型关键词匹配）
REQUIRED_FIELD_HINTS: dict[str, list[str]] = {
    "钻孔": ["钻孔编号", "孔口X", "孔口Y", "孔口高程", "孔深"],
    "borehole": ["borehole_id", "x", "y", "z", "depth"],
    "剖面": ["剖面编号", "起点X", "起点Y", "终点X", "终点Y"],
    "点云": ["x", "y", "z"],
    "point_cloud": ["x", "y", "z"],
    "栅格": ["x", "y", "pixel_value"],
    "矢量": ["geometry", "feature_type"],
    "网格": ["vertex_id", "x", "y", "z"],
    "mesh": ["vertex_id", "x", "y", "z"],
    "表格": [],
    "tabular": [],
}

# 单位换算表 —— 全部换算到 SI 基准
UNIT_CONVERSIONS: dict[str, tuple[str, float]] = {
    # 长度 → m
    "mm": ("m", 0.001),
    "cm": ("m", 0.01),
    "m": ("m", 1.0),
    "meter": ("m", 1.0),
    "metre": ("m", 1.0),
    "km": ("m", 1000.0),
    "inch": ("m", 0.0254),
    "in": ("m", 0.0254),
    "ft": ("m", 0.3048),
    "feet": ("m", 0.3048),
    # 角度 → rad
    "deg": ("rad", math.pi / 180),
    "degree": ("rad", math.pi / 180),
    "rad": ("rad", 1.0),
    "radian": ("rad", 1.0),
    # 质量 → kg
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "t": ("kg", 1000.0),
    "ton": ("kg", 1000.0),
    # 力 / 应力 → Pa / N
    "n": ("N", 1.0),
    "kn": ("N", 1000.0),
    "mn": ("N", 1_000_000),
    "pa": ("Pa", 1.0),
    "kpa": ("Pa", 1000.0),
    "mpa": ("Pa", 1_000_000),
    "gpa": ("Pa", 1_000_000_000),
    # 密度 → kg/m³
    "g/cm3": ("kg/m3", 1000.0),
    "g/cc": ("kg/m3", 1000.0),
    "kg/m3": ("kg/m3", 1.0),
    # 时间 → s
    "s": ("s", 1.0),
    "min": ("s", 60.0),
    "h": ("s", 3600.0),
    "hr": ("s", 3600.0),
    "d": ("s", 86400.0),
    "day": ("s", 86400.0),
}


def _auto_number(value: Any) -> Any:
    """将字符串尽量转为数值，失败则返回原值。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        n = float(text)
    except ValueError:
        return text
    return int(n) if n.is_integer() and not any(ch in text.lower() for ch in (".", "e")) else n


def _read_text(path: Path) -> str:
    """多编码尝试读取文本。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _detect_dtype(values: list[Any]) -> str:
    """推断字段的数据类型。"""
    numeric = 0
    null = 0
    for v in values:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            null += 1
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            numeric += 1
        elif isinstance(v, str):
            try:
                float(v)
                numeric += 1
            except ValueError:
                pass
    total = len(values) - null
    if total == 0:
        return "empty"
    if numeric / max(total, 1) > 0.8:
        return "numeric"
    return "text"


def _detect_field_unit(field_name: str, values: list[float]) -> str | None:
    """根据字段名和数值范围猜测单位。"""
    name_lower = field_name.lower().strip()
    # 角度字段
    if any(token in name_lower for token in ("angle", "dip", "倾角", "倾向", "方位", "strike", "trend", "plunge")):
        # 如果值在 0-360 范围，可能是度
        if values:
            max_abs = max(abs(v) for v in values)
            if max_abs <= 360:
                return "deg"
            if max_abs <= 2 * math.pi + 0.1:
                return "rad"
        return "deg"
    # 坐标字段 —— 如果数值很大（> 1e5），可能是 mm
    if any(token in name_lower for token in ("x", "y", "z", "easting", "northing", "坐标", "经度", "纬度", "高程", "标高")):
        if values:
            max_abs = max(abs(v) for v in values)
            if max_abs > 1e6:
                return "mm"
            if max_abs > 1e3:
                return "m"
        return "m"
    # 深度 / 厚度字段
    if any(token in name_lower for token in ("depth", "thick", "深", "厚", "孔", "borehole")):
        if values:
            max_abs = max(abs(v) for v in values)
            if max_abs < 0.5:
                return "mm"
            if max_abs < 500:
                return "m"
        return "m"
    # 应力 / 强度字段
    if any(token in name_lower for token in ("stress", "strength", "modulus", "模量", "强度", "应力", "pressure", "压")):
        if values:
            max_abs = max(abs(v) for v in values)
            if max_abs > 1e8:
                return "Pa"
            if max_abs > 1e5:
                return "kPa"
            if max_abs > 100:
                return "MPa"
        return "kPa"
    return None


# ============================================================================
# 核心入口
# ============================================================================

def build_preprocessing_report(
    file_paths: list[str],
    required_fields: list[str] | None = None,
    duplicate_keys: list[str] | None = None,
    outlier_sigma: float = 3.0,
    unit_standard: str = "SI",
    auto_fix: bool = False,
) -> dict[str, Any]:
    """
    对导入数据执行预处理与质量清洗，返回结构化报告。

    参数
    ----
    file_paths : list[str]
        待清洗的文件路径列表。
    required_fields : list[str] | None
        全局必填字段。置空则根据数据类型自动推断。
    duplicate_keys : list[str] | None
        判定重复记录的键字段。置空则以全部字段组合判定。
    outlier_sigma : float
        异常值判定标准差倍数（默认 3σ，约为 0.3% 概率）。
    unit_standard : str
        目标单位体系（当前仅支持 "SI"）。
    auto_fix : bool
        是否自动修正可修复问题（当前为报告模式，不原地改动源文件）。
    """
    report = _new_preprocessing_report()
    report["parameters"] = {
        "required_fields": required_fields,
        "duplicate_keys": duplicate_keys,
        "outlier_sigma": outlier_sigma,
        "unit_standard": unit_standard,
        "auto_fix": auto_fix,
    }

    if not file_paths:
        _add_issue(
            report,
            "field_validation",
            file_name="全部文件",
            severity="警告",
            message="未选择待清洗数据文件。请通过「添加数据」导入钻孔、剖面、点云、栅格、矢量、网格或表格文件。",
        )
        return _finalize(report, file_paths)

    for file_path in file_paths:
        path = Path(file_path)
        entry: dict[str, Any] = {
            "path": str(path),
            "name": path.name,
            "type": path.suffix.lower() or "unknown",
            "status": "已清洗",
        }
        report["files"].append(entry)

        if not path.exists():
            entry["status"] = "文件缺失"
            _add_issue(report, "field_validation", file_name=path.name, severity="严重", message="文件不存在或路径不可访问。")
            continue

        try:
            suffix = path.suffix.lower()
            if suffix in {".csv", ".txt"}:
                _inspect_tabular(path, report, entry, required_fields, duplicate_keys, outlier_sigma)
            elif suffix in {".json", ".geojson"}:
                _inspect_geospatial(path, report, entry, required_fields, outlier_sigma)
            elif suffix == ".obj":
                _inspect_obj(path, report, entry, outlier_sigma)
            elif suffix == ".stl":
                _inspect_stl(path, report, entry, outlier_sigma)
            elif suffix in {".ply", ".vtk"}:
                _inspect_tabular_like_mesh(path, report, entry, required_fields, outlier_sigma)
            else:
                entry["status"] = "格式未识别"
                _add_issue(
                    report, "field_validation", file_name=path.name, severity="提示",
                    message=f"{suffix or '未知'} 格式暂未内置预处理解析器，已登记文件，后续交由后端解析器处理。",
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, ValueError) as exc:
            entry["status"] = "解析失败"
            _add_issue(report, "field_validation", file_name=path.name, severity="严重", message=f"文件解析失败：{exc}")

    return _finalize(report, file_paths)


# ============================================================================
# 内部：报告构建
# ============================================================================

def _new_preprocessing_report() -> dict[str, Any]:
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "files": [],
        "fields": [],
        "issues": [],
        "categories": [
            {"key": key, "name": name, "status": "通过", "issue_count": 0, "summary": "未发现问题。"}
            for key, name in CATEGORY_NAMES.items()
        ],
    }


def _add_issue(
    report: dict[str, Any],
    category_key: str,
    file_name: str,
    severity: str,
    message: str,
    field_name: str | None = None,
    row: int | None = None,
    suggestion: str = "",
) -> None:
    report["issues"].append(
        {
            "category_key": category_key,
            "category": CATEGORY_NAMES.get(category_key, category_key),
            "file": file_name,
            "field": field_name,
            "row": row,
            "severity": severity,
            "message": message,
            "suggestion": suggestion,
        }
    )


def _finalize(report: dict[str, Any], file_paths: list[str]) -> dict[str, Any]:
    """汇总评分与分类状态。"""
    severity_cost = {"严重": 12, "警告": 5, "提示": 2}
    score = 100 - sum(severity_cost.get(issue["severity"], 1) for issue in report["issues"])
    report["score"] = max(0, min(100, score))
    report["grade"] = _grade(report["score"])
    report["issue_count"] = len(report["issues"])
    report["file_count"] = len(file_paths)

    for category in report["categories"]:
        related = [i for i in report["issues"] if i["category_key"] == category["key"]]
        category["issue_count"] = len(related)
        severities = {i["severity"] for i in related}
        if "严重" in severities:
            category["status"] = "未通过"
        elif "警告" in severities:
            category["status"] = "需复核"
        elif "提示" in severities:
            category["status"] = "通过（有提示）"
        else:
            category["status"] = "通过"
        if related:
            category["summary"] = related[0]["message"]

    return report


def _grade(score: int) -> str:
    if score >= 95:
        return "优秀"
    if score >= 85:
        return "良好"
    if score >= 70:
        return "合格"
    return "需复核"


def _merge_field_profile(report: dict[str, Any], profile: FieldProfile) -> None:
    """将字段概要写入报告的 fields 列表。"""
    report["fields"].append(
        {
            "name": profile.name,
            "total": profile.total,
            "missing": profile.missing,
            "null_ratio": round(profile.null_ratio, 4),
            "unique": profile.unique,
            "duplicate_count": profile.duplicate_count,
            "outlier_count": profile.outlier_count,
            "dtype": profile.dtype,
            "min_val": profile.min_val,
            "max_val": profile.max_val,
            "mean_val": profile.mean_val,
            "std_val": profile.std_val,
            "unit_detected": profile.unit_detected,
            "unit_standardized": profile.unit_standardized,
            "sample_values": profile.sample_values[:5],
        }
    )


# ============================================================================
# 内部：文件解析与检查
# ============================================================================

def _evaluate_fields(
    rows: list[dict[str, Any]],
    field_names: list[str],
    file_name: str,
    report: dict[str, Any],
    required_fields: list[str] | None = None,
    duplicate_keys: list[str] | None = None,
    outlier_sigma: float = 3.0,
) -> None:
    """对一行行字典数据进行字段、缺失、重复、异常和单位检查。"""
    total = len(rows)
    if total == 0:
        _add_issue(report, "field_validation", file_name=file_name, severity="警告", message="数据文件没有记录行。")
        return

    # ---- 1. 字段校验 ----
    req_set = {f.strip().lower() for f in (required_fields or [])}
    actual_set = {f.lower() for f in field_names}
    missing_required = req_set - actual_set
    if missing_required:
        _add_issue(
            report, "field_validation", file_name=file_name, severity="严重",
            message=f"缺少必填字段：{', '.join(sorted(missing_required))}。",
            suggestion="补充对应字段列，或调整必填规则配置。",
        )

    # ---- 2. 逐字段分析 ----
    for fname in field_names:
        values = [_auto_number(row.get(fname)) for row in rows]
        missing = sum(1 for v in values if v is None or (isinstance(v, str) and v.strip() == ""))
        non_null = [v for v in values if v is not None and not (isinstance(v, str) and v.strip() == "")]
        numeric_vals = [v for v in non_null if isinstance(v, (int, float)) and not isinstance(v, bool)]

        profile = FieldProfile(
            name=fname,
            total=total,
            missing=missing,
            null_ratio=missing / total if total else 0.0,
            unique=len(set(str(v) for v in non_null)),
            dtype=_detect_dtype(values),
            sample_values=non_null[:5],
        )

        # 重复
        if non_null:
            value_counts = Counter(str(v) for v in non_null)
            profile.duplicate_count = sum(c - 1 for c in value_counts.values() if c > 1)

        # 异常值（仅数值型）
        if len(numeric_vals) >= 3:
            n = len(numeric_vals)
            mean = sum(numeric_vals) / n
            variance = sum((v - mean) ** 2 for v in numeric_vals) / n
            std = math.sqrt(variance)
            profile.min_val = min(numeric_vals)
            profile.max_val = max(numeric_vals)
            profile.mean_val = round(mean, 6)
            profile.std_val = round(std, 6)
            if std > 1e-12:
                profile.outlier_count = sum(1 for v in numeric_vals if abs(v - mean) > outlier_sigma * std)
                if profile.outlier_count:
                    outlier_ratio = profile.outlier_count / n
                    sev = "严重" if outlier_ratio > 0.1 else "警告" if outlier_ratio > 0.03 else "提示"
                    _add_issue(
                        report, "outliers", file_name=file_name, field_name=fname, severity=sev,
                        message=f"字段“{fname}”检测到 {profile.outlier_count} 个异常值（{outlier_ratio:.1%}，>{outlier_sigma}σ）。",
                        suggestion="排查异常值来源，确认是否为采集错误或合理的极端工况。",
                    )
            # 单位检测
            unit = _detect_field_unit(fname, numeric_vals)
            if unit and unit != "m":
                profile.unit_detected = unit
                if unit in UNIT_CONVERSIONS:
                    target, factor = UNIT_CONVERSIONS[unit]
                    if factor != 1.0:
                        _add_issue(
                            report, "unit_normalization", file_name=file_name, field_name=fname, severity="提示",
                            message=f"字段“{fname}”疑似单位为 {unit}，建议转换为 {target}（×{factor}）。",
                            suggestion=f"将数值乘以 {factor} 以归一到 {target} 单位体系。",
                        )

        # 缺失严重度
        if profile.null_ratio > 0.5:
            _add_issue(
                report, "missing_values", file_name=file_name, field_name=fname, severity="严重",
                message=f"字段“{fname}”缺失率 {profile.null_ratio:.1%}（>{50}%）。",
                suggestion="该字段可用信息过少，建议补充数据或标记为不可用。",
            )
        elif profile.null_ratio > 0.1:
            _add_issue(
                report, "missing_values", file_name=file_name, field_name=fname, severity="警告",
                message=f"字段“{fname}”缺失率 {profile.null_ratio:.1%}。",
                suggestion="可考虑均值/中位数填补或插值处理。",
            )

        _merge_field_profile(report, profile)

    # ---- 3. 重复行检查 ----
    dup_keys = duplicate_keys or field_names
    key_set: set[tuple[str, ...]] = set()
    dup_count = 0
    for row_idx, row in enumerate(rows, start=2):
        key = tuple(str(row.get(k, "")) for k in dup_keys)
        if key in key_set:
            dup_count += 1
        else:
            key_set.add(key)
    if dup_count:
        _add_issue(
            report, "duplicates", file_name=file_name, severity="警告" if dup_count > 5 else "提示",
            message=f"发现 {dup_count} 行重复记录（基于 {len(dup_keys)} 个键字段）。",
            suggestion="确认是否为数据采集重复，必要时去重或标记。",
        )


# ---- 表格型文件 (CSV/TXT) ----

def _inspect_tabular(
    path: Path,
    report: dict[str, Any],
    entry: dict[str, Any],
    required_fields: list[str] | None,
    duplicate_keys: list[str] | None,
    outlier_sigma: float,
) -> None:
    text = _read_text(path)
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        _add_issue(report, "field_validation", file_name=path.name, severity="严重", message="CSV/TXT 缺少表头。")
        return
    rows = list(reader)
    entry["row_count"] = len(rows)
    entry["field_count"] = len(reader.fieldnames)
    _evaluate_fields(rows, list(reader.fieldnames), path.name, report, required_fields, duplicate_keys, outlier_sigma)


# ---- 地理空间文件 (GeoJSON/JSON) ----

def _inspect_geospatial(
    path: Path,
    report: dict[str, Any],
    entry: dict[str, Any],
    required_fields: list[str] | None,
    outlier_sigma: float,
) -> None:
    data = json.loads(_read_text(path))
    features: list[dict[str, Any]] = []
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = [f for f in data.get("features", []) if isinstance(f, dict)]
    elif isinstance(data, dict) and data.get("type") == "Feature":
        features = [data]
    elif isinstance(data, list):
        features = [f for f in data if isinstance(f, dict)]

    if not features:
        _add_issue(report, "field_validation", file_name=path.name, severity="警告", message="未找到可解析的 Feature 记录。")
        return

    # 收集所有 properties 作为字段
    prop_keys: set[str] = set()
    rows: list[dict[str, Any]] = []
    coords_all: list[float] = []

    for feat in features:
        props = feat.get("properties", {}) if isinstance(feat.get("properties"), dict) else {}
        prop_keys.update(props.keys())
        row: dict[str, Any] = dict(props)
        # 补充几何坐标字段
        geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
        if geom.get("type") == "Point":
            coord = geom.get("coordinates", [])
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                row["longitude"] = coord[0]
                row["latitude"] = coord[1]
                if len(coord) >= 3:
                    row["elevation"] = coord[2]
                coords_all.extend(float(c) for c in coord[:3] if isinstance(c, (int, float)))
        rows.append(row)

    entry["feature_count"] = len(features)
    entry["field_count"] = len(prop_keys)
    field_names = sorted(prop_keys) + (["longitude", "latitude", "elevation"] if coords_all else [])

    all_field_names = list(dict.fromkeys(field_names))  # 保持顺序去重
    _evaluate_fields(rows, all_field_names, path.name, report, required_fields, None, outlier_sigma)

    # 坐标范围检查
    if coords_all:
        nonfinite = [c for c in coords_all if not math.isfinite(c)]
        if nonfinite:
            _add_issue(
                report, "outliers", file_name=path.name, field_name="coordinates", severity="严重",
                message=f"存在 {len(nonfinite)} 个非有限坐标值。",
            )


# ---- OBJ 文件 ----

def _inspect_obj(
    path: Path,
    report: dict[str, Any],
    entry: dict[str, Any],
    outlier_sigma: float,
) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for line in _read_text(path).splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append(tuple(float(v) for v in parts[1:4]))
        elif parts[0] == "f" and len(parts) >= 4:
            idxs: list[int] = []
            for token in parts[1:]:
                raw = token.split("/")[0]
                if raw:
                    idxs.append(int(raw))
            if len(idxs) >= 3:
                faces.append(idxs)

    entry["vertex_count"] = len(vertices)
    entry["face_count"] = len(faces)

    if not vertices:
        _add_issue(report, "field_validation", file_name=path.name, severity="严重", message="OBJ 文件未读取到顶点数据。")
        return

    # 以顶点坐标作为字段
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    rows = [{"v_x": v[0], "v_y": v[1], "v_z": v[2]} for v in vertices]
    field_names = ["v_x", "v_y", "v_z"]
    _evaluate_fields(rows, field_names, path.name, report, None, None, outlier_sigma)

    # 重复顶点
    unique_verts = set(vertices)
    dup_verts = len(vertices) - len(unique_verts)
    if dup_verts:
        _add_issue(
            report, "duplicates", file_name=path.name, severity="警告" if dup_verts > 10 else "提示",
            message=f"存在 {dup_verts} 个重复顶点。",
            suggestion="可合并重复顶点以减少冗余。",
        )

    # 面索引有效性
    vcount = len(vertices)
    invalid_faces = [f for f in faces if any(idx < 1 or idx > vcount for idx in f)]
    if invalid_faces:
        _add_issue(
            report, "field_validation", file_name=path.name, severity="严重",
            message=f"存在 {len(invalid_faces)} 个面片引用了不存在的顶点索引。",
            suggestion="修正面片索引或删除孤立面片。",
        )

    # 边界边（开放网格检测）
    edge_count: dict[tuple[int, int], int] = {}
    for face in faces:
        for i in range(len(face)):
            a, b = face[i], face[(i + 1) % len(face)]
            edge = (a, b) if a < b else (b, a)
            edge_count[edge] = edge_count.get(edge, 0) + 1
    boundary = sum(1 for c in edge_count.values() if c == 1)
    if boundary:
        _add_issue(
            report, "outliers", file_name=path.name, severity="警告",
            message=f"检测到 {boundary} 条边界边，模型为开放网格。",
            suggestion="确认是否为设计预期；如需封闭模型请补全缺失面片。",
        )


# ---- STL 文件 ----

def _inspect_stl(
    path: Path,
    report: dict[str, Any],
    entry: dict[str, Any],
    outlier_sigma: float,
) -> None:
    text = _read_text(path)
    if "facet" not in text.lower():
        _add_issue(report, "field_validation", file_name=path.name, severity="严重", message="当前仅支持 ASCII STL。")
        return

    vertices: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            vertices.append(tuple(float(v) for v in parts[1:4]))

    entry["vertex_count"] = len(vertices)
    entry["face_count"] = len(vertices) // 3 if vertices else 0

    if not vertices:
        _add_issue(report, "field_validation", file_name=path.name, severity="严重", message="STL 文件未能解析到顶点。")
        return

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    rows = [{"x": v[0], "y": v[1], "z": v[2]} for v in vertices]
    _evaluate_fields(rows, ["x", "y", "z"], path.name, report, None, None, outlier_sigma)

    unique_verts = set(vertices)
    if len(vertices) - len(unique_verts):
        _add_issue(
            report, "duplicates", file_name=path.name, severity="提示",
            message=f"存在 {len(vertices) - len(unique_verts)} 个重复顶点（STL 常见）。",
        )


# ---- PLY/VTK 等网格类 ----

def _inspect_tabular_like_mesh(
    path: Path,
    report: dict[str, Any],
    entry: dict[str, Any],
    required_fields: list[str] | None,
    outlier_sigma: float,
) -> None:
    """对 PLY/VTK 做轻量顶点检查，类似表格式检查。"""
    vertices: list[tuple[float, float, float]] = []
    for line in _read_text(path).splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        # 尝试将行作为三个数值解析
        if len(parts) >= 3:
            try:
                v = tuple(float(parts[i]) for i in range(3))
                vertices.append(v)
            except ValueError:
                continue

    entry["vertex_count"] = len(vertices)
    if not vertices:
        _add_issue(report, "field_validation", file_name=path.name, severity="警告", message="未能从该文件中提取到顶点坐标。")
        return

    rows = [{"x": v[0], "y": v[1], "z": v[2]} for v in vertices]
    _evaluate_fields(rows, ["x", "y", "z"], path.name, report, required_fields, None, outlier_sigma)


# ============================================================================
# 便捷函数：清洗后的数据导出（原地不修改源文件）
# ============================================================================

def clean_tabular_data(
    file_path: str,
    output_path: str | None = None,
    drop_duplicates: bool = True,
    fill_missing: str = "",
    outlier_sigma: float = 3.0,
    duplicate_keys: list[str] | None = None,
    unit_conversions: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    对单个 CSV 文件执行清洗并写出结果。不修改源文件。

    返回 {'output': ..., 'rows_in': ..., 'rows_out': ..., 'removed_duplicates': ..., 'clamped_outliers': ...}
    """
    src = Path(file_path)
    rows = list(csv.DictReader(_read_text(src).splitlines()))
    if not rows:
        return {"output": None, "rows_in": 0, "rows_out": 0, "removed_duplicates": 0, "clamped_outliers": 0, "errors": ["文件无数据。"]}

    field_names = list(rows[0].keys())
    rows_in = len(rows)
    removed_dup = 0
    clamped_out = 0

    # 去重
    if drop_duplicates:
        keys = duplicate_keys or field_names
        seen: set[tuple[str, ...]] = set()
        deduped: list[dict[str, Any]] = []
        for row in rows:
            key = tuple(str(row.get(k, "")) for k in keys)
            if key not in seen:
                seen.add(key)
                deduped.append(row)
            else:
                removed_dup += 1
        rows = deduped

    # 单位转换
    if unit_conversions:
        for row in rows:
            for fname, factor in unit_conversions.items():
                if fname in row:
                    try:
                        row[fname] = float(row[fname]) * factor
                    except (ValueError, TypeError):
                        pass

    # 异常值截断
    if outlier_sigma > 0:
        for fname in field_names:
            numeric: list[tuple[int, float]] = []
            for idx, row in enumerate(rows):
                try:
                    numeric.append((idx, float(row[fname])))
                except (ValueError, TypeError):
                    pass
            if len(numeric) < 5:
                continue
            vals = [v for _, v in numeric]
            mean = sum(vals) / len(vals)
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            if std < 1e-12:
                continue
            lo, hi = mean - outlier_sigma * std, mean + outlier_sigma * std
            for idx, val in numeric:
                if val < lo or val > hi:
                    clamped = max(lo, min(hi, val))
                    rows[idx][fname] = clamped
                    clamped_out += 1

    # 写出
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=field_names)
            writer.writeheader()
            writer.writerows(rows)
    else:
        output_path = None

    return {
        "output": str(Path(output_path).resolve()) if output_path else None,
        "rows_in": rows_in,
        "rows_out": len(rows),
        "removed_duplicates": removed_dup,
        "clamped_outliers": clamped_out,
        "errors": [],
    }


__all__ = [
    "CATEGORY_NAMES",
    "COORD_ALIASES",
    "UNIT_CONVERSIONS",
    "FieldProfile",
    "DataIssue",
    "build_preprocessing_report",
    "clean_tabular_data",
]
