"""Unified dispatcher for the eight document-required functional modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import coordinate_datum_unification, geologic_line_reconstruction
from . import geological_attribute_mapping, local_detailed_model
from . import multiscale_model_conversion, point_cloud_conversion
from . import raster_vector_conversion, section_map_conversion


MODULE_SLUGS = {
    "坐标与基准统一模块": "coordinate_datum_unification",
    "剖面与平面图转换模块": "section_map_conversion",
    "地质解释线重建模块": "geologic_line_reconstruction",
    "栅格与矢量转换模块": "raster_vector_conversion",
    "点云数据转换模块": "point_cloud_conversion",
    "地质属性映射模块": "geological_attribute_mapping",
    "多尺度模型转换模块": "multiscale_model_conversion",
    "局部精细模型构建模块": "local_detailed_model",
}


def _value(parameters: dict[str, Any], name: str, default: Any) -> Any:
    value = parameters.get(name, default)
    return default if value in (None, "", "默认") else value


def run_specialized_module(
    module_name: str, input_files: list[str], output_root: str | Path,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if module_name not in MODULE_SLUGS:
        raise ValueError(f"不支持的专业功能模块：{module_name}")
    params = dict(parameters or {})
    output_dir = Path(output_root) / MODULE_SLUGS[module_name]
    if module_name == "坐标与基准统一模块":
        return coordinate_datum_unification.run(input_files, output_dir, _value(params, "目标坐标系", "EPSG:3857"), _value(params, "目标高程基准", "1985 国家高程基准"), _value(params, "单位体系", "m"), _value(params, "转换精度", "0.01"))
    if module_name == "剖面与平面图转换模块":
        return section_map_conversion.run(input_files, output_dir, _value(params, "矢量化精度", "0.01"), _value(params, "拓扑规则", "严格检查"), _value(params, "空间定位方式", "控制点/基线定位"), _value(params, "图层映射", "自动"))
    if module_name == "地质解释线重建模块":
        return geologic_line_reconstruction.run(input_files, output_dir, _value(params, "重建算法", "端点匹配+平滑"), _value(params, "平滑参数", "1"), _value(params, "连接容差", "1.0"), _value(params, "边界约束", "保持地质类型与接触关系"))
    if module_name == "栅格与矢量转换模块":
        return raster_vector_conversion.run(input_files, output_dir, _value(params, "转换方向", "自动双向"), _value(params, "分辨率", "10"), _value(params, "边界提取阈值", "1"), _value(params, "属性映射规则", "value"))
    if module_name == "点云数据转换模块":
        return point_cloud_conversion.run(input_files, output_dir, _value(params, "抽稀比例", "100%"), _value(params, "重采样间距", "1"), _value(params, "分类规则", "高程分位分类"), _value(params, "输出格式", "PLY"))
    if module_name == "地质属性映射模块":
        return geological_attribute_mapping.run(input_files, output_dir, _value(params, "映射字段", "lithology,permeability,density,elastic_modulus,cohesion,friction_angle,water_state"), _value(params, "插值方法", "IDW"), _value(params, "搜索半径", "100"), _value(params, "追溯标识", "自动生成"))
    if module_name == "多尺度模型转换模块":
        return multiscale_model_conversion.run(input_files, output_dir, _value(params, "目标尺度", "工程尺度"), _value(params, "抽稀策略", "顶点聚类 2.0"), _value(params, "加密规则", "按目标尺度自动"), _value(params, "精度保留策略", "边界优先"))
    return local_detailed_model.run(input_files, output_dir, _value(params, "加密级别", "1"), _value(params, "局部边界", "ROI 配置文件"), _value(params, "细化方法", "三角形中点细分"), _value(params, "过渡区策略", "1 环过渡"))


def example_directory(project_root: str | Path, module_name: str) -> Path:
    return Path(project_root) / "example_source" / "specialized_modules" / MODULE_SLUGS[module_name]


__all__ = ["MODULE_SLUGS", "run_specialized_module", "example_directory"]
