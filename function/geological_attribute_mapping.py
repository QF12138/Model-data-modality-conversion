"""Traceable nearest/IDW geological attribute mapping to model units."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .geospatial_common import as_float, distance, finish_report, iter_geometry_points, parse_number, read_csv, read_json, write_csv, write_json, write_manifest


MODULE_NAME = "地质属性映射模块"
COORDINATE_FIELDS = {"x", "y", "z", "lon", "lat", "longitude", "latitude", "easting", "northing", "sample_id", "id"}


def _samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for index, row in enumerate(read_csv(path), start=2):
        lower = {key.lower(): value for key, value in row.items()}
        x = as_float(lower.get("x", lower.get("easting", lower.get("lon"))), f"第 {index} 行 X")
        y = as_float(lower.get("y", lower.get("northing", lower.get("lat"))), f"第 {index} 行 Y")
        z = as_float(lower.get("z", 0.0), f"第 {index} 行 Z", 0.0)
        samples.append({"point": (x, y, z), "values": row, "sample_id": row.get("sample_id", row.get("id", f"S{index - 1}")), "source": path.name})
    return samples


def _centroid(feature: dict[str, Any]) -> tuple[float, float, float]:
    points = list({tuple(float(value) for value in point[:3]) for point in iter_geometry_points(feature.get("geometry") or {})})
    if not points:
        raise ValueError("模型单元缺少几何坐标")
    return tuple(sum(float(point[i]) if len(point) > i else 0.0 for point in points) / len(points) for i in range(3))  # type: ignore[return-value]


def _numeric(values: Iterable[Any]) -> bool:
    seen = False
    for value in values:
        if value in (None, ""):
            continue
        seen = True
        try:
            float(value)
        except (TypeError, ValueError):
            return False
    return seen


def _map_value(neighbours: list[tuple[float, dict[str, Any]]], field: str, method: str) -> tuple[Any, list[str], str]:
    valid = [(d, sample) for d, sample in neighbours if sample["values"].get(field) not in (None, "")]
    if not valid:
        return None, [], "unmapped"
    numeric = _numeric(sample["values"].get(field) for _, sample in valid)
    if not numeric or "最近" in method.lower() or "nearest" in method.lower():
        nearest = min(valid, key=lambda item: item[0])
        return nearest[1]["values"][field], [str(nearest[1]["sample_id"])], "nearest"
    zero = next((item for item in valid if item[0] <= 1e-12), None)
    if zero:
        return float(zero[1]["values"][field]), [str(zero[1]["sample_id"])], "exact"
    weights = [(1.0 / (distance_value * distance_value), sample) for distance_value, sample in valid]
    value = sum(weight * float(sample["values"][field]) for weight, sample in weights) / sum(weight for weight, _ in weights)
    return value, [str(sample["sample_id"]) for _, sample in weights], "idw_power_2"


def run(
    input_files: list[str], output_dir: str | Path, mapping_fields: str = "lithology,permeability,density,elastic_modulus,cohesion,friction_angle,water_state",
    interpolation_method: str = "IDW", search_radius: float | str = 100.0,
    trace_identifier: str = "自动生成",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    radius = max(0.0, parse_number(search_radius, 100.0))
    fields = [field.strip() for field in str(mapping_fields).replace("，", ",").split(",") if field.strip()]
    samples: list[dict[str, Any]] = []
    model: dict[str, Any] | None = None
    model_path: Path | None = None
    issues: list[dict[str, Any]] = []
    for source in input_files:
        path = Path(source)
        try:
            if path.suffix.lower() == ".csv":
                samples.extend(_samples(path))
            elif path.suffix.lower() in {".geojson", ".json"} and path.name.lower().endswith(".geojson"):
                model = read_json(path)
                model_path = path
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"severity": "严重", "code": "ATTRIBUTE_INPUT_FAILED", "file": path.name, "message": str(exc)})
    if not fields and samples:
        fields = [key for key in samples[0]["values"] if key.lower() not in COORDINATE_FIELDS]
    if not samples:
        issues.append({"severity": "严重", "code": "NO_ATTRIBUTE_SAMPLES", "file": "全部", "message": "未找到有效属性样本 CSV"})
    if not model or model.get("type") != "FeatureCollection":
        issues.append({"severity": "严重", "code": "NO_MODEL_UNITS", "file": "全部", "message": "未找到有效模型单元 GeoJSON"})
        model = {"type": "FeatureCollection", "features": []}

    lineage_rows: list[dict[str, Any]] = []
    mapped_values = 0
    missing_values = 0
    method_counts: Counter[str] = Counter()
    for index, feature in enumerate(model.get("features", []), start=1):
        try:
            center = _centroid(feature)
        except ValueError as exc:
            issues.append({"severity": "严重", "code": "INVALID_MODEL_GEOMETRY", "file": model_path.name if model_path else "模型", "message": f"单元 {index}: {exc}"})
            continue
        unit_id = str((feature.get("properties") or {}).get("unit_id", feature.get("id", f"U{index}")))
        neighbours = sorted(
            ((distance(center, sample["point"]), sample) for sample in samples),
            key=lambda item: (item[0], str(item[1].get("sample_id", ""))),
        )
        if radius > 0:
            neighbours = [item for item in neighbours if item[0] <= radius]
        properties = feature.setdefault("properties", {})
        properties["unit_id"] = unit_id
        for field in fields:
            value, sample_ids, actual_method = _map_value(neighbours, field, interpolation_method)
            properties[field] = value
            lineage_id = f"{trace_identifier}-{unit_id}-{field}" if trace_identifier not in {"", "自动生成"} else f"MAP-{unit_id}-{field}"
            lineage_rows.append({"lineage_id": lineage_id, "unit_id": unit_id, "field": field, "value": value, "method": actual_method, "sample_ids": ";".join(sample_ids), "sample_count": len(sample_ids), "search_radius": radius})
            method_counts[actual_method] += 1
            if value is None:
                missing_values += 1
            else:
                mapped_values += 1
    if missing_values:
        issues.append({"severity": "警告", "code": "UNMAPPED_ATTRIBUTES", "file": "全部", "message": f"有 {missing_values} 个单元字段未在搜索半径内找到样本"})
    model["attribute_mapping_metadata"] = {"fields": fields, "requested_method": interpolation_method, "search_radius": radius, "source_samples": sorted({sample["source"] for sample in samples})}
    model_output = output / "attributed_model.geojson"
    lineage_output = output / "attribute_mapping_lineage.csv"
    method_output = output / "mapping_method_report.json"
    write_json(model_output, model)
    write_csv(lineage_output, lineage_rows)
    metrics = {"sample_count": len(samples), "model_units": len(model.get("features", [])), "mapped_values": mapped_values, "unmapped_values": missing_values, "coverage_ratio": mapped_values / max(1, mapped_values + missing_values), "method_counts": dict(method_counts)}
    write_json(method_output, {"metrics": metrics, "parameters": {"fields": fields, "method": interpolation_method, "search_radius": radius}, "issues": issues})
    report = finish_report(MODULE_NAME, input_files, [model_output, lineage_output, method_output], metrics, issues, {"mapping_fields": fields, "interpolation_method": interpolation_method, "search_radius": radius, "trace_identifier": trace_identifier})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
