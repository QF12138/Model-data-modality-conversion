# 模型质量校验示例

本目录同时包含通过基线和故障注入数据，用于验证五类质量规则。

- `model_quality_closed_mesh.obj/.stl/.ply/.vtk`：同一个封闭四面体，用于验证多格式几何和拓扑解析。
- `model_quality_valid.ifc`：结构完整、标识唯一的最小 IFC4 示例。
- `model_quality_valid_attributes.csv`：字段完整、坐标精度一致的属性表。
- `model_quality_open_mesh.obj`：缺少底面，用于触发开放边界定位。
- `model_quality_boundary.geojson`：包含未闭合面环、空属性和超范围坐标。
- `model_quality_attributes.csv`：包含空属性、重复 ID 和非法坐标。

界面中的“加载示例数据”会加载上述业务文件；README 不参与检查。建议先以默认规则运行，再在参数配置页将坐标精度阈值设为 `3`，验证精度规则是否生效。
