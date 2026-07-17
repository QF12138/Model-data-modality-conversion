"""Regular geological voxel generation with MagicaVoxel ``.vox`` export."""

from __future__ import annotations

import csv
import json
import math
import struct
from pathlib import Path


VOX_VERSION = 150
LITHOLOGY_COLORS = {
    "CL1": "#dbb770",
    "SS2": "#b56a43",
    "SS3": "#6d4937",
}


def _hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255


def _chunk(chunk_id: bytes, content: bytes) -> bytes:
    return chunk_id + struct.pack("<II", len(content), 0) + content


def write_vox(
    path: str | Path,
    dimensions: tuple[int, int, int],
    voxels: list[tuple[int, int, int, int]],
    palette: dict[int, tuple[int, int, int, int]],
) -> None:
    """Write a MagicaVoxel 150 file containing one indexed-color voxel model."""
    x_size, y_size, z_size = dimensions
    size = _chunk(b"SIZE", struct.pack("<III", x_size, y_size, z_size))
    xyzi_rows = b"".join(struct.pack("<BBBB", x, y, z, color_index) for x, y, z, color_index in voxels)
    xyzi = _chunk(b"XYZI", struct.pack("<I", len(voxels)) + xyzi_rows)
    rgba = b"".join(struct.pack("<BBBB", *palette.get(index, (0, 0, 0, 0))) for index in range(1, 257))
    children = size + xyzi + _chunk(b"RGBA", rgba)
    main = b"MAIN" + struct.pack("<II", 0, len(children)) + children
    Path(path).write_bytes(b"VOX " + struct.pack("<I", VOX_VERSION) + main)


def read_vox(path: str | Path) -> dict[str, object]:
    """Read the single-model `.vox` subset emitted by :func:`write_vox`."""
    data = Path(path).read_bytes()
    if len(data) < 20 or data[:4] != b"VOX ":
        raise ValueError("不是有效的 MagicaVoxel .vox 文件")
    version = struct.unpack_from("<I", data, 4)[0]
    if version < 150:
        raise ValueError(f"不支持的 .vox 版本：{version}")

    dimensions: tuple[int, int, int] | None = None
    indexed_voxels: list[tuple[int, int, int, int]] = []
    palette: dict[int, str] = {}
    offset = 8
    while offset + 12 <= len(data):
        chunk_id = data[offset:offset + 4]
        content_size, child_size = struct.unpack_from("<II", data, offset + 4)
        content_start = offset + 12
        content_end = content_start + content_size
        if content_end > len(data):
            raise ValueError(".vox 区块长度无效")
        content = data[content_start:content_end]
        if chunk_id == b"SIZE" and len(content) >= 12:
            dimensions = struct.unpack_from("<III", content)
        elif chunk_id == b"XYZI" and len(content) >= 4:
            count = struct.unpack_from("<I", content)[0]
            if len(content) < 4 + count * 4:
                raise ValueError(".vox 体素数据不完整")
            indexed_voxels = [struct.unpack_from("<BBBB", content, 4 + index * 4) for index in range(count)]
        elif chunk_id == b"RGBA" and len(content) >= 1024:
            for index in range(1, 257):
                red, green, blue, alpha = struct.unpack_from("<BBBB", content, (index - 1) * 4)
                if alpha:
                    palette[index] = f"#{red:02x}{green:02x}{blue:02x}"
        offset = content_end
        if child_size and chunk_id != b"MAIN":
            offset += child_size

    if dimensions is None or not indexed_voxels:
        raise ValueError(".vox 缺少 SIZE 或 XYZI 数据")
    return {"dimensions": dimensions, "voxels": indexed_voxels, "palette": palette}


