# 转换规则模板示例

本目录的数据由 `example_manifest.json` 按项目类型和数据来源路由，用于验证模板推荐与实际应用。

- 隧道钻孔、超前预报、边坡剖面、城市钻孔、区域地质、点云和网格节点覆盖不同项目场景；
- `custom_template_example.json` 用于验证外部模板导入；
- 模板应用结果会记录应用 ID、模板内容指纹、输入/输出 SHA-256、字段映射结果和质量规则结果；
- “复制为项目模板”会将用户副本持久化到 `output/rule_templates/user`，重新启动软件后仍可加载；
- 导出模板库时，`template_index.json` 会记录每个模板文件的 SHA-256、内容指纹和模板校验结果。

模板中的坐标 `scale_factor` 和 `offset_x/y/z` 会直接执行；涉及 WGS84、CGCS2000 等投影变换的规则只记录配置，仍需由 pyproj/GDAL 服务执行，不能伪装成已重投影。
