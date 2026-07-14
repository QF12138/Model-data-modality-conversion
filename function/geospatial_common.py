"""Shared, dependency-free helpers for the eight specialized geology modules.

The project is intentionally runnable with the Python standard library only.  The
helpers in this file therefore implement the small, auditable subset of CSV,
GeoJSON and OBJ handling needed by the functional modules instead of silently
depending on a desktop GIS installation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence


Point3D = tuple[float, float, float]


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{Path(path).name} 的 JSON 根节点必须是对象")
    return value


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _atomic_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def write_text(path: str | Path, content: str) -> Path:
    """Atomically write a UTF-8 text artifact."""
    return _atomic_text(Path(path), content)


def write_json(path: str | Path, payload: Any) -> Path:
    return _atomic_text(Path(path), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_csv(path: str | Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str] | None = None) -> Path:
    target = Path(path)
    names = list(fieldnames or [])
    if not names:
        for row in rows:
            for key in row:
                if key not in names:
                    names.append(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_float(value: Any, name: str, default: float | None = None) -> float:
    if value in (None, "") and default is not None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值，收到 {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数值")
    return number


def parse_number(value: Any, default: float) -> float:
    """Extract the first number from a friendly GUI parameter such as ``50%``."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    token = ""
    for char in text:
        if char.isdigit() or char in ".-+eE":
            token += char
        elif token:
            break
    try:
        return float(token)
    except ValueError:
        return default


def load_config(paths: Iterable[str | Path], keywords: Iterable[str] = ()) -> dict[str, Any]:
    keys = tuple(keyword.lower() for keyword in keywords)
    merged: dict[str, Any] = {}
    for item in paths:
        path = Path(item)
        if path.suffix.lower() != ".json" or path.name.lower().endswith(".geojson"):
            continue
        if keys and not any(key in path.stem.lower() for key in keys):
            continue
        try:
            merged.update(read_json(path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return merged


def iter_geometry_points(geometry: dict[str, Any]) -> Iterable[list[float]]:
    geometry_type = str(geometry.get("type", ""))
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "Point":
        if isinstance(coordinates, list):
            yield coordinates
        return
    if geometry_type in {"MultiPoint", "LineString"}:
        for point in coordinates or []:
            yield point
        return
    if geometry_type in {"MultiLineString", "Polygon"}:
        for part in coordinates or []:
            for point in part or []:
                yield point
        return
    if geometry_type == "MultiPolygon":
        for polygon in coordinates or []:
            for ring in polygon or []:
                for point in ring or []:
                    yield point


def map_geometry(geometry: dict[str, Any], transform: Any) -> dict[str, Any]:
    result = json.loads(json.dumps(geometry))

    def walk(value: Any) -> Any:
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            x, y = float(value[0]), float(value[1])
            z = float(value[2]) if len(value) > 2 else 0.0
            converted = transform(x, y, z)
            return list(converted) if len(value) > 2 else list(converted[:2])
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    result["coordinates"] = walk(result.get("coordinates", []))
    return result


def distance(a: Sequence[float], b: Sequence[float]) -> float:
    length = min(len(a), len(b), 3)
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(length)))


def bbox(points: Iterable[Sequence[float]]) -> list[float]:
    values = [tuple(float(v) for v in point[:3]) for point in points]
    if not values:
        return [0.0] * 6
    dimensions = max(3, max(len(item) for item in values))
    padded = [item + (0.0,) * (dimensions - len(item)) for item in values]
    return [min(item[i] for item in padded) for i in range(3)] + [max(item[i] for item in padded) for i in range(3)]


def point_in_polygon(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i, current in enumerate(ring):
        previous = ring[j]
        xi, yi = float(current[0]), float(current[1])
        xj, yj = float(previous[0]), float(previous[1])
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-30) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def read_obj(path: str | Path) -> tuple[list[Point3D], list[tuple[int, ...]]]:
    vertices: list[Point3D] = []
    faces: list[tuple[int, ...]] = []
    with Path(path).open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            parts = raw.strip().split()
            if not parts or parts[0].startswith("#"):
                continue
            if parts[0] == "v" and len(parts) >= 4:
                vertices.append((as_float(parts[1], f"OBJ 第 {line_number} 行 X"), as_float(parts[2], "Y"), as_float(parts[3], "Z")))
            elif parts[0] == "f" and len(parts) >= 4:
                indices: list[int] = []
                for token in parts[1:]:
                    raw_index = int(token.split("/", 1)[0])
                    index = raw_index - 1 if raw_index > 0 else len(vertices) + raw_index
                    if not 0 <= index < len(vertices):
                        raise ValueError(f"{Path(path).name} 第 {line_number} 行存在非法面索引")
                    indices.append(index)
                faces.append(tuple(indices))
    if not vertices:
        raise ValueError(f"{Path(path).name} 不包含 OBJ 顶点")
    return vertices, faces


def write_obj(path: str | Path, vertices: Sequence[Sequence[float]], faces: Sequence[Sequence[int]], comment: str = "") -> Path:
    lines = ["# Geological model conversion toolkit"]
    if comment:
        lines.append(f"# {comment}")
    lines.extend(f"v {float(x):.9g} {float(y):.9g} {float(z):.9g}" for x, y, z in vertices)
    lines.extend("f " + " ".join(str(int(index) + 1) for index in face) for face in faces if len(face) >= 3)
    return _atomic_text(Path(path), "\n".join(lines) + "\n")


def remap_mesh(vertices: Sequence[Point3D], faces: Sequence[Sequence[int]], keep_faces: Iterable[int]) -> tuple[list[Point3D], list[tuple[int, ...]]]:
    selected = [faces[index] for index in keep_faces]
    used = sorted({vertex for face in selected for vertex in face})
    mapping = {old: new for new, old in enumerate(used)}
    return [vertices[index] for index in used], [tuple(mapping[index] for index in face) for face in selected]


def finish_report(
    module: str,
    inputs: Sequence[str | Path],
    outputs: Sequence[str | Path],
    metrics: dict[str, Any],
    issues: Sequence[dict[str, Any]] = (),
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_paths = [str(Path(path).resolve()) for path in outputs]
    serious = sum(1 for issue in issues if issue.get("severity") == "严重")
    warnings = sum(1 for issue in issues if issue.get("severity") == "警告")
    score = max(0, 100 - serious * 30 - warnings * 8)
    return {
        "module": module,
        "status": "完成" if output_paths and not serious else "需复核" if output_paths else "失败",
        "score": score,
        "grade": "优秀" if score >= 90 else "合格" if score >= 80 else "需复核",
        "file_count": len(inputs),
        "output_count": len(output_paths),
        "outputs": output_paths,
        "artifacts": [
            {"path": path, "name": Path(path).name, "sha256": sha256(path), "size_bytes": Path(path).stat().st_size}
            for path in output_paths
        ],
        "metrics": metrics,
        "parameters": parameters or {},
        "issues": list(issues),
        "issue_count": len(issues),
    }


def write_manifest(output_dir: str | Path, report: dict[str, Any], name: str = "conversion_manifest.json") -> Path:
    target = Path(output_dir) / name
    write_json(target, report)
    return target
