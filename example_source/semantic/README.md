# 地质语义编码示例

- `semantic_library.json`：默认完整语义库，覆盖地层、岩性、构造、地下水、不良地质、围岩等级和工程地质指标七个语义域。
- `semantic_library.csv`：便于人工审阅和外部维护的平面版本。
- `semantic_sample_project_dictionary.csv`：项目级扩展字典，演示别名和项目编码覆盖。
- `semantic_sample_attributes.csv`：标准演示表，涵盖规范名、别名、地质符号、项目编码和中英文术语。
- `semantic_sample_features.geojson`：GeoJSON 属性语义归一示例。
- `semantic_unmapped_terms.csv`：单独的故障注入数据，用于验证未匹配清单；界面“加载示例数据”默认不加载该文件。

成功运行会生成规范化 CSV/GeoJSON、输入输出 SHA-256、语义关系、冲突记录、语义库审计结果和 `semantic_conversion_manifest.json`。默认样例应达到 100% 术语覆盖；故障注入文件应产生明确的未匹配记录，不得伪造编码。
