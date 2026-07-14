"""ASCII raster/GeoJSON conversion with explicit resolution and accuracy QA."""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from pathlib import Path
from typing import Any

from .geospatial_common import bbox, finish_report, parse_number, point_in_polygon, read_json, write_json, write_manifest, write_text


MODULE_NAME = "栅格与矢量转换模块"


def _read_ascii(path: Path) -> tuple[dict[str, float], list[list[float]]]:
    headers: dict[str, float] = {}
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            parts = raw.strip().split()
            if not parts:
                continue
            if len(headers) < 6 and parts[0].lower() in {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}:
                headers[parts[0].lower()] = float(parts[1])
            else:
                rows.append([float(value) for value in parts])
    ncols, nrows = int(headers.get("ncols", 0)), int(headers.get("nrows", 0))
    if ncols <= 0 or nrows <= 0 or len(rows) != nrows or any(len(row) != ncols for row in rows):
        raise ValueError("ASCII Grid 的 ncols/nrows 与数据矩阵不一致")
    if "cellsize" not in headers:
        raise ValueError("ASCII Grid 缺少 cellsize")
    return headers, rows


def _cell_ring(headers: dict[str, float], row: int, col: int) -> list[list[float]]:
    size = headers["cellsize"]
    x0 = headers.get("xllcorner", headers.get("xllcenter", 0.0) - size / 2) + col * size
    y0 = headers.get("yllcorner", headers.get("yllcenter", 0.0) - size / 2) + (int(headers["nrows"]) - row - 1) * size
    return [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]


