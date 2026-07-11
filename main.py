from __future__ import annotations

import json
import sys
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import filedialog, font as tkfont
from tkinter import ttk


APP_TITLE = "地质环境模型数据模态转换工具包"

GROUP_ORDER = [
    "数据准备与标准化",
    "数据转换与三维化",
    "模型生成与尺度处理",
    "检查输出与管理",
]

BACKEND_ENDPOINTS = {
    "create_project": "POST /api/projects",
    "upload_dataset": "POST /api/datasets",
    "save_template": "POST /api/rule-templates",
    "create_task": "POST /api/conversion-tasks",
    "run_task": "POST /api/conversion-tasks/{task_id}/run",
    "task_status": "GET /api/conversion-tasks/{task_id}",
    "quality_report": "GET /api/quality-reports/{task_id}",
    "version_archive": "POST /api/model-versions",
}


@dataclass(frozen=True)
class ModuleSpec:
    group: str
    name: str
    description: str
    inputs: tuple[str, ...]
    parameters: tuple[str, ...]
    outputs: tuple[str, ...]
    mysql_tables: tuple[str, ...]


FEATURE_MODULES = [
    ModuleSpec(
        "数据准备与标准化",
        "数据预处理与质量清洗模块",
        "对导入的钻孔、剖面、点云、栅格、矢量、网格及表格数据进行字段校验、缺失值识别、重复数据清理、异常值检查和单位规范化处理。",
        ("钻孔/剖面/点云/栅格/矢量/网格/表格文件", "字段字典", "单位换算表"),
        ("字段必填规则", "重复识别键", "异常值阈值", "单位标准"),
        ("清洗后数据", "数据问题清单", "质量统计报告"),
        ("datasets", "data_quality_issues", "cleaning_rules"),
    ),
    ModuleSpec(
        "数据准备与标准化",
        "坐标与基准统一模块",
        "对不同来源数据的坐标系、高程基准、单位和工程里程进行统一转换，解决模型融合前的空间基准不一致问题。",
        ("源空间数据", "坐标系定义", "高程基准文件", "工程里程表"),
        ("目标坐标系", "目标高程基准", "单位体系", "转换精度"),
        ("统一基准数据", "转换参数记录", "误差检查结果"),
        ("coordinate_systems", "datum_transform_jobs", "task_artifacts"),
    ),
    ModuleSpec(
        "数据准备与标准化",
        "地质语义编码转换模块",
        "建立地层、岩性、构造、地下水、不良地质、围岩等级和工程地质指标等语义字典，支持编码映射、名称归一和语义关联转换。",
        ("地质属性表", "项目编码表", "行业标准字典"),
        ("语义字典", "编码映射规则", "同义词归一策略", "冲突处理方式"),
        ("标准编码数据", "语义映射报告", "冲突记录"),
        ("semantic_dictionaries", "semantic_mappings", "normalized_attributes"),
    ),
    ModuleSpec(
        "数据准备与标准化",
        "转换规则模板库模块",
        "提供常用数据格式、字段映射、坐标转换、属性映射、模型输出和质量检查规则模板，支持按项目类型和数据来源复用配置。",
        ("历史规则模板", "项目类型", "数据来源说明"),
        ("字段映射", "坐标规则", "属性映射", "质量检查规则"),
        ("规则模板", "模板版本", "复用配置包"),
        ("rule_templates", "rule_template_versions", "template_bindings"),
    ),
    ModuleSpec(
        "数据转换与三维化",
        "钻孔数据三维化模块",
        "将钻孔柱状图、岩性分层、地下水位、试验指标和结构面信息转换为三维空间对象，为地层建模、属性插值和环境评价提供基础。",
        ("钻孔柱状图", "岩性分层表", "地下水位", "试验指标", "结构面信息"),
        ("孔口坐标", "深度基准", "分层规则", "三维对象类型"),
        ("三维钻孔对象", "分层空间对象", "钻孔属性索引"),
        ("boreholes", "borehole_layers", "spatial_objects"),
    ),
    ModuleSpec(
        "数据转换与三维化",
        "钻孔属性结构化模块",
        "对岩性类别、地下水特征、试验参数和工程地质指标进行结构化整理，实现钻孔属性与空间模型的关联管理。",
        ("钻孔属性表", "试验数据", "地下水记录", "工程指标表"),
        ("属性分类体系", "字段映射", "关联主键", "缺失值策略"),
        ("结构化属性库", "空间关联表", "属性完整性报告"),
        ("borehole_attributes", "attribute_relations", "data_quality_issues"),
    ),
    ModuleSpec(
        "数据转换与三维化",
        "剖面与平面图转换模块",
        "支持工程地质剖面图、平面地质图和解释线划的矢量化、拓扑检查和空间定位，实现二维地质资料向三维建模数据的转换。",
        ("工程地质剖面图", "平面地质图", "解释线划", "图廓控制点"),
        ("矢量化精度", "拓扑规则", "空间定位方式", "图层映射"),
        ("矢量线面数据", "拓扑检查结果", "定位成果"),
        ("map_layers", "topology_checks", "spatial_objects"),
    ),
    ModuleSpec(
        "数据转换与三维化",
        "地质解释线重建模块",
        "对地层界线、断层线、接触关系和解释成果进行提取与重建，形成可用于三维建模的空间边界数据。",
        ("地层界线", "断层线", "接触关系", "解释成果"),
        ("重建算法", "平滑参数", "连接容差", "边界约束"),
        ("空间边界数据", "重建质量指标", "异常断点清单"),
        ("geologic_boundaries", "fault_lines", "reconstruction_jobs"),
    ),
    ModuleSpec(
        "数据转换与三维化",
        "栅格与矢量转换模块",
        "支持遥感影像、DEM、地质图斑和专题图层之间的栅格与矢量数据转换，实现边界提取、属性映射和空间精度控制。",
        ("遥感影像", "DEM", "地质图斑", "专题图层"),
        ("转换方向", "分辨率", "边界提取阈值", "属性映射规则"),
        ("栅格成果", "矢量成果", "空间精度报告"),
        ("raster_layers", "vector_layers", "conversion_tasks"),
    ),
    ModuleSpec(
        "数据转换与三维化",
        "点云数据转换模块",
        "对激光扫描点云、摄影测量点云和监测点云进行抽稀、重采样、分类和模型转换，形成可用于建模分析的标准数据。",
        ("激光扫描点云", "摄影测量点云", "监测点云", "分类样本"),
        ("抽稀比例", "重采样间距", "分类规则", "输出格式"),
        ("标准点云", "分类点云", "点云统计"),
        ("point_clouds", "point_cloud_classes", "conversion_tasks"),
    ),
    ModuleSpec(
        "模型生成与尺度处理",
        "网格模型生成模块",
        "将地层面、断层面、地质体边界等几何对象转换为有限元网格、有限差分网格和计算分析网格，为数值模拟和工程分析提供基础模型。",
        ("地层面", "断层面", "地质体边界", "约束线"),
        ("网格类型", "单元尺寸", "质量阈值", "边界约束"),
        ("有限元网格", "有限差分网格", "网格质量报告"),
        ("mesh_models", "mesh_cells", "quality_reports"),
    ),
    ModuleSpec(
        "模型生成与尺度处理",
        "体素模型生成模块",
        "将离散地质信息转换为规则体素单元，形成具备空间属性表达能力的三维体素模型。",
        ("离散地质点", "地质边界", "属性样本", "建模范围"),
        ("体素尺寸", "插值方法", "空值填补", "边界裁剪"),
        ("体素模型", "体素属性表", "范围索引"),
        ("voxel_models", "voxel_cells", "attribute_mappings"),
    ),
    ModuleSpec(
        "模型生成与尺度处理",
        "地质属性映射模块",
        "将岩性、渗透系数、密度、弹性模量、强度参数、含水状态等属性映射到面、体、网格或体素单元中，保持来源和方法可追溯。",
        ("属性样本", "面/体/网格/体素单元", "来源说明"),
        ("映射字段", "插值方法", "搜索半径", "追溯标识"),
        ("属性化模型", "映射关系表", "方法追溯报告"),
        ("attribute_mappings", "model_properties", "lineage_records"),
    ),
    ModuleSpec(
        "模型生成与尺度处理",
        "多尺度模型转换模块",
        "支持区域尺度、工程尺度和局部精细尺度模型之间的裁剪、抽稀、加密和尺度转换，兼顾计算效率与关键部位表达精度。",
        ("区域模型", "工程模型", "局部模型", "裁剪范围"),
        ("目标尺度", "抽稀策略", "加密规则", "精度保留策略"),
        ("多尺度模型", "尺度转换记录", "精度对比报告"),
        ("model_scales", "scale_conversion_jobs", "model_versions"),
    ),
    ModuleSpec(
        "模型生成与尺度处理",
        "局部精细模型构建模块",
        "对断层破碎带、地下洞室、边坡、隧道及其他关键工程部位进行局部加密和精细模型构建，提高局部表达精度。",
        ("关键部位范围", "基础模型", "局部约束", "工程对象"),
        ("加密级别", "局部边界", "细化方法", "过渡区策略"),
        ("局部精细模型", "加密网格", "局部质量报告"),
        ("local_detail_models", "mesh_models", "quality_reports"),
    ),
    ModuleSpec(
        "检查输出与管理",
        "模型质量校验模块",
        "对转换后的模型进行几何闭合性、拓扑关系、属性完整性、一致性和坐标精度检查，识别模型缺陷和数据异常。",
        ("转换后模型", "属性表", "坐标记录", "质量规则"),
        ("闭合性规则", "拓扑规则", "完整性规则", "坐标精度阈值"),
        ("质量校验报告", "问题定位", "修复建议"),
        ("quality_reports", "quality_issues", "task_artifacts"),
    ),
    ModuleSpec(
        "检查输出与管理",
        "模型格式转换与输出模块",
        "支持地质环境模型在 GIS 平台、三维建模软件、BIM 平台和数值模拟软件之间进行格式转换与成果输出。",
        ("地质环境模型", "属性数据", "目标平台配置"),
        ("目标格式", "坐标输出规则", "属性保留规则", "成果目录"),
        ("GIS成果", "三维建模成果", "BIM成果", "数值模拟成果"),
        ("export_jobs", "task_artifacts", "model_versions"),
    ),
    ModuleSpec(
        "检查输出与管理",
        "自动化批量转换模块",
        "支持多批次、多目录、多格式数据的批量导入、参数复用、流程编排、任务队列、日志记录和失败重试。",
        ("批量目录", "文件清单", "规则模板", "流程配置"),
        ("批处理策略", "失败重试次数", "并发数量", "日志级别"),
        ("任务队列", "批处理日志", "失败重试记录"),
        ("batch_jobs", "conversion_tasks", "operation_logs"),
    ),
    ModuleSpec(
        "检查输出与管理",
        "可视化预览与对比检查模块",
        "提供转换前后数据的二维、三维和剖切预览，对坐标位置、空间范围、属性映射、模型尺度和关键边界进行对比检查。",
        ("转换前数据", "转换后数据", "对比规则", "关键边界"),
        ("预览模式", "剖切方向", "差异阈值", "对比指标"),
        ("二维预览", "三维预览", "剖切对比", "差异报告"),
        ("preview_sessions", "comparison_reports", "task_artifacts"),
    ),
    ModuleSpec(
        "检查输出与管理",
        "模型版本管理与成果追溯模块",
        "记录数据来源、转换参数、处理流程、质量检查结果、模型版本和输出成果信息，支持历史版本对比、成果回溯和归档。",
        ("模型成果", "转换参数", "质量报告", "来源数据"),
        ("版本号", "归档策略", "追溯字段", "对比版本"),
        ("模型版本", "追溯链路", "交付归档包"),
        ("model_versions", "lineage_records", "delivery_archives"),
    ),
]


