"""Convert digitised section/map traces into positioned 3-D GeoJSON."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .geospatial_common import as_float, distance, finish_report, load_config, parse_number, read_csv, read_json, write_json, write_manifest


MODULE_NAME = "剖面与平面图转换模块"


def _position(chainage: float, elevation: float, config: dict[str, Any], section_id: str = "") -> list[float]:
    definitions = config.get("section_definitions", [])
    definition = next(
        (item for item in definitions if isinstance(item, dict) and str(item.get("section_id", "")) == section_id),
        {},
    ) if isinstance(definitions, list) else {}
    origin = definition.get("origin", config.get("origin", [0.0, 0.0, 0.0]))
    azimuth = math.radians(float(definition.get("azimuth_deg", config.get("azimuth_deg", 90.0))))
    horizontal_scale = float(definition.get("horizontal_scale", config.get("horizontal_scale", 1.0)))
    vertical_scale = float(definition.get("vertical_scale", config.get("vertical_scale", 1.0)))
    offset = chainage * horizontal_scale
    return [
        float(origin[0]) + offset * math.sin(azimuth),
        float(origin[1]) + offset * math.cos(azimuth),
        float(origin[2] if len(origin) > 2 else 0.0) + elevation * vertical_scale,
    ]


def _topology(features: list[dict[str, Any]], tolerance: float) -> tuple[list[dict[str, Any]], dict[str, int]]:
    issues: list[dict[str, Any]] = []
    duplicate_vertices = 0
    open_rings = 0
    short_segments = 0
    for feature in features:
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        coordinates = geometry.get("coordinates") or []
        parts = coordinates if kind in {"LineString", "Polygon"} else []
        if kind == "LineString":
            parts = [coordinates]
        for part in parts:
            for a, b in zip(part, part[1:]):
                if distance(a, b) <= tolerance:
                    duplicate_vertices += 1
            if kind == "Polygon" and part and distance(part[0], part[-1]) > tolerance:
                open_rings += 1
                issues.append({"severity": "严重", "code": "OPEN_RING", "file": str(feature.get("id", "未命名要素")), "message": "多边形环未闭合"})
            if len(part) < (4 if kind == "Polygon" else 2):
                short_segments += 1
                issues.append({"severity": "严重", "code": "INSUFFICIENT_VERTICES", "file": str(feature.get("id", "未命名要素")), "message": "线面顶点数不足"})
    if duplicate_vertices:
        issues.append({"severity": "警告", "code": "NEAR_DUPLICATE_VERTEX", "file": "全部", "message": f"发现 {duplicate_vertices} 组小于容差的相邻顶点"})
    return issues, {"near_duplicate_vertices": duplicate_vertices, "open_rings": open_rings, "invalid_short_parts": short_segments}


def run(
    input_files: list[str], output_dir: str | Path, vector_tolerance: float | str = 0.01,
    topology_rule: str = "严格检查", positioning: str = "控制点/基线定位", layer_mapping: str = "自动",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    tolerance = max(0.0, parse_number(vector_tolerance, 0.01))
    config = load_config(input_files, ("control", "section", "config"))
    features: list[dict[str, Any]] = []
    source_records = 0
    issues: list[dict[str, Any]] = []

    for source in input_files:
        path = Path(source)
        try:
            if path.suffix.lower() == ".csv":
                grouped: dict[tuple[str, str], list[tuple[float, list[float], dict[str, str]]]] = defaultdict(list)
                for row_number, row in enumerate(read_csv(path), start=2):
                    chainage = as_float(row.get("chainage", row.get("distance")), f"第 {row_number} 行 chainage")
                    elevation = as_float(row.get("elevation", row.get("z", 0)), f"第 {row_number} 行 elevation", 0.0)
                    section_id = str(row.get("section_id", "SECTION-1"))
                    feature_id = str(row.get("feature_id", row.get("line_id", "LINE-1")))
                    grouped[(section_id, feature_id)].append((chainage, _position(chainage, elevation, config, section_id), row))
                    source_records += 1
                for (section_id, feature_id), points in grouped.items():
                    points.sort(key=lambda item: item[0])
                    source_row = points[0][2]
                    features.append({
                        "type": "Feature", "id": feature_id,
                        "properties": {"section_id": section_id, "feature_id": feature_id, "geology_type": source_row.get("geology_type", source_row.get("type", "boundary")), "source_file": path.name, "positioning": positioning},
                        "geometry": {"type": "LineString", "coordinates": [item[1] for item in points]},
                    })
            elif path.suffix.lower() in {".geojson", ".json"} and path.name.lower().endswith(".geojson"):
                document = read_json(path)
                if document.get("type") != "FeatureCollection":
                    raise ValueError("GeoJSON 根节点必须是 FeatureCollection")
                for feature in document.get("features", []):
                    item = json.loads(json.dumps(feature))
                    item.setdefault("properties", {})["source_file"] = path.name
                    features.append(item)
                    source_records += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"severity": "严重", "code": "SECTION_INPUT_FAILED", "file": path.name, "message": str(exc)})

    topology_issues, topology_metrics = _topology(features, tolerance)
    issues.extend(topology_issues)
    result = {
        "type": "FeatureCollection",
        "name": "positioned_geological_sections_and_maps",
        "features": features,
        "conversion_metadata": {"positioning": positioning, "layer_mapping": layer_mapping, "vector_tolerance": tolerance, "control": config},
    }
    vector_path = output / "section_map_positioned.geojson"
    topology_path = output / "topology_check.json"
    write_json(vector_path, result)
    write_json(topology_path, {"rule": topology_rule, "passed": not any(item["severity"] == "严重" for item in issues), "metrics": topology_metrics, "issues": issues})
    report = finish_report(MODULE_NAME, input_files, [vector_path, topology_path], {"source_records": source_records, "output_features": len(features), **topology_metrics}, issues, {"vector_tolerance": tolerance, "topology_rule": topology_rule, "positioning": positioning, "layer_mapping": layer_mapping})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
