"""Crop, decimate and refine OBJ meshes between geological model scales."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from .geospatial_common import bbox, distance, finish_report, load_config, parse_number, read_obj, remap_mesh, write_json, write_manifest, write_obj


MODULE_NAME = "多尺度模型转换模块"


def _inside(point: Sequence[float], bounds: Sequence[float]) -> bool:
    return all(float(bounds[i]) <= float(point[i]) <= float(bounds[i + 3]) for i in range(3))


def _crop(vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]], bounds: Sequence[float]) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    keep = []
    for index, face in enumerate(faces):
        center = tuple(sum(vertices[vertex][axis] for vertex in face) / len(face) for axis in range(3))
        if _inside(center, bounds):
            keep.append(index)
    return remap_mesh(vertices, faces, keep) if keep else ([], [])


def _cluster(vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]], size: float) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    if size <= 0:
        return vertices, faces
    groups: dict[tuple[int, int, int], list[int]] = {}
    for index, vertex in enumerate(vertices):
        key = tuple(math.floor(value / size) for value in vertex)
        groups.setdefault(key, []).append(index)
    new_vertices: list[tuple[float, float, float]] = []
    mapping: dict[int, int] = {}
    for key in sorted(groups):
        members = groups[key]
        new_index = len(new_vertices)
        new_vertices.append(tuple(sum(vertices[index][axis] for index in members) / len(members) for axis in range(3)))
        mapping.update({index: new_index for index in members})
    new_faces: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for face in faces:
        remapped = tuple(mapping[index] for index in face)
        cleaned = tuple(dict.fromkeys(remapped))
        canonical = tuple(sorted(cleaned))
        if len(cleaned) >= 3 and canonical not in seen:
            new_faces.append(cleaned)
            seen.add(canonical)
    return new_vertices, new_faces


def _triangles(faces: list[tuple[int, ...]]) -> list[tuple[int, int, int]]:
    result = []
    for face in faces:
        for index in range(1, len(face) - 1):
            result.append((face[0], face[index], face[index + 1]))
    return result


def _refine(vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]]) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    result_vertices = list(vertices)
    cache: dict[tuple[int, int], int] = {}
    def midpoint(a: int, b: int) -> int:
        key = tuple(sorted((a, b)))
        if key not in cache:
            cache[key] = len(result_vertices)
            result_vertices.append(tuple((vertices[a][axis] + vertices[b][axis]) / 2 for axis in range(3)))
        return cache[key]
    result_faces: list[tuple[int, int, int]] = []
    for a, b, c in _triangles(faces):
        ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
        result_faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
    return result_vertices, result_faces


def _nearest_error(source: list[tuple[float, float, float]], target: list[tuple[float, float, float]]) -> tuple[float, float]:
    if not source or not target:
        return 0.0, 0.0
    errors = [min(distance(point, candidate) for candidate in target) for point in source]
    return max(errors), sum(errors) / len(errors)


def run(
    input_files: list[str], output_dir: str | Path, target_scale: str = "工程尺度",
    decimation_strategy: str = "顶点聚类 2.0", refinement_rule: str = "按目标尺度自动",
    precision_strategy: str = "边界优先",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(input_files, ("scale", "crop", "config"))
    outputs: list[Path] = []
    issues: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for source in input_files:
        path = Path(source)
        if path.suffix.lower() != ".obj":
            continue
        try:
            vertices, faces = read_obj(path)
            original_vertices, original_faces = list(vertices), list(faces)
            crop_bounds = config.get("crop_bbox")
            if isinstance(crop_bounds, list) and len(crop_bounds) == 6:
                vertices, faces = _crop(vertices, faces, [float(value) for value in crop_bounds])
                if not faces:
                    raise ValueError("裁剪范围未包含任何面")
            model_bounds = bbox(vertices)
            diagonal = math.sqrt(sum((model_bounds[i + 3] - model_bounds[i]) ** 2 for i in range(3)))
            default_cluster = diagonal / (30 if "区域" in target_scale else 60 if "工程" in target_scale else 0 or 1)
            cluster_size = float(config.get("cluster_size", parse_number(decimation_strategy, default_cluster)))
            if "局部" not in target_scale and cluster_size > 0:
                vertices, faces = _cluster(vertices, faces, cluster_size)
            refine_iterations = int(config.get("refine_iterations", 1 if "局部" in target_scale else 0))
            if "不加密" in refinement_rule or "关闭" in refinement_rule:
                refine_iterations = 0
            for _ in range(max(0, min(refine_iterations, 2))):
                vertices, faces = _refine(vertices, faces)
            if not faces:
                raise ValueError("尺度转换后没有有效网格面；请减小聚类尺寸")
            target = output / f"{path.stem}_{'regional' if '区域' in target_scale else 'local' if '局部' in target_scale else 'engineering'}.obj"
            write_obj(target, vertices, faces, f"target_scale={target_scale}; precision={precision_strategy}")
            outputs.append(target)
            max_error, mean_error = _nearest_error(original_vertices, vertices)
            models.append({"source": path.name, "output": target.name, "source_vertices": len(original_vertices), "source_faces": len(original_faces), "output_vertices": len(vertices), "output_faces": len(faces), "vertex_ratio": len(vertices) / len(original_vertices), "face_ratio": len(faces) / max(1, len(original_faces)), "max_vertex_error": max_error, "mean_vertex_error": mean_error, "bounds": bbox(vertices)})
        except (OSError, ValueError) as exc:
            issues.append({"severity": "严重", "code": "MULTISCALE_CONVERSION_FAILED", "file": path.name, "message": str(exc)})
    if not models:
        issues.append({"severity": "严重", "code": "NO_MESH_MODEL", "file": "全部", "message": "未找到可转换的 OBJ 网格模型"})
    record_path = output / "scale_conversion_record.json"
    accuracy_path = output / "scale_accuracy_report.json"
    metrics = {"model_count": len(models), "models": models, "total_source_faces": sum(item["source_faces"] for item in models), "total_output_faces": sum(item["output_faces"] for item in models), "max_error": max((item["max_vertex_error"] for item in models), default=0.0)}
    write_json(record_path, {"target_scale": target_scale, "decimation_strategy": decimation_strategy, "refinement_rule": refinement_rule, "precision_strategy": precision_strategy, "models": models})
    write_json(accuracy_path, {"metrics": metrics, "issues": issues})
    outputs.extend((record_path, accuracy_path))
    report = finish_report(MODULE_NAME, input_files, outputs, metrics, issues, {"target_scale": target_scale, "decimation_strategy": decimation_strategy, "refinement_rule": refinement_rule, "precision_strategy": precision_strategy})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