MODULE_UI_PROFILES = {
    "数据预处理与质量清洗模块": {
        "layout": "audit",
        "overview": (("字段", "校验"), ("缺失", "识别"), ("异常", "清洗")),
        "workflow": ("导入样本", "字段体检", "规则清洗", "质量报告"),
        "checks": ("字段完整", "重复记录", "异常阈值", "单位一致"),
        "focus": ("字段规范化", "缺失值处理", "异常数据隔离"),
        "visual": "audit",
    },
    "坐标与基准统一模块": {
        "layout": "spatial",
        "overview": (("坐标", "统一"), ("高程", "基准"), ("里程", "校准")),
        "workflow": ("读取源基准", "设置目标系", "转换校验", "误差入库"),
        "checks": ("坐标系", "高程基准", "单位体系", "误差范围"),
        "focus": ("源坐标识别", "目标基准配置", "转换误差复核"),
        "visual": "coordinate",
    },
    "地质语义编码转换模块": {
        "layout": "matrix",
        "overview": (("字典", "管理"), ("编码", "映射"), ("冲突", "处理")),
        "workflow": ("载入字典", "编码匹配", "语义归一", "冲突复核"),
        "checks": ("编码覆盖", "同义归并", "冲突项", "来源追溯"),
        "focus": ("地层岩性字典", "项目编码映射", "冲突合并策略"),
        "visual": "semantic",
    },
    "转换规则模板库模块": {
        "layout": "library",
        "overview": (("模板", "复用"), ("规则", "编排"), ("版本", "管理")),
        "workflow": ("选择场景", "配置规则", "保存版本", "绑定项目"),
        "checks": ("字段映射", "坐标规则", "质量规则", "输出规则"),
        "focus": ("项目类型模板", "字段/属性规则", "输出与质检规则"),
        "visual": "template",
    },
    "钻孔数据三维化模块": {
        "layout": "spatial",
        "overview": (("钻孔", "定位"), ("分层", "建模"), ("三维", "对象")),
        "workflow": ("孔口定位", "深度分层", "三维拉伸", "属性挂接"),
        "checks": ("孔深范围", "层序连续", "水位记录", "空间定位"),
        "focus": ("钻孔柱状图", "岩性分层", "三维钻孔对象"),
        "visual": "borehole",
    },
    "钻孔属性结构化模块": {
        "layout": "audit",
        "overview": (("岩性", "结构化"), ("指标", "关联"), ("属性", "入库")),
        "workflow": ("字段解析", "属性分类", "主键关联", "完整性检查"),
        "checks": ("属性完整", "主键一致", "指标范围", "空间关联"),
        "focus": ("岩性类别", "地下水特征", "试验与工程指标"),
        "visual": "attribute_table",
    },
    "剖面与平面图转换模块": {
        "layout": "compare",
        "overview": (("图件", "定位"), ("线划", "矢量"), ("拓扑", "检查")),
        "workflow": ("图件导入", "控制点定位", "线划矢量化", "拓扑检查"),
        "checks": ("图层映射", "拓扑闭合", "控制点", "空间范围"),
        "focus": ("剖面图", "平面地质图", "解释线划"),
        "visual": "section_map",
    },
    "地质解释线重建模块": {
        "layout": "spatial",
        "overview": (("界线", "提取"), ("断层", "重建"), ("边界", "建模")),
        "workflow": ("提取线划", "断点识别", "边界重建", "质量评价"),
        "checks": ("断点数量", "连接容差", "接触关系", "边界连续"),
        "focus": ("地层界线", "断层线", "接触关系"),
        "visual": "boundary",
    },
    "栅格与矢量转换模块": {
        "layout": "compare",
        "overview": (("栅格", "解析"), ("边界", "提取"), ("矢量", "输出")),
        "workflow": ("影像/DEM读取", "阈值分割", "边界提取", "属性映射"),
        "checks": ("分辨率", "边界精度", "属性保留", "范围一致"),
        "focus": ("遥感影像/DEM", "地质图斑", "专题图层"),
        "visual": "raster_vector",
    },
    "点云数据转换模块": {
        "layout": "spatial",
        "overview": (("点云", "抽稀"), ("分类", "重采样"), ("模型", "转换")),
        "workflow": ("点云导入", "抽稀重采样", "分类过滤", "标准输出"),
        "checks": ("点密度", "分类覆盖", "噪声比例", "坐标范围"),
        "focus": ("激光扫描点云", "摄影测量点云", "监测点云"),
        "visual": "point_cloud",
    },
    "网格模型生成模块": {
        "layout": "model",
        "overview": (("边界", "约束"), ("网格", "生成"), ("质量", "评价")),
        "workflow": ("几何约束", "网格剖分", "质量优化", "模拟输出"),
        "checks": ("单元质量", "边界贴合", "拓扑连通", "畸变比例"),
        "focus": ("有限元网格", "有限差分网格", "计算分析网格"),
        "visual": "mesh",
    },
    "体素模型生成模块": {
        "layout": "model",
        "overview": (("范围", "裁剪"), ("体素", "生成"), ("属性", "填充")),
        "workflow": ("确定范围", "体素剖分", "属性插值", "模型入库"),
        "checks": ("体素尺寸", "空值比例", "边界裁剪", "属性覆盖"),
        "focus": ("规则体素单元", "空间属性表达", "范围索引"),
        "visual": "voxel",
    },
    "地质属性映射模块": {
        "layout": "matrix",
        "overview": (("属性", "映射"), ("插值", "计算"), ("来源", "追溯")),
        "workflow": ("选择属性", "匹配单元", "插值映射", "追溯记录"),
        "checks": ("字段覆盖", "插值方法", "搜索半径", "来源记录"),
        "focus": ("岩性/渗透系数", "强度与含水状态", "面体网格体素挂接"),
        "visual": "property_map",
    },
    "多尺度模型转换模块": {
        "layout": "compare",
        "overview": (("区域", "工程"), ("局部", "精细"), ("尺度", "转换")),
        "workflow": ("选择源尺度", "裁剪抽稀", "局部加密", "精度对比"),
        "checks": ("尺度目标", "抽稀率", "加密区", "精度保留"),
        "focus": ("区域尺度", "工程尺度", "局部精细尺度"),
        "visual": "multiscale",
    },
    "局部精细模型构建模块": {
        "layout": "model",
        "overview": (("重点", "区域"), ("局部", "加密"), ("精细", "构建")),
        "workflow": ("圈定重点区", "边界约束", "局部加密", "过渡检查"),
        "checks": ("加密级别", "过渡区", "边界贴合", "局部质量"),
        "focus": ("断层破碎带", "地下洞室/隧道", "边坡关键区"),
        "visual": "local_detail",
    },
    "模型质量校验模块": {
        "layout": "quality",
        "overview": (("几何", "闭合"), ("拓扑", "关系"), ("属性", "完整")),
        "workflow": ("载入模型", "执行规则", "定位问题", "生成报告"),
        "checks": ("几何闭合", "拓扑关系", "属性完整", "坐标精度"),
        "focus": ("模型缺陷识别", "异常定位", "修复建议"),
        "visual": "quality",
    },
    "模型格式转换与输出模块": {
        "layout": "export",
        "overview": (("GIS", "输出"), ("BIM", "对接"), ("模拟", "接口")),
        "workflow": ("选择目标平台", "格式映射", "成果输出", "共享交付"),
        "checks": ("目标格式", "坐标保留", "属性保留", "成果完整"),
        "focus": ("GIS平台", "三维/BIM平台", "数值模拟软件"),
        "visual": "export",
    },
    "自动化批量转换模块": {
        "layout": "batch",
        "overview": (("批量", "导入"), ("队列", "执行"), ("失败", "重试")),
        "workflow": ("扫描目录", "套用模板", "队列执行", "日志回收"),
        "checks": ("文件覆盖", "模板匹配", "失败重试", "日志完整"),
        "focus": ("批次目录", "流程编排", "任务队列"),
        "visual": "batch",
    },
    "可视化预览与对比检查模块": {
        "layout": "compare",
        "overview": (("二维", "预览"), ("三维", "剖切"), ("差异", "对比")),
        "workflow": ("加载前后成果", "同步视图", "剖切对比", "差异定位"),
        "checks": ("坐标位置", "空间范围", "属性映射", "关键边界"),
        "focus": ("转换前后对比", "二维/三维预览", "剖切检查"),
        "visual": "comparison",
    },
    "模型版本管理与成果追溯模块": {
        "layout": "lineage",
        "overview": (("版本", "归档"), ("参数", "追溯"), ("成果", "交付")),
        "workflow": ("采集来源", "记录参数", "归档成果", "版本对比"),
        "checks": ("来源完整", "参数可追溯", "版本差异", "交付清单"),
        "focus": ("数据来源", "转换参数", "质量报告与成果"),
        "visual": "lineage",
    },
}


