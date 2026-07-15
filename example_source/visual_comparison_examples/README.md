# 可视化预览与对比检查示例

## 目录与自动配对

- `before/`：转换前数据。
- `after/`：转换后数据。
- 两个目录中的同名文件自动配对，不会把单文件与自身对比。
- `expected_report_5percent.json`：固定回归期望值，不包含每次运行都会变化的 ID、时间和校验和。

## 真实三维地形来源

界面中的 OBJ 不再使用规则长方体，而是从 USGS National Map 3D Elevation Program（3DEP）裸地 DEM 动态服务生成：

- `mount_st_helens_terrain.obj`：美国华盛顿州圣海伦斯火山口，真实火山地貌。
- `grand_canyon_terrain.obj`：美国亚利桑那州科罗拉多大峡谷，真实峡谷地貌。
- 数据许可：USGS 3DEP 公共领域，可免费使用且无使用限制。
- 官方数据页：https://www.usgs.gov/3d-elevation-program
- 官方 DEM 服务：https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer

每处地形的 `before` 为 25×25 网格，`after` 模拟常见格式转换后的 17×17 网格简化、X 方向 2m 偏移和 0.5m 高程量化。可运行 `python regenerate_real_terrain.py` 从官方服务重新生成。

## 四组已知差异

1. 两组真实地形 OBJ
   - 转换后网格从 625 个顶点、1152 个三角面简化为 289 个顶点、512 个三角面。
   - 转换后整体向 X 正方向偏移 2m，高程按 0.5m 量化。
2. `borehole_points.csv`
   - 转换后少 1 个点，X 坐标整体偏移 1m。
   - 丢失 `density` 属性字段。
3. `geologic_boundary.geojson`
   - 边界范围扩大。
   - 丢失 `source` 字段，新增 `model_id` 字段。

## 界面验证

1. 进入“可视化预览与对比检查模块”，点击“加载示例”。
2. 在参数页设置剖切方向 `XY/XZ/YZ`、剖切位置和差异阈值。
3. 执行后工作台会同时绘制二维叠加、三维并排、剖切轮廓和差异热图。
4. 对比报告同时记录坐标位置、空间范围、属性映射、模型尺度和关键边界五个维度，并保留每个输入文件的 SHA-256。
