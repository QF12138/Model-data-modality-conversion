地质语义编码转换模块文件说明

1. semantic_library.json
   完整项目级语义库。程序运行时优先从 source 目录读取。

2. semantic_library.csv
   JSON 语义库的扁平维护版，可使用 Excel 打开并编辑。

3. semantic_sample_project_dictionary.csv
   项目自定义语义字典示例。软件会先加载它，再处理业务数据。

4. semantic_sample_attributes.csv
   钻孔/属性表语义转换示例，包含规范名、别名、英文名、地质符号、项目编码、复合描述和未匹配术语。

5. semantic_sample_features.geojson
   空间要素属性语义转换示例。

使用方法：
- 将 function/semantic_encoding.py 替换到原项目 function 目录。
- 将 source 下全部文件复制到原项目 source 目录。
- 将 main.py 替换原主程序文件，或按修改点合并。
- 启动软件，进入“地质语义编码转换模块”。
- 点击“加载示例数据”，然后点击“执行语义编码转换”。
- 规范化后的 CSV/GeoJSON 会自动写入 output/semantic 目录。

编码说明：
- PROJECT 是本工具内部稳定编码或项目自定义编码。
- SYMBOL 是常见地质符号。
- 不应把 PROJECT 编码直接宣称为国家标准编号；若项目需要正式 GB/T、行业或地方标准编号，应通过项目语义字典补充并注明标准版本。
