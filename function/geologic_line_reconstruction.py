"""Reconstruct fragmented geological interpretation lines with traceable QA."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from .geospatial_common import distance, finish_report, parse_number, read_json, write_json, write_manifest


MODULE_NAME = "地质解释线重建模块"


def _chaikin(points: list[list[float]], iterations: int) -> list[list[float]]:
    result = [list(point) for point in points]
    for _ in range(max(0, iterations)):
        if len(result) < 3:
            break
        refined = [result[0]]
        for first, second in zip(result, result[1:]):
            dimensions = min(len(first), len(second))
            refined.append([0.75 * first[i] + 0.25 * second[i] for i in range(dimensions)])
            refined.append([0.25 * first[i] + 0.75 * second[i] for i in range(dimensions)])
        refined.append(result[-1])
        result = refined
    return result


def _join(lines: list[list[list[float]]], tolerance: float) -> tuple[list[list[list[float]]], int]:
    remaining = [[list(point) for point in line] for line in lines if len(line) >= 2]
    rebuilt: list[list[list[float]]] = []
    joins = 0
    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            best: tuple[float, int, str] | None = None
            for index, candidate in enumerate(remaining):
                options = (
                    (distance(current[-1], candidate[0]), "append"),
                    (distance(current[-1], candidate[-1]), "append_reverse"),
                    (distance(current[0], candidate[-1]), "prepend"),
                    (distance(current[0], candidate[0]), "prepend_reverse"),
                )
                value, mode = min(options, key=lambda item: item[0])
                if value <= tolerance and (best is None or value < best[0]):
                    best = (value, index, mode)
            if best:
                _, index, mode = best
                candidate = remaining.pop(index)
                if mode == "append":
                    current.extend(candidate[1:])
                elif mode == "append_reverse":
                    current.extend(list(reversed(candidate[:-1])))
                elif mode == "prepend":
                    current = candidate[:-1] + current
                else:
                    current = list(reversed(candidate[1:])) + current
                joins += 1
                changed = True
        rebuilt.append(current)
    return rebuilt, joins


def _line_length(points: Sequence[Sequence[float]]) -> float:
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def run(
    input_files: list[str], output_dir: str | Path, algorithm: str = "端点匹配+平滑",
    smoothing: int | str = 1, connection_tolerance: float | str = 1.0,
    boundary_constraint: str = "保持地质类型与接触关系",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    tolerance = max(0.0, parse_number(connection_tolerance, 1.0))
    iterations = max(0, min(5, int(parse_number(smoothing, 1))))
    grouped: dict[tuple[str, str], list[list[list[float]]]] = defaultdict(list)
    group_properties: dict[tuple[str, str], dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    source_segments = 0

    for source in input_files:
        path = Path(source)
        if path.suffix.lower() not in {".geojson", ".json"} or not path.name.lower().endswith(".geojson"):
            continue
        try:
            document = read_json(path)
            for index, feature in enumerate(document.get("features", []), start=1):
                geometry = feature.get("geometry") or {}
                kind = geometry.get("type")
                properties = dict(feature.get("properties") or {})
                key = (str(properties.get("boundary_id", properties.get("name", f"B-{index}"))), str(properties.get("geology_type", properties.get("type", "boundary"))))
                parts = [geometry.get("coordinates", [])] if kind == "LineString" else geometry.get("coordinates", []) if kind == "MultiLineString" else []
                for part in parts:
                    if len(part) >= 2:
                        grouped[key].append(part)
                        source_segments += 1
                    else:
                        issues.append({"severity": "严重", "code": "INVALID_LINE", "file": path.name, "message": f"要素 {index} 的线顶点不足"})
                group_properties.setdefault(key, properties)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"severity": "严重", "code": "LINE_INPUT_FAILED", "file": path.name, "message": str(exc)})

    features: list[dict[str, Any]] = []
    anomaly_features: list[dict[str, Any]] = []
    joins_total = 0
    before_length = 0.0
    after_length = 0.0
    for key, lines in grouped.items():
        before_length += sum(_line_length(line) for line in lines)
        rebuilt, joins = _join(lines, tolerance)
        joins_total += joins
        for part_index, line in enumerate(rebuilt, start=1):
            smoothed = _chaikin(line, iterations)
            after_length += _line_length(smoothed)
            properties = dict(group_properties[key])
            properties.update({"boundary_id": key[0], "geology_type": key[1], "part": part_index, "source_segments": len(lines), "join_count": joins, "smoothing_iterations": iterations})
            features.append({"type": "Feature", "properties": properties, "geometry": {"type": "LineString", "coordinates": smoothed}})
            for endpoint_name, point in (("start", smoothed[0]), ("end", smoothed[-1])):
                other_distance = min((distance(point, candidate) for other in rebuilt if other is not line for candidate in (other[0], other[-1])), default=float("inf"))
                if len(rebuilt) > 1 and other_distance > tolerance:
                    anomaly_features.append({"type": "Feature", "properties": {"boundary_id": key[0], "endpoint": endpoint_name, "nearest_distance": other_distance, "reason": "超过连接容差"}, "geometry": {"type": "Point", "coordinates": point}})

    if anomaly_features:
        issues.append({"severity": "警告", "code": "UNCONNECTED_ENDPOINTS", "file": "全部", "message": f"仍有 {len(anomaly_features)} 个异常断点需人工复核"})
    boundary_path = output / "reconstructed_boundaries.geojson"
    anomaly_path = output / "breakpoint_anomalies.geojson"
    quality_path = output / "reconstruction_quality.json"
    write_json(boundary_path, {"type": "FeatureCollection", "features": features})
    write_json(anomaly_path, {"type": "FeatureCollection", "features": anomaly_features})
    length_change = abs(after_length - before_length) / before_length if before_length else 0.0
    quality = {"source_segments": source_segments, "reconstructed_parts": len(features), "joined_gaps": joins_total, "anomaly_endpoints": len(anomaly_features), "length_change_ratio": length_change, "continuity_rate": joins_total / max(1, source_segments - len(features))}
    write_json(quality_path, quality)
    report = finish_report(MODULE_NAME, input_files, [boundary_path, anomaly_path, quality_path], quality, issues, {"algorithm": algorithm, "smoothing_iterations": iterations, "connection_tolerance": tolerance, "boundary_constraint": boundary_constraint})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
