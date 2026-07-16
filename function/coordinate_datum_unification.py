"""Coordinate, vertical datum, unit and engineering-chainage unification."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .geospatial_common import (
    as_float, bbox, finish_report, load_config, map_geometry, parse_number,
    read_csv, read_json, write_csv, write_json, write_manifest, write_obj, read_obj,
)


MODULE_NAME = "坐标与基准统一模块"
EARTH_RADIUS = 6378137.0


def _normalize_crs(value: Any) -> str:
    text = str(value or "LOCAL").upper().replace(" ", "")
    aliases = {
        "WGS84": "EPSG:4326", "4326": "EPSG:4326",
        "CGCS2000": "EPSG:4490", "4490": "EPSG:4490",
        "WEBMERCATOR": "EPSG:3857", "3857": "EPSG:3857",
    }
    return aliases.get(text, text)


def _horizontal_transform(source: str, target: str, config: dict[str, Any]):
    source, target = _normalize_crs(source), _normalize_crs(target)
    geographic = {"EPSG:4326", "EPSG:4490"}
    if source == target or source in geographic and target in geographic:
        return lambda x, y: (x, y), "identity"
    if source in geographic and target == "EPSG:3857":
        def forward(lon: float, lat: float) -> tuple[float, float]:
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError(f"经纬度超出有效范围：{lon}, {lat}")
            limited = max(-85.05112878, min(85.05112878, lat))
            return EARTH_RADIUS * math.radians(lon), EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(limited) / 2))
        return forward, "geographic_to_web_mercator"
    if source == "EPSG:3857" and target in geographic:
        return (
            lambda x, y: (math.degrees(x / EARTH_RADIUS), math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)),
            "web_mercator_to_geographic",
        )
    affine = config.get("affine") if isinstance(config.get("affine"), dict) else config
    required = {"scale_x", "scale_y", "offset_x", "offset_y"}
    if required.issubset(affine):
        sx, sy = float(affine["scale_x"]), float(affine["scale_y"])
        ox, oy = float(affine["offset_x"]), float(affine["offset_y"])
        rotation = math.radians(float(affine.get("rotation_deg", 0.0)))
        return (
            lambda x, y: (
                ox + sx * x * math.cos(rotation) - sy * y * math.sin(rotation),
                oy + sx * x * math.sin(rotation) + sy * y * math.cos(rotation),
            ),
            "configured_affine",
        )
    raise ValueError(f"暂不支持 {source} → {target}；请在配置文件中提供 affine 参数")


def _unit_factor(unit: str) -> float:
    text = str(unit or "m").lower().strip()
    return {"m": 1.0, "米": 1.0, "mm": 0.001, "毫米": 0.001, "cm": 0.01, "厘米": 0.01, "km": 1000.0, "千米": 1000.0}.get(text, 1.0)


def run(
    input_files: list[str], output_dir: str | Path,
    target_crs: str = "EPSG:3857", target_vertical_datum: str = "1985 国家高程基准",
    unit: str = "m", tolerance: float | str = 0.01,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(input_files, ("config", "datum", "coordinate"))
    target_crs = _normalize_crs(config.get("target_crs", target_crs))
    vertical_offset = float(config.get("vertical_offset", 0.0))
    target_unit = str(config.get("target_unit", unit)).split("/")[0].strip() or "m"
    precision = max(0.0, parse_number(tolerance, 0.01))
    outputs: list[Path] = []
    issues: list[dict[str, Any]] = []
    total_points = 0
    residual_max = 0.0
    transformations: list[dict[str, Any]] = []

    for source_name in input_files:
        source_path = Path(source_name)
        suffix = source_path.suffix.lower()
        if suffix == ".json" and not source_path.name.lower().endswith(".geojson"):
            continue
        source_crs = _normalize_crs(config.get("source_crs", "LOCAL"))
        source_unit = str(config.get("source_unit", target_unit))
        factor = _unit_factor(source_unit) / _unit_factor(target_unit)
        try:
            horizontal, method = _horizontal_transform(source_crs, target_crs, config)
        except ValueError as exc:
            issues.append({"severity": "严重", "file": source_path.name, "code": "UNSUPPORTED_CRS", "message": str(exc)})
            continue

        def convert(x: float, y: float, z: float) -> tuple[float, float, float]:
            nonlocal residual_max
            tx, ty = horizontal(x * factor, y * factor)
            tz = z * factor + vertical_offset
            rounded = tuple(round(value, 9) for value in (tx, ty, tz))
            residual_max = max(residual_max, *(abs(a - b) for a, b in zip((tx, ty, tz), rounded)))
            return rounded

        try:
            if suffix == ".csv":
                rows = read_csv(source_path)
                converted_rows: list[dict[str, Any]] = []
                for index, row in enumerate(rows, start=2):
                    x_key = next((key for key in row if key.lower() in {"x", "lon", "longitude", "easting"}), None)
                    y_key = next((key for key in row if key.lower() in {"y", "lat", "latitude", "northing"}), None)
                    z_key = next((key for key in row if key.lower() in {"z", "elevation", "height", "高程"}), None)
                    if not x_key or not y_key:
                        raise ValueError(f"第 {index} 行缺少 X/Y 坐标字段")
                    if row.get("source_crs"):
                        row_source = _normalize_crs(row["source_crs"])
                        row_horizontal, _ = _horizontal_transform(row_source, target_crs, config)
                        x, y = row_horizontal(as_float(row[x_key], x_key) * factor, as_float(row[y_key], y_key) * factor)
                        z = as_float(row.get(z_key, 0.0), z_key or "Z", 0.0) * factor + vertical_offset
                        converted = (round(x, 9), round(y, 9), round(z, 9))
                    else:
                        converted = convert(as_float(row[x_key], x_key), as_float(row[y_key], y_key), as_float(row.get(z_key, 0.0), z_key or "Z", 0.0))
                    item = dict(row)
                    item.update({"x": converted[0], "y": converted[1], "z": converted[2], "source_crs": source_crs, "target_crs": target_crs, "vertical_datum": target_vertical_datum, "unit": target_unit})
                    converted_rows.append(item)
                target = output / f"{source_path.stem}_unified.csv"
                write_csv(target, converted_rows)
                total_points += len(converted_rows)
            elif suffix in {".geojson", ".json"}:
                document = read_json(source_path)
                if document.get("type") != "FeatureCollection":
                    raise ValueError("空间 JSON 必须是 GeoJSON FeatureCollection")
                count = 0
                for feature in document.get("features", []):
                    feature["geometry"] = map_geometry(feature.get("geometry") or {}, convert)
                    count += sum(1 for _ in feature["geometry"].get("coordinates", [])) if feature["geometry"].get("type") == "MultiPoint" else 1
                document["crs"] = {"type": "name", "properties": {"name": target_crs}}
                document["conversion_metadata"] = {"source_crs": source_crs, "target_crs": target_crs, "vertical_datum": target_vertical_datum, "unit": target_unit}
                target = output / f"{source_path.stem}_unified.geojson"
                write_json(target, document)
                total_points += count
            elif suffix == ".obj":
                vertices, faces = read_obj(source_path)
                converted_vertices = [convert(*point) for point in vertices]
                target = output / f"{source_path.stem}_unified.obj"
                write_obj(target, converted_vertices, faces, f"{source_crs} -> {target_crs}; vertical_offset={vertical_offset}")
                total_points += len(converted_vertices)
            else:
                continue
            outputs.append(target)
            transformations.append({"source": source_path.name, "output": target.name, "method": method, "source_crs": source_crs, "target_crs": target_crs, "vertical_offset": vertical_offset, "unit_factor": factor})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"severity": "严重", "file": source_path.name, "code": "COORDINATE_CONVERSION_FAILED", "message": str(exc)})

    if residual_max > precision:
        issues.append({"severity": "警告", "file": "全部", "code": "PRECISION_EXCEEDED", "message": f"最大数值舍入残差 {residual_max:.3g} 超过容差 {precision:.3g}"})
    parameter_path = output / "coordinate_transform_parameters.json"
    write_json(parameter_path, {"target_crs": target_crs, "target_vertical_datum": target_vertical_datum, "target_unit": target_unit, "tolerance": precision, "transformations": transformations})
    outputs.append(parameter_path)
    report = finish_report(MODULE_NAME, input_files, outputs, {"converted_points": total_points, "converted_files": len(transformations), "max_numeric_residual": residual_max, "target_crs": target_crs}, issues, {"target_crs": target_crs, "vertical_datum": target_vertical_datum, "unit": target_unit, "tolerance": precision})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
