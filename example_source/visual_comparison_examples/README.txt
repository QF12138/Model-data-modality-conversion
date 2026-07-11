可视化预览与对比检查模块示例数据

目录结构：
  before/  转换前数据
  after/   转换后数据

三组同名文件会自动配对：
1. tunnel_model.obj
   - 转换后模型整体向 X 方向偏移约 2m
   - X 方向跨度由 100m 变为 101m

2. borehole_points.csv
   - 转换后少 1 个点
   - 丢失 density 属性字段
   - X 坐标整体偏移 1m

3. geologic_boundary.geojson
   - 标准二维 GeoJSON，用于验证二维坐标解析
   - 转换后边界范围略有扩大
   - 丢失 source 字段，新增 model_id 字段

使用方式：
将 visual_comparison_examples 文件夹整体放到项目 source 目录中，
软件内进入“可视化预览与对比检查模块”，点击“加载示例”，再点击“执行对比检查”。
