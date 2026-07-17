"""Professional off-screen rendering for MagicaVoxel models using trimesh."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyglet
import trimesh
from pyvox.parser import VoxParser
from trimesh.util import BytesIO
from trimesh.viewer.windowed import SceneViewer


BACKGROUND = (22, 26, 35, 255)


def _render_hidden_scene(scene: trimesh.Scene, width: int, height: int) -> bytes:
    """Render through an off-screen positioned OpenGL context on Windows."""
    window = SceneViewer(
        scene,
        start_loop=False,
        visible=False,
        resolution=(width, height),
        resizable=False,
        background=BACKGROUND,
    )
    window.set_location(-32000, -32000)
    window.set_visible(True)
    try:
        for _ in range(2):
            pyglet.clock.tick()
            window.switch_to()
            window.dispatch_events()
            window.dispatch_event("on_draw")
            window.flip()
        output = BytesIO()
        window.save_image(output)
        return output.getvalue()
    finally:
        window.close()

def render_vox_preview(path: str | Path, width: int, height: int) -> bytes:
    """Render a `.vox` file to PNG through trimesh's OpenGL scene renderer."""
    vox = VoxParser(str(path)).parse()
    model = vox.models[0]
    dimensions = (model.size.x, model.size.y, model.size.z)
    occupied = np.zeros(dimensions, dtype=bool)
    colors = np.zeros((*dimensions, 4), dtype=np.uint8)
    for voxel in model.voxels:
        occupied[voxel.x, voxel.y, voxel.z] = True
        color = vox.palette[voxel.c - 1]
        colors[voxel.x, voxel.y, voxel.z] = (color.r, color.g, color.b, color.a)

    transform = np.diag((1.0, 1.0, 0.5, 1.0))
    voxel_grid = trimesh.voxel.VoxelGrid(occupied, transform=transform)
    mesh = voxel_grid.as_boxes(colors=colors)
    mesh.apply_translation(-mesh.centroid)
    scene = trimesh.Scene(mesh)
    scene.set_camera(angles=(np.radians(28), 0.0, np.radians(42)), distance=max(dimensions) * 2.4)
    return _render_hidden_scene(scene, max(320, width), max(260, height))


__all__ = ["render_vox_preview"]