def generate(source_dir: str | Path, output_dir: str | Path) -> dict[str, object]:
    source = Path(source_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((source / "model_boundary.json").read_text(encoding="utf-8"))
    dictionary = json.loads((source / "lithology_dictionary.json").read_text(encoding="utf-8"))
    with (source / "geologic_samples.csv").open(encoding="utf-8-sig", newline="") as stream:
        samples = list(csv.DictReader(stream))

    origin_x, origin_y, origin_z = config["origin"]
    size_x, size_y, size_z = config["size"]
    step_x, step_y, step_z = config["voxel_size"]
    dimensions = (int(size_x / step_x), int(size_y / step_y), int(size_z / step_z))
    rows: list[list[object]] = []
    voxel_codes: list[tuple[int, int, int, str]] = []
    for z_index in range(dimensions[2]):
        center_z = origin_z + (z_index + 0.5) * step_z
        for y_index in range(dimensions[1]):
            center_y = origin_y + (y_index + 0.5) * step_y
            for x_index in range(dimensions[0]):
                center_x = origin_x + (x_index + 0.5) * step_x
                nearest = sorted(
                    samples,
                    key=lambda row: (center_x - float(row["x"])) ** 2
                    + (center_y - float(row["y"])) ** 2
                    + (center_z - float(row["z"])) ** 2,
                )[:4]
                weights = [
                    1 / max(1e-9, math.dist((center_x, center_y, center_z), (float(row["x"]), float(row["y"]), float(row["z"]))) ** 2)
                    for row in nearest
                ]
                total_weight = sum(weights)
                density = sum(weight * float(row["density_g_cm3"]) for weight, row in zip(weights, nearest)) / total_weight
                permeability = sum(weight * float(row["permeability_m_d"]) for weight, row in zip(weights, nearest)) / total_weight
                lithology_code = max(
                    {row["lithology_code"] for row in nearest},
                    key=lambda code: sum(weight for weight, row in zip(weights, nearest) if row["lithology_code"] == code),
                )
                rows.append([
                    x_index, y_index, z_index, center_x, center_y, center_z, lithology_code,
                    dictionary[lithology_code]["name"], round(density, 4), round(permeability, 5),
                ])
                voxel_codes.append((x_index, y_index, z_index, lithology_code))

    csv_path = output / "geologic_voxel_cells.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "i", "j", "k", "center_x", "center_y", "center_z", "lithology_code",
            "lithology_name", "density_g_cm3", "permeability_m_d",
        ])
        writer.writerows(rows)

    palette_codes = sorted(dictionary, key=lambda code: int(dictionary[code].get("class", 0)))
    color_indices = {code: index for index, code in enumerate(palette_codes, start=1)}
    vox_path = output / "geologic_voxel_model.vox"
    write_vox(
        vox_path,
        dimensions,
        [(x, y, z, color_indices[code]) for x, y, z, code in voxel_codes],
        {color_indices[code]: _hex_to_rgba(LITHOLOGY_COLORS.get(code, "#7d756f")) for code in palette_codes},
    )

    header_path = output / "geologic_voxel_model.json"
    header_path.write_text(json.dumps({
        "format": "MagicaVoxel .vox + regular_voxel_grid attributes",
        "dimensions": dimensions,
        "origin": config["origin"],
        "voxel_size": config["voxel_size"],
        "cell_count": len(rows),
        "attributes": ["lithology_code", "density_g_cm3", "permeability_m_d"],
        "data_file": csv_path.name,
        "visualization_file": vox_path.name,
        "crs": config["crs"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = output / "voxel_generation_report.json"
    report_path.write_text(json.dumps({
        "status": "success",
        "cell_count": len(rows),
        "empty_ratio": 0.0,
        "interpolation": config["interpolation"],
        "lithology_classes": len(dictionary),
        "bounds": [config["origin"], config["size"]],
        "visualization_format": ".vox",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "success",
        "files": [str(csv_path), str(vox_path), str(header_path), str(report_path)],
        "summary": f"生成 {dimensions[0]}×{dimensions[1]}×{dimensions[2]} 规则体素，共 {len(rows)} 个单元（.vox）",
    }


__all__ = ["generate", "read_vox", "write_vox"]
