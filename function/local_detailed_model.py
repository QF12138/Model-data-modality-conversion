"""ROI-driven local mesh refinement for faults, tunnels, slopes and cavities."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from .geospatial_common import bbox, distance, finish_report, load_config, parse_number, read_json, read_obj, write_json, write_manifest, write_obj


MODULE_NAME = "局部精细模型构建模块"


def _triangles(faces: Sequence[Sequence[int]]) -> list[tuple[int, int, int]]:
    result: list[tuple[int, int, int]] = []
    for face in faces:
        for index in range(1, len(face) - 1):
            result.append((int(face[0]), int(face[index]), int(face[index + 1])))
    return result


def _inside(point: Sequence[float], bounds: Sequence[float]) -> bool:
    return all(float(bounds[index]) <= float(point[index]) <= float(bounds[index + 3]) for index in range(3))


def _expand_ring(faces: list[tuple[int, int, int]], selected: set[int], rings: int) -> set[int]:
    vertex_faces: dict[int, set[int]] = defaultdict(set)
    for index, face in enumerate(faces):
        for vertex in face:
            vertex_faces[vertex].add(index)
    result = set(selected)
    frontier = set(selected)
    for _ in range(max(0, rings)):
        neighbours = {other for index in frontier for vertex in faces[index] for other in vertex_faces[vertex]}
        frontier = neighbours - result
        result.update(frontier)
    return result


def _refine_selected(
    vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]], selected: set[int],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], set[int]]:
    result_vertices = list(vertices)
    result_faces: list[tuple[int, int, int]] = []
    child_selected: set[int] = set()
    midpoint_cache: dict[tuple[int, int], int] = {}

    def midpoint(a: int, b: int) -> int:
        key = tuple(sorted((a, b)))
        if key not in midpoint_cache:
            midpoint_cache[key] = len(result_vertices)
            result_vertices.append(tuple((vertices[a][axis] + vertices[b][axis]) / 2 for axis in range(3)))
        return midpoint_cache[key]

    for index, (a, b, c) in enumerate(faces):
        if index not in selected:
            result_faces.append((a, b, c))
            continue
        ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
        children = ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))
        start = len(result_faces)
        result_faces.extend(children)
        child_selected.update(range(start, start + 4))
    return result_vertices, result_faces, child_selected


def _edge_quality(vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> dict[str, Any]:
    edges: Counter[tuple[int, int]] = Counter()
    lengths: list[float] = []
    degenerate = 0
    for face in faces:
        a, b, c = (vertices[index] for index in face)
        cross = (
            (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
            (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
            (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]),
        )
        if sum(value * value for value in cross) <= 1e-20:
            degenerate += 1
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge = tuple(sorted((first, second)))
            edges[edge] += 1
            lengths.append(distance(vertices[first], vertices[second]))
    return {"degenerate_faces": degenerate, "boundary_edges": sum(1 for count in edges.values() if count == 1), "non_manifold_edges": sum(1 for count in edges.values() if count > 2), "min_edge_length": min(lengths, default=0.0), "max_edge_length": max(lengths, default=0.0), "mean_edge_length": sum(lengths) / len(lengths) if lengths else 0.0}


def run(
    input_files: list[str], output_dir: str | Path, refinement_level: int | str = 1,
    local_boundary: str = "ROI 配置文件", refinement_method: str = "三角形中点细分",
    transition_strategy: str = "1 环过渡",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(input_files, ("roi", "local", "detail", "config"))
    levels = max(1, min(3, int(parse_number(refinement_level, 1))))
    rings = max(0, min(3, int(config.get("transition_rings", parse_number(transition_strategy, 1)))))
    roi = config.get("roi_bbox")
    outputs: list[Path] = []
    issues: list[dict[str, Any]] = []
    model_metrics: list[dict[str, Any]] = []
    constraint_features = 0
    constraint_types: Counter[str] = Counter()
    for source in input_files:
        path = Path(source)
        if path.suffix.lower() in {".geojson", ".json"} and path.name.lower().endswith(".geojson"):
            try:
                document = read_json(path)
                for feature in document.get("features", []):
                    constraint_features += 1
                    constraint_types[str((feature.get("properties") or {}).get("constraint", "untyped"))] += 1
            except (OSError, ValueError) as exc:
                issues.append({"severity": "警告", "code": "CONSTRAINT_INPUT_FAILED", "file": path.name, "message": str(exc)})
            continue
        if path.suffix.lower() != ".obj":
            continue
        try:
            vertices, raw_faces = read_obj(path)
            faces = _triangles(raw_faces)
            if not isinstance(roi, list) or len(roi) != 6:
                bounds = bbox(vertices)
                roi = [(bounds[i] * 0.25 + bounds[i + 3] * 0.75) for i in range(3)] + [(bounds[i] * 0.75 + bounds[i + 3] * 0.25) for i in range(3)]
                roi = [min(roi[i], roi[i + 3]) for i in range(3)] + [max(roi[i], roi[i + 3]) for i in range(3)]
            roi_values = [float(value) for value in roi]
            selected = {
                index for index, face in enumerate(faces)
                if _inside(tuple(sum(vertices[vertex][axis] for vertex in face) / 3 for axis in range(3)), roi_values)
            }
            if not selected:
                raise ValueError("局部边界未覆盖任何网格面")
            selected = _expand_ring(faces, selected, rings)
            selected_before = len(selected)
            original_vertices, original_faces = len(vertices), len(faces)
            for _ in range(levels):
                vertices, faces, selected = _refine_selected(vertices, faces, selected)
            quality = _edge_quality(vertices, faces)
            if quality["degenerate_faces"] or quality["non_manifold_edges"]:
                issues.append({"severity": "严重", "code": "LOCAL_MESH_QUALITY", "file": path.name, "message": f"细化后退化面 {quality['degenerate_faces']} 个、非流形边 {quality['non_manifold_edges']} 条"})
            target = output / f"{path.stem}_local_detail.obj"
            write_obj(target, vertices, faces, f"roi={roi_values}; levels={levels}; transition_rings={rings}")
            outputs.append(target)
            model_metrics.append({"source": path.name, "output": target.name, "roi_bbox": roi_values, "refinement_levels": levels, "transition_rings": rings, "selected_base_faces": selected_before, "source_vertices": original_vertices, "source_faces": original_faces, "output_vertices": len(vertices), "output_faces": len(faces), "face_growth_ratio": len(faces) / max(1, original_faces), **quality})
        except (OSError, ValueError) as exc:
            issues.append({"severity": "严重", "code": "LOCAL_DETAIL_FAILED", "file": path.name, "message": str(exc)})
    if not model_metrics:
        issues.append({"severity": "严重", "code": "NO_BASE_MODEL", "file": "全部", "message": "未找到可细化的 OBJ 基础模型"})
    quality_path = output / "local_detail_quality.json"
    metrics = {"model_count": len(model_metrics), "models": model_metrics, "constraint_features": constraint_features, "constraint_types": dict(constraint_types), "total_source_faces": sum(item["source_faces"] for item in model_metrics), "total_output_faces": sum(item["output_faces"] for item in model_metrics)}
    write_json(quality_path, {"metrics": metrics, "issues": issues, "parameters": {"levels": levels, "transition_rings": rings, "method": refinement_method}})
    outputs.append(quality_path)
    report = finish_report(MODULE_NAME, input_files, outputs, metrics, issues, {"refinement_level": levels, "local_boundary": local_boundary, "refinement_method": refinement_method, "transition_strategy": transition_strategy})
    manifest = write_manifest(output, report)
    report["manifest_path"] = str(manifest.resolve())
    report["outputs"].append(str(manifest.resolve()))
    return report


__all__ = ["run", "MODULE_NAME"]
