"""从 USGS 3DEP 裸地 DEM 服务重新生成真实地形 OBJ 示例。

依赖：Pillow。默认生成 25x25 的原始网格和 17x17 的转换后简化网格。
USGS 3DEP 数据为公共领域：https://www.usgs.gov/3d-elevation-program
"""

from __future__ import annotations

import argparse
import io
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


EXPORT_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer/exportImage"
)
METERS_PER_DEGREE_LATITUDE = 111_320.0


@dataclass(frozen=True)
class Terrain:
    slug: str
    title: str
    bbox: tuple[float, float, float, float]


TERRAINS = (
    Terrain(
        slug="mount_st_helens_terrain",
        title="Mount St. Helens volcanic crater, Washington",
        bbox=(-122.22, 46.16, -122.15, 46.22),
    ),
    Terrain(
        slug="grand_canyon_terrain",
        title="Grand Canyon terrain, Arizona",
        bbox=(-112.16, 36.02, -112.06, 36.10),
    ),
)


def _download_dem(terrain: Terrain, grid_size: int = 49) -> tuple[Image.Image, dict[str, object]]:
    params = {
        "bbox": ",".join(str(value) for value in terrain.bbox),
        "bboxSR": "4326",
        "size": f"{grid_size},{grid_size}",
        "imageSR": "4326",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "json",
    }
    request_url = f"{EXPORT_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(request_url, timeout=60) as response:
        payload = json.load(response)
    with urllib.request.urlopen(str(payload["href"]), timeout=60) as response:
        image = Image.open(io.BytesIO(response.read()))
        image.load()
    payload["request_url"] = request_url
    return image, payload


def _resample(image: Image.Image, size: int) -> Image.Image:
    return image.resize((size, size), resample=Image.Resampling.BILINEAR)


def _write_obj(
    output_path: Path,
    terrain: Terrain,
    image: Image.Image,
    extent: dict[str, float],
    *,
    source_grid_size: int,
    stage: str,
    x_shift_m: float = 0.0,
    elevation_quantization_m: float | None = None,
) -> None:
    width, height = image.size
    xmin, xmax = float(extent["xmin"]), float(extent["xmax"])
    ymin, ymax = float(extent["ymin"]), float(extent["ymax"])
    mid_latitude = (ymin + ymax) / 2
    meters_per_degree_longitude = METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(mid_latitude))
    values = list(image.getdata())

    lines = [
        f"# {terrain.title}",
        "# Source: USGS National Map 3D Elevation Program (3DEP) Bare Earth DEM Dynamic Service",
        "# License: Public domain; https://www.usgs.gov/3d-elevation-program",
        f"# Source bbox EPSG:4326: {xmin:.8f},{ymin:.8f},{xmax:.8f},{ymax:.8f}",
        f"# Stage: {stage}; source grid {source_grid_size}x{source_grid_size}; mesh grid {width}x{height}",
        "# XY coordinates are local metres from the southwest corner; Z is DEM elevation in metres.",
    ]
    if x_shift_m or elevation_quantization_m:
        lines.append(
            f"# Simulated conversion: X shift {x_shift_m:.2f} m; "
            f"elevation quantization {elevation_quantization_m or 0:.2f} m."
        )

    for row in range(height):
        latitude = ymax - row * (ymax - ymin) / max(height - 1, 1)
        y = (latitude - ymin) * METERS_PER_DEGREE_LATITUDE
        for column in range(width):
            longitude = xmin + column * (xmax - xmin) / max(width - 1, 1)
            x = (longitude - xmin) * meters_per_degree_longitude + x_shift_m
            z = float(values[row * width + column])
            if elevation_quantization_m:
                z = round(z / elevation_quantization_m) * elevation_quantization_m
            lines.append(f"v {x:.3f} {y:.3f} {z:.3f}")

    for row in range(height - 1):
        for column in range(width - 1):
            top_left = row * width + column + 1
            top_right = top_left + 1
            bottom_left = top_left + width
            bottom_right = bottom_left + 1
            # 行号从北向南递增，以下绕序令面法线朝 +Z，便于预览器背面剔除。
            lines.append(f"f {top_left} {bottom_left} {top_right}")
            lines.append(f"f {top_right} {bottom_left} {bottom_right}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def regenerate(output_root: Path) -> None:
    before_dir = output_root / "before"
    after_dir = output_root / "after"
    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)

    for terrain in TERRAINS:
        dem, metadata = _download_dem(terrain)
        extent = metadata["extent"]
        _write_obj(
            before_dir / f"{terrain.slug}.obj",
            terrain,
            _resample(dem, 25),
            extent,
            source_grid_size=dem.width,
            stage="before / source mesh",
        )
        _write_obj(
            after_dir / f"{terrain.slug}.obj",
            terrain,
            _resample(dem, 17),
            extent,
            source_grid_size=dem.width,
            stage="after / simplified conversion result",
            x_shift_m=2.0,
            elevation_quantization_m=0.5,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="visual_comparison_examples 目录；默认使用脚本所在目录。",
    )
    regenerate(parser.parse_args().output_root.resolve())
