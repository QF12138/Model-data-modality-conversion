模型版本管理与成果追溯模块示例数据

目录用途：
1. project_history.json：包含 V1.0.0、V1.1.0、V1.2.0 三个完整历史版本。
2. v1/v2/v3/source：各版本来源数据，包括钻孔分层、断层边界和地下水样点。
3. v1/v2/v3/output：各版本模型成果、属性表和交付说明。
4. v1/v2/v3/quality：各版本质量检查报告。

使用方式：
将整个 version_management_examples 文件夹复制到项目的 source 目录下，最终路径应为：
source/version_management_examples/project_history.json

启动 main.py，进入“模型版本管理与成果追溯”模块，点击“加载示例数据”。
程序会导入三个历史版本，可查看追溯链、选择两个版本进行差异对比，并归档所选版本。
