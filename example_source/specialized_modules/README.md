# 八个专业功能模块示例数据

本目录只包含需求文档指定的八个模块示例。每个子目录均可独立加载；软件会把转换成果写入 `output/specialized_modules/<模块英文名>/`，不会修改源示例。

## 在软件中验证

1. 运行项目根目录的 `run.bat`。
2. 在左侧选择下表中的任一模块。
3. 在模块专属工作台点击“加载复杂示例”，需要时到“参数配置”页调整参数。
4. 返回工作台点击“执行转换”。
5. 在状态、日志、预览/追溯页检查质量分、异常和成果；实际文件及 `conversion_manifest.json` 位于上述输出目录。

也可运行 `python -m unittest tests.test_specialized_modules -v` 一次验证全部八个示例。测试使用临时输出目录，不会覆盖示例源数据。

| 目录 | 模块 | 主要验证内容 |
|---|---|---|
| `coordinate_datum_unification` | 坐标与基准统一 | 27 个多来源坐标/复核点、地理与工程仿射、高程和里程统一 |
| `section_map_conversion` | 剖面与平面图转换 | 3 条剖面、27 个线划点、5 个平面要素、控制点定位与拓扑检查 |
| `geologic_line_reconstruction` | 地质解释线重建 | 5 类边界、13 个分段、容差内连接和平滑、超容差异常断点 |
| `raster_vector_conversion` | 栅格与矢量转换 | 双 ASCII Grid、复杂 GeoJSON 图斑、双向转换、分辨率与覆盖率 |
| `point_cloud_conversion` | 点云数据转换 | 90 个混合来源点、体素重采样、规则分类、CSV/PLY 输出 |
| `geological_attribute_mapping` | 地质属性映射 | 24 个样本、9 个目标单元、7 类属性的 IDW/最近邻和逐字段追溯 |
| `multiscale_model_conversion` | 多尺度模型转换 | 地表+断层双 OBJ、三级尺度链、裁剪抽稀和误差比较 |
| `local_detailed_model` | 局部精细模型构建 | 地表+洞室双模型、4 类工程约束、ROI 细分和局部网格质量检查 |