def _raster_to_vector(path: Path, threshold: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    headers, rows = _read_ascii(path)
    nodata = headers.get("nodata_value", -9999.0)
    visited: set[tuple[int, int]] = set()
    features: list[dict[str, Any]] = []
    active_cells = 0
    for row in range(len(rows)):
        for col in range(len(rows[row])):
            value = rows[row][col]
            if (row, col) in visited or value == nodata or value < threshold:
                continue
            queue = deque([(row, col)])
            visited.add((row, col))
            component: list[tuple[int, int]] = []
            while queue:
                current = queue.popleft()
                component.append(current)
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    rr, cc = current[0] + dr, current[1] + dc
                    if 0 <= rr < len(rows) and 0 <= cc < len(rows[rr]) and (rr, cc) not in visited:
                        candidate = rows[rr][cc]
                        if candidate != nodata and candidate >= threshold:
                            visited.add((rr, cc))
                            queue.append((rr, cc))
            active_cells += len(component)
            polygons = [[_cell_ring(headers, rr, cc)] for rr, cc in component]
            values = [rows[rr][cc] for rr, cc in component]
            features.append({"type": "Feature", "properties": {"component_id": len(features) + 1, "cell_count": len(component), "value_min": min(values), "value_max": max(values), "value_mean": sum(values) / len(values), "source": path.name}, "geometry": {"type": "MultiPolygon", "coordinates": polygons}})
    metrics = {"raster_rows": len(rows), "raster_columns": len(rows[0]), "active_cells": active_cells, "vector_components": len(features), "cellsize": headers["cellsize"]}
    return features, metrics


def _feature_polygons(feature: dict[str, Any]) -> list[list[list[float]]]:
    geometry = feature.get("geometry") or {}
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiPolygon":
        return geometry.get("coordinates", [])
    return []


def _vector_to_ascii(path: Path, resolution: float, output: Path, field: str) -> dict[str, Any]:
    document = read_json(path)
    features = document.get("features", [])
    polygons = [(feature, polygon) for feature in features for polygon in _feature_polygons(feature) if polygon]
    points = [point for _, polygon in polygons for ring in polygon for point in ring]
    if not points:
        raise ValueError("GeoJSON 中没有 Polygon/MultiPolygon")
    bounds = bbox(points)
    ncols = max(1, math.ceil((bounds[3] - bounds[0]) / resolution))
    nrows = max(1, math.ceil((bounds[4] - bounds[1]) / resolution))
    if ncols * nrows > 2_000_000:
        raise ValueError("目标分辨率将产生超过 200 万像元，请增大分辨率")
    nodata = -9999.0
    grid = [[nodata for _ in range(ncols)] for _ in range(nrows)]
    populated = 0
    for row in range(nrows):
        y = bounds[1] + (nrows - row - 0.5) * resolution
        for col in range(ncols):
            x = bounds[0] + (col + 0.5) * resolution
            for feature, polygon in polygons:
                if point_in_polygon(x, y, polygon[0]) and not any(point_in_polygon(x, y, hole) for hole in polygon[1:]):
                    raw = (feature.get("properties") or {}).get(field, (feature.get("properties") or {}).get("value", 1))
                    try:
                        grid[row][col] = float(raw)
                    except (TypeError, ValueError):
                        stable_code = int(hashlib.sha1(str(raw).encode("utf-8")).hexdigest()[:8], 16) % 10000 + 1
                        grid[row][col] = float(stable_code)
                    populated += 1
                    break
    lines = [f"ncols {ncols}", f"nrows {nrows}", f"xllcorner {bounds[0]:.9g}", f"yllcorner {bounds[1]:.9g}", f"cellsize {resolution:.9g}", f"NODATA_value {nodata:.9g}"]
    lines.extend(" ".join(f"{value:.9g}" for value in row) for row in grid)
    write_text(output, "\n".join(lines) + "\n")
    return {"vector_features": len(features), "raster_rows": nrows, "raster_columns": ncols, "populated_cells": populated, "resolution": resolution, "coverage_ratio": populated / (nrows * ncols)}


def run(
    input_files: list[str], output_dir: str | Path, direction: str = "自动双向",
    resolution: float | str = 10.0, boundary_threshold: float | str = 1.0,
    attribute_mapping: str = "value",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cell_size = max(1e-9, parse_number(resolution, 10.0))
    threshold = parse_number(boundary_threshold, 1.0)
    field = str(attribute_mapping or "value").split(",")[0].strip() or "value"
    outputs: list[Path] = []
    issues: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"raster_to_vector_files": 0, "vector_to_raster_files": 0}
    lower_direction = direction.lower()
    for source in input_files:
        path = Path(source)
        try:
            if path.suffix.lower() in {".asc", ".grd"} and not ("矢量转栅格" in direction or "vector_to_raster" in lower_direction):
                features, item_metrics = _raster_to_vector(path, threshold)
                target = output / f"{path.stem}_vectorized.geojson"
                write_json(target, {"type": "FeatureCollection", "features": features, "conversion_metadata": {"threshold": threshold, "source_raster": path.name}})
                outputs.append(target)
                metrics["raster_to_vector_files"] += 1
                metrics[path.name] = item_metrics
            elif path.suffix.lower() in {".geojson", ".json"} and path.name.lower().endswith(".geojson") and not ("栅格转矢量" in direction or "raster_to_vector" in lower_direction):
                target = output / f"{path.stem}_rasterized.asc"
                item_metrics = _vector_to_ascii(path, cell_size, target, field)
                outputs.append(target)
                metrics["vector_to_raster_files"] += 1
                metrics[path.name] = item_metrics
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"severity": "严重", "code": "RASTER_VECTOR_FAILED", "file": path.name, "message": str(exc)})
    accuracy_path = output / "spatial_accuracy_report.json"
    write_json(accuracy_path, {"resolution": cell_size, "boundary_threshold": threshold, "attribute_field": field, "metrics": metrics, "issues": issues})
    outputs.append(accuracy_path)
    report = finish_report(MODULE_NAME, input_files, outputs, metrics, issues, {"direction": direction, "resolution": cell_size, "boundary_threshold": threshold, "attribute_mapping": field})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