class BackendClient:
    """Frontend-facing API placeholder. Replace these methods with real MySQL-backed services."""

    def __init__(self) -> None:
        self.mysql_config = {
            "host": "127.0.0.1",
            "port": 3306,
            "database": "geo_model_conversion",
            "user": "geo_app",
        }

    def build_task_payload(self, module: ModuleSpec, files: list[str], params: dict[str, str]) -> dict[str, object]:
        return {
            "module": module.name,
            "group": module.group,
            "input_files": files,
            "parameters": params,
            "mysql_tables": list(module.mysql_tables),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "backend_endpoints": BACKEND_ENDPOINTS,
        }

    def preview_sql_tables(self, module: ModuleSpec) -> str:
        tables = "\n".join(f"  - {table}" for table in module.mysql_tables)
        return (
            "MySQL 预留表：\n"
            f"{tables}\n\n"
            "建议后端分层：\n"
            "  - controller: 接收前端任务请求\n"
            "  - service: 调用转换算法与质量校验\n"
            "  - repository: 读写 MySQL 表\n"
            "  - artifact storage: 保存模型、报告、导出文件路径\n"
        )


class GeoConversionApp(tk.Tk):
    BG = "#eef2f4"
    PANEL = "#ffffff"
    SOFT = "#f6f8f9"
    TEXT = "#203039"
    MUTED = "#697b82"
    BORDER = "#d7e0e3"
    NAVY = "#17313a"
    TEAL = "#14736e"
    AMBER = "#bb7a20"
    RED = "#b34d43"

    def __init__(self) -> None:
        super().__init__()
        validate_modules()

        self.backend = BackendClient()
        self.active_module = FEATURE_MODULES[0]
        self.selected_files: list[str] = []
        self.param_vars: dict[str, tk.StringVar] = {}
        self.menu_buttons: list[tk.Button] = []

        self.search_var = tk.StringVar(value="")
        self.project_var = tk.StringVar(value="默认项目")
        self.module_title = tk.StringVar()
        self.module_group = tk.StringVar()
        self.module_desc = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.mysql_var = tk.StringVar()

        self.title(APP_TITLE)
        self.geometry("1440x900")
        self.minsize(1180, 740)
        self.configure(bg=self.BG)

        self._configure_fonts()
        self._configure_styles()
        self._build_layout()
        self._select_module(self.active_module)

    def _configure_fonts(self) -> None:
        preferred = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Arial"]
        available = set(tkfont.families(self))
        self.font_family = next((item for item in preferred if item in available), "Arial")
        self.option_add("*Font", f"{{{self.font_family}}} 10")
        self.brand_font = tkfont.Font(self, family=self.font_family, size=17, weight="bold")
        self.title_font = tkfont.Font(self, family=self.font_family, size=18, weight="bold")
        self.section_font = tkfont.Font(self, family=self.font_family, size=11, weight="bold")
        self.small_font = tkfont.Font(self, family=self.font_family, size=9)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("Soft.TFrame", background=self.SOFT)
        style.configure("Primary.TButton", background=self.TEAL, foreground="#ffffff", borderwidth=0, padding=(14, 8))
        style.map("Primary.TButton", background=[("active", "#0f5d59"), ("disabled", "#b7c5c8")])
        style.configure("Tool.TButton", padding=(10, 6))
        style.configure("Work.TNotebook", background=self.PANEL, borderwidth=0)
        style.configure("Work.TNotebook.Tab", padding=(14, 8), background="#e7edef", foreground=self.MUTED)
        style.map("Work.TNotebook.Tab", background=[("selected", self.PANEL)], foreground=[("selected", self.TEAL)])

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        body = ttk.Frame(self, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=320, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_sidebar(body).grid(row=0, column=0, sticky="nsew")
        self._build_workspace(body).grid(row=0, column=1, sticky="nsew", padx=(14, 14), pady=(14, 12))
        self._build_status_bar()

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=self.NAVY, padx=20, pady=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        tk.Label(header, text="GEO", bg="#e0a33b", fg=self.NAVY, font=(self.font_family, 11, "bold"), padx=11, pady=8).grid(
            row=0, column=0, rowspan=2, sticky="w", padx=(0, 12)
        )
        tk.Label(header, text=APP_TITLE, bg=self.NAVY, fg="#ffffff", font=self.brand_font, anchor="w").grid(
            row=0, column=1, sticky="ew"
        )
        tk.Label(
            header,
            text="坐标基准统一 · 模态转换 · 三维建模 · 质量校验 · 成果追溯",
            bg=self.NAVY,
            fg="#bfd0d4",
            font=self.small_font,
            anchor="w",
        ).grid(row=1, column=1, sticky="ew", pady=(3, 0))
        tk.Label(header, text="MySQL 后端接口预留", bg="#244852", fg="#dce8eb", padx=12, pady=7).grid(
            row=0, column=2, rowspan=2, sticky="e"
        )

    def _build_sidebar(self, parent: tk.Widget) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Panel.TFrame")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        tk.Label(panel, text="功能模块", bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(16, 6)
        )
        search = tk.Entry(panel, textvariable=self.search_var, relief="flat", bg="#eef3f4", fg=self.TEXT)
        search.grid(row=1, column=0, sticky="ew", padx=16, ipady=8)
        search.insert(0, "")
        self.search_var.trace_add("write", lambda *_args: self._populate_menu())

        summary = tk.Frame(panel, bg="#f6faf9", highlightbackground=self.BORDER, highlightthickness=1)
        summary.grid(row=2, column=0, sticky="ew", padx=16, pady=12)
        summary.columnconfigure((0, 1), weight=1)
        self._metric(summary, "模块", "20").grid(row=0, column=0, sticky="ew")
        self._metric(summary, "分组", "4").grid(row=0, column=1, sticky="ew")

        canvas = tk.Canvas(panel, bg=self.PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=3, column=0, sticky="nsew", padx=(10, 0), pady=(0, 12))
        scrollbar.grid(row=3, column=1, sticky="ns", pady=(0, 12))
        self.menu_content = tk.Frame(canvas, bg=self.PANEL)
        window = canvas.create_window((0, 0), window=self.menu_content, anchor="nw")
        self.menu_content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self._populate_menu()
        return panel

    def _metric(self, parent: tk.Widget, label: str, value: str) -> tk.Frame:
        frame = tk.Frame(parent, bg="#f6faf9", padx=8, pady=8)
        tk.Label(frame, text=value, bg="#f6faf9", fg=self.TEAL, font=(self.font_family, 16, "bold")).pack()
        tk.Label(frame, text=label, bg="#f6faf9", fg=self.MUTED, font=self.small_font).pack()
        return frame

    def _populate_menu(self) -> None:
        for child in self.menu_content.winfo_children():
            child.destroy()
        self.menu_buttons.clear()
        query = self.search_var.get().strip().lower()
        row = 0
        for group in GROUP_ORDER:
            modules = [item for item in FEATURE_MODULES if item.group == group and query in item.name.lower()]
            if not modules:
                continue
            tk.Label(self.menu_content, text=group, bg=self.PANEL, fg="#788a90", font=self.small_font, anchor="w").grid(
                row=row, column=0, sticky="ew", padx=10, pady=(10 if row else 2, 5)
            )
            row += 1
            for module in modules:
                button = tk.Button(
                    self.menu_content,
                    text=module.name.removesuffix("模块"),
                    anchor="w",
                    justify="left",
                    wraplength=250,
                    relief="flat",
                    bd=0,
                    padx=12,
                    pady=8,
                    bg=self.PANEL,
                    fg=self.TEXT,
                    activebackground="#e2f0ef",
                    cursor="hand2",
                    command=lambda selected=module: self._select_module(selected),
                )
                button.module_name = module.name  # type: ignore[attr-defined]
                button.grid(row=row, column=0, sticky="ew", padx=(2, 8), pady=1)
                self.menu_buttons.append(button)
                row += 1
        self._refresh_menu()

    def _build_workspace(self, parent: tk.Widget) -> ttk.Frame:
        panel = ttk.Frame(parent, style="App.TFrame")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        hero = tk.Frame(panel, bg="#132d35", highlightbackground="#0d2229", highlightthickness=1)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=0)

        title_area = tk.Frame(hero, bg="#132d35", padx=20, pady=18)
        title_area.grid(row=0, column=0, sticky="ew")
        title_area.columnconfigure(0, weight=1)
        tk.Label(title_area, textvariable=self.module_group, bg="#132d35", fg="#8fd1ca", font=self.small_font, anchor="w").grid(
            row=0, column=0, sticky="ew"
        )
        tk.Label(title_area, textvariable=self.module_title, bg="#132d35", fg="#ffffff", font=self.title_font, anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(5, 0)
        )
        tk.Label(
            title_area,
            textvariable=self.module_desc,
            bg="#132d35",
            fg="#c6d6d9",
            justify="left",
            anchor="w",
            wraplength=820,
        ).grid(row=2, column=0, sticky="ew", pady=(9, 0))

        project = tk.Frame(hero, bg="#173842", padx=16, pady=14)
        project.grid(row=0, column=1, sticky="nsew")
        tk.Label(project, text="当前项目", bg="#173842", fg="#a7bec3", font=self.small_font).grid(row=0, column=0, sticky="w")
        ttk.Entry(project, textvariable=self.project_var, width=24).grid(row=1, column=0, sticky="ew", pady=(7, 13))
        self._hero_metric(project, "接口", "MySQL").grid(row=2, column=0, sticky="ew")
        self._hero_metric(project, "状态", "原型就绪").grid(row=3, column=0, sticky="ew", pady=(8, 0))

        notebook = ttk.Notebook(panel, style="Work.TNotebook")
        notebook.grid(row=1, column=0, sticky="nsew")
        self.input_tab = tk.Frame(notebook, bg=self.PANEL)
        self.params_tab = tk.Frame(notebook, bg=self.PANEL)
        self.preview_tab = tk.Frame(notebook, bg=self.PANEL)
        self.task_tab = tk.Frame(notebook, bg=self.PANEL)
        self.backend_tab = tk.Frame(notebook, bg=self.PANEL)
        notebook.add(self.input_tab, text="数据输入")
        notebook.add(self.params_tab, text="参数配置")
        notebook.add(self.preview_tab, text="预览检查")
        notebook.add(self.task_tab, text="任务与追溯")
        notebook.add(self.backend_tab, text="后端接口")
        return panel

    def _render_tabs(self) -> None:
        for tab in (self.input_tab, self.params_tab, self.preview_tab, self.task_tab, self.backend_tab):
            for child in tab.winfo_children():
                child.destroy()
        self._render_input_tab()
        self._render_params_tab()
        self._render_preview_tab()
        self._render_task_tab()
        self._render_backend_tab()

    def _render_input_tab(self) -> None:
        tab = self.input_tab
        tab.columnconfigure(0, weight=2)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(2, weight=1)
        self._module_overview(tab).grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 10))
        self._section_title(tab, "数据接入工作台", "按模块要求导入源数据，后端接入后写入 datasets、task_artifacts 与对应业务表。").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10)
        )
        if self._profile()["layout"] in {"library", "matrix", "compare", "quality", "export", "batch", "lineage"}:
            self._render_special_input_panel(tab)
            return

        left = self._card(tab)
        left.grid(row=2, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        left.columnconfigure(0, weight=1)
        tk.Label(left, text="输入清单", bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(16, 8)
        )
        for index, item in enumerate(self.active_module.inputs, start=1):
            row = tk.Frame(left, bg="#f7fafb", highlightbackground="#dfe8ea", highlightthickness=1)
            row.grid(row=index, column=0, sticky="ew", padx=18, pady=5)
            row.columnconfigure(1, weight=1)
            tk.Label(row, text=f"{index:02d}", bg="#dcefed", fg=self.TEAL, font=(self.font_family, 10, "bold"), padx=10, pady=8).grid(
                row=0, column=0, sticky="nsw"
            )
            tk.Label(row, text=item, bg="#f7fafb", fg=self.TEXT, anchor="w", padx=12).grid(
                row=0, column=1, sticky="ew"
            )
        ttk.Button(left, text="添加文件", style="Primary.TButton", command=self._choose_files).grid(
            row=9, column=0, sticky="w", padx=18, pady=(16, 16)
        )

        right = self._card(tab)
        right.grid(row=2, column=1, sticky="nsew", padx=(8, 16), pady=(0, 16))
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="数据队列", bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(16, 8)
        )
        self.file_list = tk.Listbox(right, relief="flat", bg="#f5f8f9", fg=self.TEXT, height=12, selectbackground="#dcefed")
        self.file_list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
        tk.Label(
            right,
            text="支持后续接入文件指纹、数据类型识别、坐标基准检查与入库状态。",
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.small_font,
            wraplength=260,
            justify="left",
        ).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        right.rowconfigure(1, weight=1)
        self._refresh_file_list()

    def _render_params_tab(self) -> None:
        tab = self.params_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self._workflow_strip(tab).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        self._section_title(tab, "参数配置中心", "这些字段会随任务提交给后端，后端用 MySQL 保存参数、过程、质量结果和成果追溯。").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 8)
        )
        form = self._card(tab)
        form.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        form.columnconfigure(1, weight=1)
        self.param_vars.clear()
        defaults = {
            "目标坐标系": "CGCS2000 / 工程坐标",
            "目标高程基准": "1985 国家高程基准",
            "转换精度": "标准",
            "目标格式": "GeoJSON / VTK / IFC / CSV",
            "日志级别": "INFO",
        }
        for row, name in enumerate(self.active_module.parameters):
            tk.Label(form, text=name, bg=self.PANEL, fg=self.TEXT, anchor="w").grid(row=row, column=0, sticky="w", padx=18, pady=11)
            var = tk.StringVar(value=defaults.get(name, "默认"))
            self.param_vars[name] = var
            ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky="ew", padx=(8, 18), pady=8)
        ttk.Button(form, text="保存为规则模板", style="Tool.TButton", command=self._save_template_stub).grid(
            row=len(self.active_module.parameters), column=1, sticky="e", padx=18, pady=(16, 18)
        )

    def _render_preview_tab(self) -> None:
        tab = self.preview_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self._quality_strip(tab).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        self._section_title(tab, "空间预览与质量检查", "前端提供统一预览位，后续可接二维地图、三维场景、剖切对比、质量报告与差异定位接口。").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 8)
        )
        canvas = tk.Canvas(tab, bg="#0f262e", highlightthickness=1, highlightbackground="#0b1d23")
        canvas.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        canvas.bind("<Configure>", lambda _e, c=canvas: self._draw_preview(c))

    def _render_task_tab(self) -> None:
        tab = self.task_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self._workflow_strip(tab).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        self._section_title(tab, "任务、版本与成果追溯", "覆盖批量转换、日志、失败重试、版本对比、成果归档等管理功能。").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 8)
        )
        box = self._card(tab)
        box.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        actions = tk.Frame(box, bg=self.PANEL)
        actions.grid(row=0, column=0, sticky="ew", padx=18, pady=14)
        ttk.Button(actions, text="生成任务请求", style="Primary.TButton", command=self._generate_task_payload).pack(side="left")
        ttk.Button(actions, text="预留执行接口", style="Tool.TButton", command=self._run_stub).pack(side="left", padx=8)
        ttk.Button(actions, text="归档版本", style="Tool.TButton", command=self._archive_stub).pack(side="left")
        self.task_text = tk.Text(box, relief="flat", bg="#f5f8f9", fg=self.TEXT, height=16, wrap="word")
        self.task_text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.task_text.insert(
            "1.0",
            "任务状态：待配置\n\n"
            "预留能力：\n"
            "- 多批次、多目录、多格式导入\n"
            "- 参数复用与流程编排\n"
            "- 任务队列、运行日志、失败重试\n"
            "- 质量报告、模型版本、成果归档\n",
        )

    def _render_backend_tab(self) -> None:
        tab = self.backend_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.mysql_var.set(
            f"{self.backend.mysql_config['host']}:{self.backend.mysql_config['port']} / "
            f"{self.backend.mysql_config['database']} / {self.backend.mysql_config['user']}"
        )
        self._backend_strip(tab).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        self._section_title(tab, "MySQL 后端接口预留", "前端不直接处理模型算法，只组装请求、显示状态、接收结果；后端使用 MySQL 持久化项目、数据、任务、质量报告和版本追溯。").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 8)
        )
        text = tk.Text(tab, relief="flat", bg="#f5f8f9", fg=self.TEXT, wrap="word")
        text.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        endpoint_lines = "\n".join(f"- {name}: {value}" for name, value in BACKEND_ENDPOINTS.items())
        text.insert(
            "1.0",
            f"MySQL 连接占位：{self.mysql_var.get()}\n\n"
            f"{self.backend.preview_sql_tables(self.active_module)}\n\n"
            "接口占位：\n"
            f"{endpoint_lines}\n\n"
            "建议核心表：projects, datasets, conversion_tasks, task_parameters, task_artifacts, "
            "quality_reports, quality_issues, model_versions, lineage_records, operation_logs。\n",
        )

    def _section_title(self, parent: tk.Widget, title: str, subtitle: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.columnconfigure(0, weight=1)
        tk.Label(frame, text=title, bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(
            row=0, column=0, sticky="ew"
        )
        tk.Label(frame, text=subtitle, bg=self.PANEL, fg=self.MUTED, font=self.small_font, anchor="w", wraplength=980).grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )
        return frame

    def _profile(self) -> dict[str, object]:
        return MODULE_UI_PROFILES[self.active_module.name]

    def _render_special_input_panel(self, tab: tk.Widget) -> None:
        profile = self._profile()
        layout = profile["layout"]
        tab.rowconfigure(3, weight=1)
        board = tk.Frame(tab, bg=self.PANEL)
        board.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10))
        board.columnconfigure((0, 1, 2), weight=1)

        focus_items = profile["focus"]
        if layout == "compare":
            titles = ("源资料 / 转换前", "目标成果 / 转换后", "差异检查")
        elif layout == "batch":
            titles = ("批次目录", "流程模板", "任务队列")
        elif layout == "lineage":
            titles = ("来源链路", "参数快照", "成果归档")
        elif layout == "export":
            titles = ("目标平台", "格式映射", "交付包")
        elif layout == "quality":
            titles = ("检查规则", "问题定位", "修复建议")
        elif layout == "library":
            titles = ("模板分类", "规则编排", "版本发布")
        else:
            titles = ("属性源", "映射关系", "追溯结果")

        for col, title in enumerate(titles):
            card = tk.Frame(board, bg="#f6faf9", highlightbackground="#d8e4e6", highlightthickness=1, padx=14, pady=14)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
            tk.Label(card, text=title, bg="#f6faf9", fg=self.TEAL, font=(self.font_family, 11, "bold"), anchor="w").pack(anchor="w")
            tk.Label(
                card,
                text=focus_items[col],
                bg="#f6faf9",
                fg=self.TEXT,
                font=self.small_font,
                anchor="w",
                justify="left",
                wraplength=260,
            ).pack(anchor="w", pady=(9, 0))
            tk.Label(card, text="接口待接入", bg="#eef4f4", fg=self.MUTED, font=self.small_font, padx=8, pady=3).pack(anchor="w", pady=(12, 0))

        queue = self._card(tab)
        queue.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 16))
        queue.columnconfigure(0, weight=1)
        queue.rowconfigure(1, weight=1)
        queue_title = {
            "batch": "批量任务队列",
            "compare": "对比数据队列",
            "lineage": "追溯资料队列",
            "export": "待输出成果队列",
            "quality": "待检查模型队列",
            "library": "模板与规则文件",
        }.get(str(layout), "业务数据队列")
        tk.Label(queue, text=queue_title, bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(16, 8)
        )
        self.file_list = tk.Listbox(queue, relief="flat", bg="#f5f8f9", fg=self.TEXT, height=8, selectbackground="#dcefed")
        self.file_list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
        actions = tk.Frame(queue, bg=self.PANEL)
        actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        ttk.Button(actions, text="添加文件", style="Primary.TButton", command=self._choose_files).pack(side="left")
        ttk.Button(actions, text="生成任务请求", style="Tool.TButton", command=self._generate_task_payload).pack(side="left", padx=8)
        self._refresh_file_list()

    def _hero_metric(self, parent: tk.Widget, label: str, value: str) -> tk.Frame:
        frame = tk.Frame(parent, bg="#214a53", padx=12, pady=8)
        frame.columnconfigure(0, weight=1)
        tk.Label(frame, text=label, bg="#214a53", fg="#a9c2c7", font=self.small_font, anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(frame, text=value, bg="#214a53", fg="#ffffff", font=(self.font_family, 11, "bold"), anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(2, 0)
        )
        return frame

    def _module_overview(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.columnconfigure((0, 1, 2), weight=1)
        overview = self._profile()["overview"]
        captions = ("核心输入与场景", "关键处理动作", "成果与接口落点")
        for col, ((title, value), caption) in enumerate(zip(overview, captions)):
            card = tk.Frame(frame, bg="#f6faf9", highlightbackground="#d8e4e6", highlightthickness=1, padx=14, pady=12)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
            tk.Label(card, text=title, bg="#f6faf9", fg=self.MUTED, font=self.small_font, anchor="w").pack(anchor="w")
            tk.Label(card, text=value, bg="#f6faf9", fg=self.TEAL, font=(self.font_family, 20, "bold"), anchor="w").pack(anchor="w")
            tk.Label(card, text=caption, bg="#f6faf9", fg=self.TEXT, font=self.small_font, anchor="w").pack(anchor="w")
        return frame

    def _workflow_strip(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.columnconfigure((0, 1, 2, 3), weight=1)
        steps = self._profile()["workflow"]
        for col, title in enumerate(steps):
            card = tk.Frame(frame, bg="#f6faf9", highlightbackground="#d8e4e6", highlightthickness=1, padx=12, pady=10)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
            tk.Label(card, text=f"0{col + 1}", bg="#f6faf9", fg=self.TEAL, font=(self.font_family, 13, "bold")).pack(anchor="w")
            tk.Label(card, text=title, bg="#f6faf9", fg=self.TEXT, font=(self.font_family, 10, "bold")).pack(anchor="w", pady=(2, 0))
            tk.Label(card, text="接口预留", bg="#f6faf9", fg=self.MUTED, font=self.small_font).pack(anchor="w")
        return frame

    def _quality_strip(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.columnconfigure((0, 1, 2, 3), weight=1)
        checks = self._profile()["checks"]
        for col, title in enumerate(checks):
            card = tk.Frame(frame, bg="#f6faf9", highlightbackground="#d8e4e6", highlightthickness=1, padx=12, pady=10)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
            tk.Label(card, text="●", bg="#f6faf9", fg=self.AMBER, font=(self.font_family, 13, "bold")).pack(anchor="w")
            tk.Label(card, text=title, bg="#f6faf9", fg=self.TEXT, font=(self.font_family, 10, "bold")).pack(anchor="w")
            tk.Label(card, text="待后端计算", bg="#f6faf9", fg=self.MUTED, font=self.small_font).pack(anchor="w")
        return frame

    def _backend_strip(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.columnconfigure((0, 1, 2), weight=1)
        items = (
            ("服务层", "FastAPI / REST 预留"),
            ("数据库", self.backend.mysql_config["database"]),
            ("追溯链", "数据源 · 参数 · 任务 · 成果"),
        )
        for col, (title, caption) in enumerate(items):
            card = tk.Frame(frame, bg="#f6faf9", highlightbackground="#d8e4e6", highlightthickness=1, padx=14, pady=12)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
            tk.Label(card, text=title, bg="#f6faf9", fg=self.TEAL, font=(self.font_family, 11, "bold")).pack(anchor="w")
            tk.Label(card, text=caption, bg="#f6faf9", fg=self.TEXT, font=self.small_font).pack(anchor="w", pady=(5, 0))
        return frame

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(parent, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)

    def _choose_files(self) -> None:
        files = list(filedialog.askopenfilenames(title="选择源数据文件"))
        if files:
            self.selected_files.extend(files)
            self._refresh_file_list()
            self.status_var.set(f"已添加 {len(files)} 个文件")

    def _refresh_file_list(self) -> None:
        if not hasattr(self, "file_list"):
            return
        self.file_list.delete(0, tk.END)
        if not self.selected_files:
            self.file_list.insert(tk.END, "尚未选择文件")
            return
        for path in self.selected_files:
            self.file_list.insert(tk.END, path)

    def _save_template_stub(self) -> None:
        self.status_var.set(f"已预留模板保存接口：{BACKEND_ENDPOINTS['save_template']}")

    def _run_stub(self) -> None:
        self.status_var.set(f"已预留任务执行接口：{BACKEND_ENDPOINTS['run_task']}")
        self.task_text.insert(tk.END, "\n接口占位：后端接入后将提交任务并轮询运行状态。\n")

    def _archive_stub(self) -> None:
        self.status_var.set(f"已预留版本归档接口：{BACKEND_ENDPOINTS['version_archive']}")
        self.task_text.insert(tk.END, "\n接口占位：后端接入后将写入 model_versions 与 lineage_records。\n")

    def _generate_task_payload(self) -> None:
        params = {name: var.get() for name, var in self.param_vars.items()}
        payload = self.backend.build_task_payload(self.active_module, self.selected_files, params)
        self.task_text.delete("1.0", tk.END)
        self.task_text.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2))
        self.status_var.set(f"已生成任务请求：{BACKEND_ENDPOINTS['create_task']}")

    def _draw_preview(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 360)
        for x in range(30, width, 44):
            canvas.create_line(x, 0, x, height, fill="#173840")
        for y in range(30, height, 44):
            canvas.create_line(0, y, width, y, fill="#173840")
        cx, cy = width / 2, height / 2
        canvas.create_rectangle(24, 24, width - 24, height - 24, outline="#2a5660", width=2)
        canvas.create_text(44, 44, text="MODEL PREVIEW", fill="#7db8b2", anchor="w", font=(self.font_family, 10, "bold"))
        canvas.create_text(width - 44, 44, text="2D / 3D / SECTION", fill="#8fa7ad", anchor="e", font=(self.font_family, 9))
        visual = self._profile()["visual"]
        if visual in {"audit", "attribute_table", "semantic"}:
            for index, length in enumerate((260, 210, 300, 180)):
                y = cy - 90 + index * 48
                canvas.create_rectangle(cx - 180, y, cx + 180, y + 30, fill="#173840", outline="#3d6870")
                canvas.create_rectangle(cx - 170, y + 9, cx - 170 + length, y + 20, fill="#45b5a9", outline="")
                canvas.create_oval(cx + 150, y + 8, cx + 164, y + 22, fill="#e1a33e", outline="")
            if visual == "semantic":
                for x in (cx - 50, cx + 70):
                    canvas.create_line(x, cy - 122, x + 58, cy + 92, fill="#7db8b2", dash=(4, 3))
        elif visual in {"coordinate", "section_map", "raster_vector"}:
            canvas.create_rectangle(cx - 245, cy - 120, cx + 245, cy + 120, fill="#173840", outline="#3d6870")
            for index in range(6):
                y = cy - 100 + index * 40
                canvas.create_line(cx - 230, y, cx + 230, y + (18 if index % 2 else -12), fill="#567d85")
            canvas.create_line(cx - 200, cy + 70, cx + 205, cy - 55, fill="#45b5a9", width=3)
            canvas.create_line(cx - 170, cy - 75, cx + 180, cy + 62, fill="#d99a3f", width=2)
            if visual == "coordinate":
                canvas.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="#e06155", outline="")
                canvas.create_text(cx + 18, cy - 18, text="基准转换点", fill="#c6d6d9", anchor="w")
            else:
                canvas.create_rectangle(cx - 90, cy - 50, cx + 95, cy + 52, outline="#e06155", dash=(5, 3), width=2)
        elif visual in {"borehole", "boundary"}:
            for index, color in enumerate(("#d6bb6f", "#58aaa3", "#b98265", "#7399a7")):
                y = cy - 100 + index * 46
                canvas.create_polygon(cx - 220, y, cx + 90, y - 22, cx + 220, y + 12, cx - 150, y + 34, fill=color, outline="#173840")
            for x in (cx - 120, cx - 40, cx + 55, cx + 135):
                canvas.create_line(x, cy - 145, x, cy + 120, fill="#e06155", width=3)
                canvas.create_oval(x - 5, cy - 150, x + 5, cy - 140, fill="#e06155", outline="")
            if visual == "boundary":
                canvas.create_line(cx - 205, cy - 5, cx - 80, cy + 30, cx + 60, cy - 18, cx + 210, cy + 16, fill="#ffffff", width=2, smooth=True)
        elif visual == "point_cloud":
            for i in range(80):
                x = cx - 220 + (i * 37) % 440
                y = cy - 110 + (i * 53) % 220
                color = "#45b5a9" if i % 3 else "#d99a3f"
                canvas.create_oval(x, y, x + 4, y + 4, fill=color, outline="")
            canvas.create_rectangle(cx - 180, cy - 80, cx + 180, cy + 80, outline="#7db8b2", dash=(4, 3))
        elif visual in {"mesh", "voxel", "local_detail", "property_map", "multiscale"}:
            size = 42
            for row in range(5):
                for col in range(7):
                    x = cx - 145 + col * size
                    y = cy - 110 + row * size
                    fill = "#45b5a9" if (row + col) % 3 else "#d99a3f"
                    if visual == "local_detail" and 2 <= row <= 3 and 2 <= col <= 4:
                        fill = "#e06155"
                    canvas.create_rectangle(x, y, x + size - 5, y + size - 5, fill=fill, outline="#173840")
            if visual == "multiscale":
                canvas.create_rectangle(cx - 165, cy - 130, cx + 165, cy + 130, outline="#c6d6d9", dash=(6, 4), width=2)
            if visual == "property_map":
                canvas.create_text(cx, cy + 132, text="属性映射热区 / 来源可追溯", fill="#c6d6d9")
        elif visual in {"template", "batch", "lineage", "export", "quality", "comparison"}:
            canvas.create_rectangle(cx - 250, cy - 110, cx - 30, cy + 100, fill="#173840", outline="#3d6870")
            canvas.create_rectangle(cx + 30, cy - 110, cx + 250, cy + 100, fill="#173840", outline="#3d6870")
            for offset, color in ((-65, "#45b5a9"), (-20, "#8aa9a6"), (25, "#d99a3f")):
                canvas.create_rectangle(cx - 220, cy + offset, cx - 80, cy + offset + 18, fill=color, outline="")
                canvas.create_rectangle(cx + 65, cy + offset, cx + 220, cy + offset + 18, fill=color, outline="")
            if visual == "lineage":
                canvas.create_line(cx - 30, cy - 70, cx + 30, cy - 70, fill="#7db8b2", arrow=tk.LAST)
                canvas.create_line(cx - 30, cy, cx + 30, cy, fill="#7db8b2", arrow=tk.LAST)
                canvas.create_line(cx - 30, cy + 70, cx + 30, cy + 70, fill="#7db8b2", arrow=tk.LAST)
            if visual == "quality":
                for y in (cy - 65, cy - 20, cy + 25):
                    canvas.create_oval(cx + 205, y - 5, cx + 215, y + 5, fill="#e06155", outline="")
            canvas.create_text(cx, cy + 135, text="任务流 / 对比 / 输出 / 追溯", fill="#a5bdc2", font=(self.font_family, 10))
        else:
            canvas.create_text(cx, cy, text="模块预览", fill="#c6d6d9", font=(self.font_family, 18, "bold"))
        canvas.create_text(cx, height - 42, text=f"{self.active_module.name}：预览组件占位，后续接入二维/三维渲染结果", fill="#a5bdc2")

    def _select_module(self, module: ModuleSpec) -> None:
        self.active_module = module
        self.module_group.set(f"{module.group} / 功能工作区")
        self.module_title.set(module.name)
        self.module_desc.set(module.description)
        self.status_var.set(f"当前模块：{module.name}")
        self._refresh_menu()
        self._render_tabs()

    def _refresh_menu(self) -> None:
        active_name = self.active_module.name
        for button in self.menu_buttons:
            active = getattr(button, "module_name", "") == active_name
            button.configure(
                bg="#dcefed" if active else self.PANEL,
                fg=self.TEAL if active else self.TEXT,
                font=(self.font_family, 10, "bold" if active else "normal"),
            )

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self, bg="#dce5e7", height=30)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(0, weight=1)
        tk.Label(bar, textvariable=self.status_var, bg="#dce5e7", fg="#51666c", anchor="w", padx=14).grid(
            row=0, column=0, sticky="nsew"
        )
        tk.Label(bar, text="本地前端原型 · 后端 MySQL 接口待接入", bg="#dce5e7", fg=self.TEAL, padx=14).grid(
            row=0, column=1, sticky="e"
        )


def validate_modules() -> None:
    names = [item.name for item in FEATURE_MODULES]
    groups = {item.group for item in FEATURE_MODULES}
    missing_groups = sorted(groups - set(GROUP_ORDER))
    if len(FEATURE_MODULES) != 20:
        raise ValueError(f"功能模块数量应为 20 个，当前为 {len(FEATURE_MODULES)} 个。")
    if len(names) != len(set(names)):
        raise ValueError("功能模块名称存在重复。")
    if missing_groups:
        raise ValueError(f"存在未登记的分组：{', '.join(missing_groups)}")


def main() -> int:
    if "--check" in sys.argv:
        validate_modules()
        print("前端配置检查通过：20 个功能模块，4 个功能分组，MySQL 后端接口占位已定义。")
        return 0
    app = GeoConversionApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
