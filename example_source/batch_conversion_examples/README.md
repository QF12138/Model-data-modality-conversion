# 自动化批量转换示例数据

## 目录说明

- `01_drilling_and_boundary`：CSV、TXT、GeoJSON、JSON，演示表格和地理空间数据批量导入。
- `02_3d_models`：OBJ、ASCII STL、ASCII PLY、Legacy ASCII VTK，演示多种三维模型格式。
- `03_failure_retry_demo`：损坏 JSON 与占位 LAS，用于演示失败日志、重试、跳过和中止策略。

## 在软件中使用

1. 打开“自动化批量转换模块”。
2. 点击“加载示例”，软件会递归加载上述三个目录。
3. 默认输出格式为 `OBJ`，成果写入 `output/batch_conversion/<作业ID>/`。
4. 默认包含两个故意失败文件，因此执行结果一般为“部分失败”，可在日志中看到重试记录。
5. 只测试成功流程时，点击“清空”，再通过“添加目录”选择前两个目录。

## 注意

LAS/LAZ 与部分专有 BIM、点云格式需要额外解析库或后端转换服务。示例中的 LAS 文件只用于验证“不支持格式”的错误处理逻辑。
