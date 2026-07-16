"""Point-cloud thinning, voxel resampling, classification and PLY export."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .geospatial_common import as_float, bbox, finish_report, load_config, parse_number, read_csv, write_csv, write_json, write_manifest, write_text


MODULE_NAME = "点云数据转换模块"


def _read_ply(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        lines = handle.readlines()
    if not lines or lines[0].strip() != "ply" or not any("format ascii" in line for line in lines[:10]):
        raise ValueError("仅支持 ASCII PLY；LAS/LAZ 应先由采集软件导出为 CSV/ASCII PLY")
    vertex_count = 0
    properties: list[str] = []
    header_end = -1
    in_vertex = False
    for index, line in enumerate(lines):
        parts = line.strip().split()
        if parts[:2] == ["element", "vertex"]:
            vertex_count = int(parts[2])
            in_vertex = True
        elif parts and parts[0] == "element" and parts[1] != "vertex":
            in_vertex = False
        elif in_vertex and parts[:1] == ["property"]:
            properties.append(parts[-1])
        elif parts[:1] == ["end_header"]:
            header_end = index
            break
    if header_end < 0 or not {"x", "y", "z"}.issubset(properties):
        raise ValueError("PLY 头缺少 x/y/z 或 end_header")
    points = []
    for line in lines[header_end + 1:header_end + 1 + vertex_count]:
        values = line.strip().split()
        if len(values) >= len(properties):
            points.append({key: values[i] for i, key in enumerate(properties)})
    return points


def _normalise(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        lower = {str(key).lower(): value for key, value in row.items()}
        point = dict(row)
        point.update({"x": as_float(lower.get("x"), f"{source} 点 {index} X"), "y": as_float(lower.get("y"), f"{source} 点 {index} Y"), "z": as_float(lower.get("z", lower.get("elevation")), f"{source} 点 {index} Z")})
        point["source_file"] = source
        points.append(point)
    return points


def _voxel_downsample(points: list[dict[str, Any]], spacing: float) -> list[dict[str, Any]]:
    if spacing <= 0:
        return list(points)
    buckets: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        key = (math.floor(point["x"] / spacing), math.floor(point["y"] / spacing), math.floor(point["z"] / spacing))
        buckets[key].append(point)
    result: list[dict[str, Any]] = []
    for key in sorted(buckets):
        group = buckets[key]
        representative = dict(group[0])
        for axis in ("x", "y", "z"):
            representative[axis] = sum(float(item[axis]) for item in group) / len(group)
        representative["source_point_count"] = len(group)
        result.append(representative)
    return result


def _classify(points: list[dict[str, Any]], config: dict[str, Any]) -> None:
    if not points:
        return
    rules = config.get("classification_rules", [])
    if isinstance(rules, list) and rules:
        for point in points:
            point["classification"] = "unclassified"
            for rule in rules:
                if float(rule.get("z_min", -math.inf)) <= point["z"] < float(rule.get("z_max", math.inf)):
                    point["classification"] = str(rule.get("class", "unclassified"))
                    break
        return
    if any(str(point.get("classification", "")).strip() for point in points):
        return
    elevations = sorted(point["z"] for point in points)
    q1 = elevations[int((len(elevations) - 1) * 0.33)]
    q2 = elevations[int((len(elevations) - 1) * 0.67)]
    for point in points:
        point["classification"] = "ground" if point["z"] <= q1 else "surface" if point["z"] <= q2 else "high_feature"


def _write_ply(path: Path, points: list[dict[str, Any]]) -> None:
    class_names = sorted({str(point.get("classification", "unclassified")) for point in points})
    class_codes = {name: index for index, name in enumerate(class_names)}
    lines = ["ply", "format ascii 1.0", f"element vertex {len(points)}", "property double x", "property double y", "property double z", "property uchar classification", "end_header"]
    lines.extend(f"{point['x']:.9g} {point['y']:.9g} {point['z']:.9g} {class_codes[str(point.get('classification', 'unclassified'))]}" for point in points)
    write_text(path, "\n".join(lines) + "\n")


def run(
    input_files: list[str], output_dir: str | Path, thinning_ratio: float | str = "100%",
    resampling_spacing: float | str = 1.0, classification_rule: str = "高程分位分类",
    output_format: str = "PLY",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(input_files, ("point", "classification", "config"))
    spacing = max(0.0, parse_number(resampling_spacing, 1.0))
    ratio = parse_number(thinning_ratio, 100.0)
    ratio = ratio / 100 if "%" in str(thinning_ratio) or ratio > 1 else ratio
    ratio = min(1.0, max(0.001, ratio))
    points: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for source in input_files:
        path = Path(source)
        try:
            if path.suffix.lower() == ".csv":
                points.extend(_normalise(read_csv(path), path.name))
            elif path.suffix.lower() == ".ply":
                points.extend(_normalise(_read_ply(path), path.name))
        except (OSError, ValueError) as exc:
            issues.append({"severity": "严重", "code": "POINT_CLOUD_INPUT_FAILED", "file": path.name, "message": str(exc)})
    source_count = len(points)
    sampled = _voxel_downsample(points, spacing)
    target_count = max(1, round(len(sampled) * ratio)) if sampled else 0
    if target_count < len(sampled):
        step = len(sampled) / target_count
        sampled = [sampled[min(len(sampled) - 1, int(index * step))] for index in range(target_count)]
    _classify(sampled, config)
    class_stats = dict(Counter(str(point.get("classification", "unclassified")) for point in sampled))
    csv_path = output / "standardized_point_cloud.csv"
    ply_path = output / "classified_point_cloud.ply"
    stats_path = output / "point_cloud_statistics.json"
    fields = ["x", "y", "z", "classification", "source_file", "source_point_count"]
    write_csv(csv_path, sampled, fields)
    _write_ply(ply_path, sampled)
    metrics = {"input_points": source_count, "output_points": len(sampled), "retention_ratio": len(sampled) / source_count if source_count else 0.0, "voxel_spacing": spacing, "classes": class_stats, "bounds": bbox((point["x"], point["y"], point["z"]) for point in sampled)}
    write_json(stats_path, metrics)
    if source_count and len(sampled) / source_count < 0.05:
        issues.append({"severity": "警告", "code": "AGGRESSIVE_THINNING", "file": "全部", "message": "输出点数低于输入点数的 5%，请复核抽稀与重采样参数"})
    outputs = [csv_path, ply_path, stats_path]
    report = finish_report(MODULE_NAME, input_files, outputs, metrics, issues, {"thinning_ratio": ratio, "resampling_spacing": spacing, "classification_rule": classification_rule, "output_format": output_format})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
