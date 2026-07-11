from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ObjModel:
    """解析后的 OBJ 模型数据。"""
    file_name: str
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[list[int]] = field(default_factory=list)        # 0-based vertex indices
    edges: set[tuple[int, int]] = field(default_factory=set)
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: float = 1.0
    vertex_count: int = 0
    face_count: int = 0

    @property
    def is_empty(self) -> bool:
        return len(self.vertices) == 0 or len(self.faces) == 0


def parse_obj(filepath: str | Path) -> ObjModel:
    """解析 OBJ 文件，提取顶点与面片用于三维渲染。"""
    path = Path(filepath)
    model = ObjModel(file_name=path.name)
    raw_vertices: list[tuple[float, float, float]] = []

    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return model

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if parts[0] == "v" and len(parts) >= 4:
            raw_vertices.append(tuple(float(v) for v in parts[1:4]))
        elif parts[0] == "f" and len(parts) >= 4:
            face: list[int] = []
            for token in parts[1:]:
                idx_str = token.split("/")[0]
                if idx_str:
                    idx = int(idx_str)
                    face.append(idx - 1 if idx > 0 else len(raw_vertices) + idx)
            if len(face) >= 3:
                model.faces.append(face)

    if not raw_vertices or not model.faces:
        return model

    # 计算包围盒并归一化
    xs = [v[0] for v in raw_vertices]
    ys = [v[1] for v in raw_vertices]
    zs = [v[2] for v in raw_vertices]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    cz = (min_z + max_z) / 2
    span = max(max_x - min_x, max_y - min_y, max_z - min_z) or 1.0

    model.center = (cx, cy, cz)
    model.scale = span
    model.vertices = [((x - cx) / span, (y - cy) / span, (z - cz) / span) for x, y, z in raw_vertices]
    model.vertex_count = len(model.vertices)
    model.face_count = len(model.faces)

    # 收集所有边
    for face in model.faces:
        for i in range(len(face)):
            a, b = face[i], face[(i + 1) % len(face)]
            model.edges.add((a, b) if a < b else (b, a))

    return model


def load_models(file_paths: list[str]) -> list[ObjModel]:
    """从文件路径列表加载所有 OBJ 模型。"""
    models: list[ObjModel] = []
    for fp in file_paths:
        suffix = Path(fp).suffix.lower()
        if suffix == ".obj":
            model = parse_obj(fp)
            if not model.is_empty:
                models.append(model)
    return models


# ---------- 3D 数学工具 ----------

def rotate_x(point: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    cx, cy = math.cos(angle), math.sin(angle)
    return (point[0], point[1] * cx - point[2] * cy, point[1] * cy + point[2] * cx)


def rotate_y(point: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    cx, cy = math.cos(angle), math.sin(angle)
    return (point[0] * cx + point[2] * cy, point[1], -point[0] * cy + point[2] * cx)


def rotate_z(point: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    cx, cy = math.cos(angle), math.sin(angle)
    return (point[0] * cx - point[1] * cy, point[0] * cy + point[1] * cx, point[2])


def project_ortho(point: tuple[float, float, float], scale: float, cx: float, cy: float) -> tuple[float, float]:
    """正交投影：x→屏幕右，y→屏幕上，z→忽略（用于线框）。"""
    return (cx + point[0] * scale, cy - point[1] * scale)


def project_persp(point: tuple[float, float, float], scale: float, cx: float, cy: float, d: float = 5.0) -> tuple[float, float]:
    """简单透视投影。"""
    z = point[2] + d
    if z <= 0.01:
        z = 0.01
    factor = scale / z
    return (cx + point[0] * factor, cy - point[1] * factor)


def compute_face_normal(v0: tuple[float, float, float], v1: tuple[float, float, float], v2: tuple[float, float, float]) -> tuple[float, float, float]:
    """计算面法线（未归一化）。"""
    a = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
    b = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def face_visible(v0: tuple[float, float, float], v1: tuple[float, float, float],
                 v2: tuple[float, float, float]) -> bool:
    """检查面是否朝向观察者（背面剔除）。观察方向为 +Z。"""
    normal = compute_face_normal(v0, v1, v2)
    # 面法线的 z 分量 > 0 表示朝向观察者
    return normal[2] > 0


# ---------- 渲染状态 ----------

@dataclass
class RenderState:
    """控制三维视图的旋转、缩放与偏移。"""
    rot_x: float = 0.35      # X 轴旋转角（弧度）
    rot_y: float = -0.55     # Y 轴旋转角
    rot_z: float = 0.0
    zoom: float = 1.0        # 缩放系数
    pan_x: float = 0.0
    pan_y: float = 0.0
    auto_spin: bool = True
    spin_speed: float = 0.008
    persp: bool = False


def transform_vertices(model: ObjModel, state: RenderState) -> list[tuple[float, float, float]]:
    """将模型顶点按当前视图状态旋转。"""
    result: list[tuple[float, float, float]] = []
    for v in model.vertices:
        p = v
        if state.rot_z:
            p = rotate_z(p, state.rot_z)
        if state.rot_x:
            p = rotate_x(p, state.rot_x)
        if state.rot_y:
            p = rotate_y(p, state.rot_y)
        result.append(p)
    return result


def collect_face_depths(transformed: list[tuple[float, float, float]], faces: list[list[int]]) -> list[tuple[float, int, list[int]]]:
    """计算每个面的平均深度，用于画家算法排序。"""
    depths: list[tuple[float, int, list[int]]] = []
    for idx, face in enumerate(faces):
        try:
            pts = [transformed[i] for i in face]
        except IndexError:
            continue
        avg_z = sum(p[2] for p in pts) / len(pts)
        depths.append((avg_z, idx, face))
    return depths
