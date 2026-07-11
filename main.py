from __future__ import annotations

import json
import math
import sys
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
    """仿照“预测结果汇总研判”界面重新设计的 Tkinter 前端。"""

    BG = "#eef2f1"
    PANEL = "#ffffff"
    SOFT = "#f6f8f7"
    TEXT = "#10231f"
    MUTED = "#66756f"
    BORDER = "#d6dfdc"
    SIDEBAR = "#142821"
    SIDEBAR_ITEM = "#1d342d"
    SIDEBAR_HOVER = "#244039"
    TEAL = "#0b8d80"
    TEAL_DARK = "#087166"
    TEAL_SOFT = "#e5f5f1"
    BLUE = "#2f6ed0"
    ORANGE = "#c9770e"
    PURPLE = "#654bd5"
    GREEN = "#16934f"
    RED = "#d34234"
    AMBER = "#d88213"

    PAGE_NAMES = ("工作台", "参数配置", "预览检查", "任务与追溯", "后端接口")

    def __init__(self) -> None:
        super().__init__()
        validate_modules()

        self.backend = BackendClient()
        self.active_module = FEATURE_MODULES[0]
        self.selected_files: list[str] = []
        self.param_values: dict[str, str] = {}
        self.param_vars: dict[str, tk.StringVar] = {}
        self.menu_buttons: list[tk.Button] = []
        self.page_buttons: dict[str, tk.Button] = {}
        self.current_page = "工作台"
        self.run_completed = False
        self.task_payload_text = (
            "任务状态：待配置\n\n"
            "预留能力：\n"
            "- 多批次、多目录、多格式导入\n"
            "- 参数复用与流程编排\n"
            "- 任务队列、运行日志、失败重试\n"
            "- 质量报告、模型版本、成果归档\n"
        )
        self.logs: list[str] = []

        self.search_var = tk.StringVar(value="")
        self.project_var = tk.StringVar(value="默认项目")
        self.module_title = tk.StringVar()
        self.module_desc = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.run_status_var = tk.StringVar(value="待处理")
        self.mysql_var = tk.StringVar()

        self.title(APP_TITLE)
        self.geometry("1540x900")
        self.minsize(1260, 760)
        self.configure(bg=self.BG)

        self._configure_fonts()
        self._configure_styles()
        self._build_layout()
        self._select_module(self.active_module, keep_page=True)
        self.after(150, self._maximize_if_possible)

    def _maximize_if_possible(self) -> None:
        try:
            if sys.platform.startswith("win"):
                self.state("zoomed")
        except tk.TclError:
            pass

    def _configure_fonts(self) -> None:
        preferred = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial"]
        available = set(tkfont.families(self))
        self.font_family = next((name for name in preferred if name in available), "Arial")
        self.option_add("*Font", f"{{{self.font_family}}} 10")
        self.brand_font = tkfont.Font(self, family=self.font_family, size=17, weight="bold")
        self.hero_font = tkfont.Font(self, family=self.font_family, size=16, weight="bold")
        self.section_font = tkfont.Font(self, family=self.font_family, size=11, weight="bold")
        self.small_font = tkfont.Font(self, family=self.font_family, size=9)
        self.tiny_font = tkfont.Font(self, family=self.font_family, size=8)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("Primary.TButton", background=self.TEAL, foreground="#ffffff", borderwidth=0, padding=(16, 9))
        style.map("Primary.TButton", background=[("active", self.TEAL_DARK), ("disabled", "#b6c3c0")])
        style.configure("Blue.TButton", background=self.BLUE, foreground="#ffffff", borderwidth=0, padding=(16, 9))
        style.map("Blue.TButton", background=[("active", "#235ab2")])
        style.configure("Orange.TButton", background=self.ORANGE, foreground="#ffffff", borderwidth=0, padding=(16, 9))
        style.map("Orange.TButton", background=[("active", "#a9650b")])
        style.configure("Purple.TButton", background=self.PURPLE, foreground="#ffffff", borderwidth=0, padding=(16, 9))
        style.map("Purple.TButton", background=[("active", "#5139bc")])
        style.configure("Dark.TButton", background="#165c53", foreground="#ffffff", borderwidth=0, padding=(16, 9))
        style.map("Dark.TButton", background=[("active", "#104a43")])
        style.configure("Tool.TButton", background="#e7eeec", foreground=self.TEXT, borderwidth=0, padding=(13, 8))
        style.map("Tool.TButton", background=[("active", "#d7e5e1")])
        style.configure("Dashboard.Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=self.TEXT, rowheight=26, borderwidth=0)
        style.configure("Dashboard.Treeview.Heading", background="#edf3f1", foreground=self.TEXT, relief="flat", font=(self.font_family, 9, "bold"))
        style.map("Dashboard.Treeview", background=[("selected", "#dff1ed")], foreground=[("selected", self.TEXT)])
        style.configure("TEntry", padding=(6, 5))
        style.configure("Vertical.TScrollbar", arrowsize=12)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()

        body = tk.Frame(self, bg=self.BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=190, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body).grid(row=0, column=0, sticky="nsew")
        self._build_workspace(body).grid(row=0, column=1, sticky="nsew", padx=(8, 8), pady=(8, 6))
        self._build_status_bar()

    def _build_header(self) -> None:
        header = tk.Frame(self, bg="#ffffff", height=98, highlightbackground=self.BORDER, highlightthickness=1)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)

        left = tk.Frame(header, bg="#ffffff")
        left.grid(row=0, column=0, sticky="nsew", padx=18, pady=13)
        tk.Label(left, text=APP_TITLE, bg="#ffffff", fg=self.TEXT, font=self.brand_font, anchor="w").pack(anchor="w")
        tk.Label(
            left,
            text="坐标基准统一 · 模态转换 · 三维建模 · 质量校验 · 成果追溯",
            bg="#ffffff",
            fg=self.MUTED,
            font=self.small_font,
        ).pack(anchor="w", pady=(8, 0))

        tk.Label(header, text="V1.0", bg="#ffffff", fg=self.MUTED, font=self.small_font).grid(
            row=0, column=1, sticky="se", padx=20, pady=18
        )

    def _build_sidebar(self, parent: tk.Widget) -> tk.Frame:
        panel = tk.Frame(parent, bg=self.SIDEBAR, width=190)
        panel.grid_propagate(False)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(5, weight=1)

        tk.Label(panel, text="转换平台", bg=self.SIDEBAR, fg="#ffffff", font=(self.font_family, 12, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=13, pady=(16, 4)
        )
        tk.Label(panel, text="工程数据 · 模态转换 · 成果输出", bg=self.SIDEBAR, fg="#c7d4d0", font=self.tiny_font, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=13, pady=(0, 12)
        )

        self.overview_button = tk.Button(
            panel,
            text="总览主界面",
            command=lambda: self._switch_page("工作台"),
            relief="flat",
            bd=0,
            anchor="w",
            padx=13,
            pady=10,
            bg=self.SIDEBAR_ITEM,
            fg="#ffffff",
            activebackground=self.TEAL,
            activeforeground="#ffffff",
            cursor="hand2",
        )
        self.overview_button.grid(row=2, column=0, sticky="ew", padx=9, pady=(0, 8))

        search_frame = tk.Frame(panel, bg="#203a33", highlightbackground="#29473f", highlightthickness=1)
        search_frame.grid(row=3, column=0, sticky="ew", padx=9, pady=(0, 8))
        search_frame.columnconfigure(0, weight=1)
        tk.Entry(
            search_frame,
            textvariable=self.search_var,
            relief="flat",
            bd=0,
            bg="#203a33",
            fg="#ffffff",
            insertbackground="#ffffff",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self.search_var.trace_add("write", lambda *_args: self._populate_menu())

        tk.Label(panel, text="功能模块", bg=self.SIDEBAR, fg="#91a59f", font=self.tiny_font, anchor="w").grid(
            row=4, column=0, sticky="ew", padx=13, pady=(0, 3)
        )

        canvas = tk.Canvas(panel, bg=self.SIDEBAR, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=5, column=0, sticky="nsew", padx=(7, 0))
        scrollbar.grid(row=5, column=1, sticky="ns")
        self.menu_content = tk.Frame(canvas, bg=self.SIDEBAR)
        menu_window = canvas.create_window((0, 0), window=self.menu_content, anchor="nw")
        self.menu_content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(menu_window, width=e.width))
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        foot = tk.Frame(panel, bg=self.SIDEBAR)
        foot.grid(row=6, column=0, columnspan=2, sticky="ew", padx=13, pady=12)
        tk.Label(foot, text="系统说明", bg=self.SIDEBAR, fg="#ffffff", font=(self.font_family, 9, "bold"), anchor="w").pack(anchor="w")
        tk.Label(
            foot,
            text="面向地质环境模型转换与质量检查，支持数据组织、任务分析和报告输出。",
            bg=self.SIDEBAR,
            fg="#aebfba",
            font=self.tiny_font,
            justify="left",
            wraplength=155,
        ).pack(anchor="w", pady=(5, 0))

        self._populate_menu()
        return panel

    def _populate_menu(self) -> None:
        for child in self.menu_content.winfo_children():
            child.destroy()
        self.menu_buttons.clear()
        query = self.search_var.get().strip().lower()
        row = 0
        module_index = 1
        for group in GROUP_ORDER:
            modules = [item for item in FEATURE_MODULES if item.group == group and query in item.name.lower()]
            if not modules:
                continue
            tk.Label(self.menu_content, text=group, bg=self.SIDEBAR, fg="#86a099", font=self.tiny_font, anchor="w").grid(
                row=row, column=0, sticky="ew", padx=7, pady=(9 if row else 2, 4)
            )
            row += 1
            for module in modules:
                text = f"{module_index}. {module.name.removesuffix('模块')}"
                button = tk.Button(
                    self.menu_content,
                    text=text,
                    command=lambda selected=module: self._select_module(selected),
                    relief="flat",
                    bd=0,
                    anchor="w",
                    justify="left",
                    padx=10,
                    pady=8,
                    bg=self.SIDEBAR_ITEM,
                    fg="#ffffff",
                    activebackground=self.TEAL,
                    activeforeground="#ffffff",
                    cursor="hand2",
                    wraplength=165,
                )
                button.module_name = module.name  # type: ignore[attr-defined]
                button.grid(row=row, column=0, sticky="ew", padx=(0, 5), pady=1)
                self.menu_buttons.append(button)
                row += 1
                module_index += 1
        self._refresh_menu()

    def _build_workspace(self, parent: tk.Widget) -> tk.Frame:
        """构建右侧业务工作区；左侧导航结构保持不变。"""
        panel = tk.Frame(parent, bg=self.BG)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(5, weight=1)

        hero = tk.Frame(panel, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        hero.columnconfigure(0, weight=1)

        hero_left = tk.Frame(hero, bg=self.PANEL)
        hero_left.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        hero_left.columnconfigure(0, weight=1)

        breadcrumb = tk.Frame(hero_left, bg=self.PANEL)
        breadcrumb.grid(row=0, column=0, sticky="ew")
        self.group_badge = tk.Label(
            breadcrumb,
            text=self.active_module.group,
            bg=self.TEAL_SOFT,
            fg=self.TEAL_DARK,
            font=(self.font_family, 8, "bold"),
            padx=8,
            pady=3,
        )
        self.group_badge.pack(side="left")
        tk.Label(
            breadcrumb,
            text="  /  功能工作台",
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.tiny_font,
        ).pack(side="left")

        tk.Label(
            hero_left,
            textvariable=self.module_title,
            bg=self.PANEL,
            fg=self.TEXT,
            font=self.hero_font,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(7, 0))
        tk.Label(
            hero_left,
            textvariable=self.module_desc,
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.small_font,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).grid(row=2, column=0, sticky="ew", pady=(6, 0))

        hero_right = tk.Frame(hero, bg=self.PANEL)
        hero_right.grid(row=0, column=1, sticky="e", padx=16, pady=12)
        tk.Label(hero_right, text="当前项目", bg=self.PANEL, fg=self.MUTED, font=self.tiny_font).grid(
            row=0, column=0, sticky="w"
        )
        project_box = ttk.Combobox(
            hero_right,
            textvariable=self.project_var,
            values=("默认项目", "典型数据试转换", "工程模型转换项目"),
            state="normal",
            width=22,
        )
        project_box.grid(row=1, column=0, sticky="ew", pady=(4, 7))
        status_line = tk.Frame(hero_right, bg=self.PANEL)
        status_line.grid(row=2, column=0, sticky="e")
        tk.Label(status_line, text="●", bg=self.PANEL, fg=self.GREEN if self.run_completed else self.AMBER).pack(side="left")
        tk.Label(
            status_line,
            textvariable=self.run_status_var,
            bg=self.PANEL,
            fg=self.TEAL_DARK,
            font=(self.font_family, 9, "bold"),
        ).pack(side="left", padx=(5, 0))

        toolbar = tk.Frame(panel, bg=self.BG)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        ttk.Button(toolbar, text="加载数据", style="Primary.TButton", command=self._choose_files).pack(side="left")
        ttk.Button(toolbar, text="配置规则", style="Tool.TButton", command=lambda: self._switch_page("参数配置")).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="开始转换", style="Blue.TButton", command=self._run_stub).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="预览检查", style="Orange.TButton", command=lambda: self._switch_page("预览检查")).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="导出报告", style="Purple.TButton", command=self._export_report).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="一键处理", style="Dark.TButton", command=self._one_click_analysis).pack(side="left", padx=(8, 0))
        tk.Label(toolbar, textvariable=self.status_var, bg=self.BG, fg=self.MUTED, font=self.small_font).pack(side="right", padx=5)

        self.progress_host = tk.Frame(panel, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        self.progress_host.grid(row=2, column=0, sticky="ew", pady=(0, 7))

        self.page_nav = tk.Frame(panel, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        self.page_nav.grid(row=3, column=0, sticky="ew", pady=(0, 7))
        for name in self.PAGE_NAMES:
            button = tk.Button(
                self.page_nav,
                text=name,
                command=lambda selected=name: self._switch_page(selected),
                relief="flat",
                bd=0,
                padx=15,
                pady=8,
                bg=self.PANEL,
                fg=self.MUTED,
                activebackground=self.TEAL_SOFT,
                activeforeground=self.TEAL_DARK,
                cursor="hand2",
            )
            button.pack(side="left")
            self.page_buttons[name] = button

        self.page_title_bar = tk.Frame(panel, bg=self.BG)
        self.page_title_bar.grid(row=4, column=0, sticky="ew", pady=(0, 3))

        self.content_host = tk.Frame(panel, bg=self.BG)
        self.content_host.grid(row=5, column=0, sticky="nsew")
        self.content_host.columnconfigure(0, weight=1)
        self.content_host.rowconfigure(0, weight=1)
        return panel

    def _render_progress_strip(self) -> None:
        for child in self.progress_host.winfo_children():
            child.destroy()
        for index in range(5):
            self.progress_host.columnconfigure(index, weight=1)

        workflow = list(self._profile()["workflow"])
        steps = (
            ("01", "数据接入", "识别源文件与空间基准"),
            ("02", workflow[0], "读取模块输入与规则"),
            ("03", workflow[1], "执行转换核心处理"),
            ("04", workflow[2], "完成质量检查与复核"),
            ("05", "成果输出", "生成模型、报告与追溯记录"),
        )
        active_step = 5 if self.run_completed else (2 if self.selected_files else 1)
        for col, (number, title, caption) in enumerate(steps, start=1):
            finished = col < active_step or self.run_completed
            active = col == active_step and not self.run_completed
            bg = self.TEAL_SOFT if finished or active else "#f7faf9"
            badge_bg = self.GREEN if finished else self.TEAL if active else "#dbe5e2"
            badge_fg = "#ffffff" if finished or active else self.MUTED
            cell = tk.Frame(self.progress_host, bg=bg, padx=10, pady=8)
            cell.grid(row=0, column=col - 1, sticky="nsew", padx=(8 if col == 1 else 3, 8 if col == 5 else 3), pady=8)
            cell.columnconfigure(1, weight=1)
            tk.Label(
                cell,
                text="✓" if finished else number,
                bg=badge_bg,
                fg=badge_fg,
                font=(self.font_family, 9, "bold"),
                width=3,
                pady=4,
            ).grid(row=0, column=0, rowspan=2, sticky="w")
            tk.Label(cell, text=title, bg=bg, fg=self.TEXT, font=(self.font_family, 9, "bold"), anchor="w").grid(
                row=0, column=1, sticky="ew", padx=(8, 0)
            )
            tk.Label(cell, text=caption, bg=bg, fg=self.MUTED, font=self.tiny_font, anchor="w").grid(
                row=1, column=1, sticky="ew", padx=(8, 0), pady=(3, 0)
            )

    def _switch_page(self, page_name: str) -> None:
        self.current_page = page_name
        self._render_current_page()

    def _render_current_page(self) -> None:
        for child in self.content_host.winfo_children():
            child.destroy()
        for name, button in self.page_buttons.items():
            active = name == self.current_page
            button.configure(
                bg=self.TEAL_SOFT if active else self.PANEL,
                fg=self.TEAL_DARK if active else self.MUTED,
                font=(self.font_family, 9, "bold" if active else "normal"),
            )
        self.overview_button.configure(bg=self.TEAL if self.current_page == "工作台" else self.SIDEBAR_ITEM)

        renderers = {
            "工作台": self._render_dashboard_page,
            "参数配置": self._render_params_page,
            "预览检查": self._render_preview_page,
            "任务与追溯": self._render_task_page,
            "后端接口": self._render_backend_page,
        }
        renderers[self.current_page]()

    def _render_dashboard_page(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=0)

        # 顶部指标：围绕采购要求展示输入、规则、质量与成果，而非风险研判。
        metrics = tk.Frame(root, bg=self.BG)
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        for index in range(4):
            metrics.columnconfigure(index, weight=1)
        configured = sum(1 for value in self.param_values.values() if value and value != "默认")
        quality_score = self._quality_score()
        metric_items = (
            ("已接入数据", f"{len(self.selected_files)} 个", "支持多源、多格式工程数据", self.TEAL),
            ("转换规则", f"{configured}/{len(self.active_module.parameters)} 项", "参数可复用并保存为模板", self.BLUE),
            ("质量状态", self._quality_grade(quality_score), "精度、拓扑、属性与完整性", self.ORANGE),
            ("预期成果", f"{len(self.active_module.outputs)} 类", "模型、报告与追溯记录", self.PURPLE),
        )
        for index, item in enumerate(metric_items):
            self._metric_card(metrics, *item).grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0 if index == 0 else 4, 0 if index == 3 else 4),
            )

        main = tk.Frame(root, bg=self.BG)
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=27)
        main.columnconfigure(1, weight=46)
        main.columnconfigure(2, weight=27)
        main.rowconfigure(0, weight=1)

        # 左：输入数据与数据源状态。
        source_card = self._card(main)
        source_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        source_card.columnconfigure(0, weight=1)
        source_card.rowconfigure(2, weight=1)
        self._card_header(source_card, "数据接入")
        tk.Label(
            source_card,
            text="按模块要求导入源数据，系统将识别格式、空间参考与字段结构。",
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.tiny_font,
            justify="left",
            wraplength=300,
        ).grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 8))

        source_wrap = tk.Frame(source_card, bg=self.PANEL)
        source_wrap.grid(row=2, column=0, sticky="nsew", padx=12)
        source_wrap.columnconfigure(0, weight=1)
        source_wrap.rowconfigure(0, weight=1)
        source_tree = ttk.Treeview(
            source_wrap,
            columns=("source", "format", "status"),
            show="headings",
            style="Dashboard.Treeview",
            height=6,
        )
        for key, title, width in (("source", "数据项", 155), ("format", "格式/数量", 95), ("status", "状态", 72)):
            source_tree.heading(key, text=title)
            source_tree.column(key, width=width, anchor="w")
        source_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(source_wrap, orient="vertical", command=source_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        source_tree.configure(yscrollcommand=scrollbar.set)

        for index, item in enumerate(self.active_module.inputs):
            loaded = index == 0 and bool(self.selected_files)
            amount = f"{len(self.selected_files)} 个文件" if loaded else self._input_format_hint(item)
            source_tree.insert("", "end", values=(item, amount, "已接入" if loaded else "待接入"))

        source_actions = tk.Frame(source_card, bg=self.PANEL)
        source_actions.grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        ttk.Button(source_actions, text="添加数据", style="Primary.TButton", command=self._choose_files).pack(side="left")
        ttk.Button(source_actions, text="清空", style="Tool.TButton", command=self._clear_files).pack(side="left", padx=(7, 0))

        # 中：与模块匹配的转换流程图和运行状态。
        process_card = self._card(main)
        process_card.grid(row=0, column=1, sticky="nsew", padx=5)
        process_card.columnconfigure(0, weight=1)
        process_card.rowconfigure(1, weight=1)
        self._card_header(process_card, "转换流程与模型预览")
        process_canvas = tk.Canvas(process_card, bg="#fbfcfc", highlightthickness=0, bd=0, height=215)
        process_canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        process_canvas.bind("<Configure>", lambda _e, c=process_canvas: self._draw_process_pipeline(c))

        process_footer = tk.Frame(process_card, bg=self.PANEL)
        process_footer.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 11))
        process_footer.columnconfigure(0, weight=1)
        tk.Label(
            process_footer,
            text=f"当前流程：{' → '.join(self._profile()['workflow'])}",
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.tiny_font,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(process_footer, text="执行转换", style="Blue.TButton", command=self._run_stub).grid(row=0, column=1, sticky="e")

        # 右：文档要求对应的能力、参数、成果和质量检查。
        spec_card = self._card(main)
        spec_card.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        spec_card.columnconfigure(0, weight=1)
        self._card_header(spec_card, "模块任务说明")
        spec_scroll_host = tk.Frame(spec_card, bg=self.PANEL)
        spec_scroll_host.grid(row=1, column=0, sticky="nsew", padx=(13, 5), pady=(0, 10))
        spec_scroll_host.columnconfigure(0, weight=1)
        spec_scroll_host.rowconfigure(0, weight=1)
        spec_canvas = tk.Canvas(spec_scroll_host, bg=self.PANEL, highlightthickness=0, bd=0)
        spec_canvas.grid(row=0, column=0, sticky="nsew")
        spec_scroll = ttk.Scrollbar(spec_scroll_host, orient="vertical", command=spec_canvas.yview)
        spec_scroll.grid(row=0, column=1, sticky="ns")
        spec_canvas.configure(yscrollcommand=spec_scroll.set)
        spec_body = tk.Frame(spec_canvas, bg=self.PANEL)
        spec_window = spec_canvas.create_window((0, 0), window=spec_body, anchor="nw")
        spec_body.bind("<Configure>", lambda _e: spec_canvas.configure(scrollregion=spec_canvas.bbox("all")))
        spec_canvas.bind("<Configure>", lambda e: spec_canvas.itemconfigure(spec_window, width=e.width))
        spec_body.columnconfigure(0, weight=1)

        self._compact_info_section(spec_body, 0, "核心能力", self._profile()["focus"], self.TEAL)
        self._compact_info_section(spec_body, 1, "关键参数", self.active_module.parameters, self.BLUE)
        self._compact_info_section(spec_body, 2, "质量检查", self._profile()["checks"], self.ORANGE)
        self._compact_info_section(spec_body, 3, "成果输出", self.active_module.outputs, self.PURPLE)

        # 底：结果、质量与成果状态，直接服务于转换与交付。
        result_card = self._card(root)
        result_card.configure(height=112)
        result_card.grid_propagate(False)
        result_card.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        result_card.columnconfigure(0, weight=1)
        self._card_header(result_card, "转换成果与质量摘要")
        result_wrap = tk.Frame(result_card, bg=self.PANEL)
        result_wrap.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        result_wrap.columnconfigure(0, weight=1)
        result_tree = ttk.Treeview(
            result_wrap,
            columns=("artifact", "type", "status", "quality", "trace"),
            show="headings",
            height=2,
            style="Dashboard.Treeview",
        )
        columns = (
            ("artifact", "成果名称", 220),
            ("type", "成果类型", 150),
            ("status", "处理状态", 100),
            ("quality", "质量检查", 180),
            ("trace", "追溯信息", 220),
        )
        for key, title, width in columns:
            result_tree.heading(key, text=title)
            result_tree.column(key, width=width, anchor="w")
        result_tree.grid(row=0, column=0, sticky="ew")
        for row in self._result_rows():
            result_tree.insert("", "end", values=row)

    def _render_params_page(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=62)
        root.columnconfigure(1, weight=38)
        root.rowconfigure(0, weight=1)

        form_card = self._card(root)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        form_card.columnconfigure(0, weight=1)
        form_card.rowconfigure(2, weight=1)
        self._card_header(form_card, "转换规则配置")
        tk.Label(
            form_card,
            text="规则参数将随任务提交，并保存至任务参数与规则模板记录中。",
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.small_font,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 8))

        form_canvas = tk.Canvas(form_card, bg=self.PANEL, highlightthickness=0)
        form_canvas.grid(row=2, column=0, sticky="nsew", padx=(12, 2), pady=(0, 8))
        form_scroll = ttk.Scrollbar(form_card, orient="vertical", command=form_canvas.yview)
        form_scroll.grid(row=2, column=1, sticky="ns", pady=(0, 8))
        form_canvas.configure(yscrollcommand=form_scroll.set)
        form = tk.Frame(form_canvas, bg=self.PANEL)
        form_window = form_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _e: form_canvas.configure(scrollregion=form_canvas.bbox("all")))
        form_canvas.bind("<Configure>", lambda e: form_canvas.itemconfigure(form_window, width=e.width))
        form.columnconfigure(1, weight=1)
        self.param_vars.clear()

        defaults = self._parameter_defaults()
        for row_index, name in enumerate(self.active_module.parameters):
            block = tk.Frame(form, bg="#f8faf9", highlightbackground=self.BORDER, highlightthickness=1)
            block.grid(row=row_index, column=0, columnspan=2, sticky="ew", pady=(0, 7))
            block.columnconfigure(1, weight=1)
            tk.Label(block, text=name, bg="#f8faf9", fg=self.TEXT, font=(self.font_family, 9, "bold"), anchor="w").grid(
                row=0, column=0, sticky="w", padx=13, pady=12
            )
            initial = self.param_values.get(name, defaults.get(name, "默认"))
            var = tk.StringVar(value=initial)
            self.param_vars[name] = var
            ttk.Entry(block, textvariable=var).grid(row=0, column=1, sticky="ew", padx=(10, 13), pady=9)
            tk.Label(
                block,
                text=f"用于控制{name}，后端接入后进行合法性与精度校验。",
                bg="#f8faf9",
                fg=self.MUTED,
                font=self.tiny_font,
                anchor="w",
            ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=13, pady=(0, 9))

        form_actions = tk.Frame(form_card, bg=self.PANEL)
        form_actions.grid(row=3, column=0, columnspan=2, sticky="e", padx=13, pady=(3, 12))
        ttk.Button(form_actions, text="应用参数", style="Primary.TButton", command=self._apply_params).pack(side="left")
        ttk.Button(form_actions, text="保存为规则模板", style="Tool.TButton", command=self._save_template_stub).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(form_actions, text="生成任务请求", style="Tool.TButton", command=self._generate_task_payload).pack(
            side="left", padx=(8, 0)
        )

        guide_card = self._card(root)
        guide_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        guide_card.columnconfigure(0, weight=1)
        self._card_header(guide_card, "规则与输出说明")
        guide = tk.Frame(guide_card, bg=self.PANEL)
        guide.grid(row=1, column=0, sticky="nsew", padx=13, pady=(0, 12))
        guide.columnconfigure(0, weight=1)
        self._info_section(guide, 0, "输入要求", self.active_module.inputs, self.TEAL)
        self._info_section(guide, 1, "执行流程", self._profile()["workflow"], self.BLUE)
        self._info_section(guide, 2, "质量约束", self._profile()["checks"], self.ORANGE)
        self._info_section(guide, 3, "输出成果", self.active_module.outputs, self.PURPLE)

    def _render_preview_page(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=72)
        root.columnconfigure(1, weight=28)
        root.rowconfigure(0, weight=1)

        preview_card = self._card(root)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=1)
        self._card_header(preview_card, "二维 / 三维 / 剖切预览")
        canvas = tk.Canvas(preview_card, bg="#fbfcfc", highlightthickness=0)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        canvas.bind("<Configure>", lambda _e, c=canvas: self._draw_preview(c))

        quality_card = self._card(root)
        quality_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        quality_card.columnconfigure(0, weight=1)
        self._card_header(quality_card, "质量检查清单")
        body = tk.Frame(quality_card, bg=self.PANEL)
        body.grid(row=1, column=0, sticky="nsew", padx=13, pady=(0, 12))
        body.columnconfigure(0, weight=1)
        score = self._quality_score()
        tk.Label(body, text=str(score) if self.run_completed else "--", bg=self.PANEL, fg=self.TEAL_DARK, font=(self.font_family, 28, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(body, text=f"质量评分 · {self._quality_grade(score)}", bg=self.PANEL, fg=self.MUTED, font=self.small_font).grid(
            row=1, column=0, sticky="w", pady=(0, 12)
        )
        for row_index, check in enumerate(self._profile()["checks"], start=2):
            passed = self.run_completed
            item = tk.Frame(body, bg="#f7faf9", highlightbackground=self.BORDER, highlightthickness=1)
            item.grid(row=row_index, column=0, sticky="ew", pady=(0, 7))
            item.columnconfigure(1, weight=1)
            tk.Label(item, text="✓" if passed else "·", bg=self.GREEN if passed else "#e3ebe8", fg="#ffffff" if passed else self.MUTED, width=3, pady=7).grid(
                row=0, column=0, sticky="nsw"
            )
            tk.Label(item, text=check, bg="#f7faf9", fg=self.TEXT, font=(self.font_family, 9, "bold"), anchor="w").grid(
                row=0, column=1, sticky="ew", padx=9
            )
            tk.Label(item, text="通过" if passed else "待执行", bg="#f7faf9", fg=self.GREEN if passed else self.MUTED, font=self.tiny_font).grid(
                row=0, column=2, sticky="e", padx=9
            )
        ttk.Button(body, text="重新执行质量检查", style="Primary.TButton", command=self._run_stub).grid(
            row=7, column=0, sticky="ew", pady=(6, 0)
        )

    def _render_task_page(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        summary = tk.Frame(root, bg=self.BG)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        for index in range(4):
            summary.columnconfigure(index, weight=1)
        items = (
            ("任务状态", self.run_status_var.get(), "当前转换任务", self.TEAL),
            ("任务模块", self.active_module.name.removesuffix("模块"), self.active_module.group, self.BLUE),
            ("版本记录", "1 条" if self.run_completed else "0 条", "支持历史版本对比", self.PURPLE),
            ("追溯链", "完整" if self.run_completed else "待生成", "来源—参数—过程—成果", self.ORANGE),
        )
        for index, item in enumerate(items):
            self._metric_card(summary, *item).grid(
                row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 4, 0 if index == 3 else 4)
            )

        body = tk.Frame(root, bg=self.BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=48)
        body.columnconfigure(1, weight=52)
        body.rowconfigure(0, weight=1)

        task_card = self._card(body)
        task_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        task_card.columnconfigure(0, weight=1)
        task_card.rowconfigure(2, weight=1)
        self._card_header(task_card, "任务执行记录")
        task_actions = tk.Frame(task_card, bg=self.PANEL)
        task_actions.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 9))
        ttk.Button(task_actions, text="生成任务请求", style="Primary.TButton", command=self._generate_task_payload).pack(side="left")
        ttk.Button(task_actions, text="执行任务", style="Tool.TButton", command=self._run_stub).pack(side="left", padx=7)
        ttk.Button(task_actions, text="归档版本", style="Tool.TButton", command=self._archive_stub).pack(side="left")

        task_tree = ttk.Treeview(
            task_card,
            columns=("step", "operation", "status", "record"),
            show="headings",
            style="Dashboard.Treeview",
            height=10,
        )
        for key, title, width in (("step", "序号", 55), ("operation", "处理环节", 170), ("status", "状态", 85), ("record", "追溯记录", 220)):
            task_tree.heading(key, text=title)
            task_tree.column(key, width=width, anchor="w")
        task_tree.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        task_steps = ("数据接入",) + tuple(self._profile()["workflow"]) + ("质量报告与成果归档",)
        for index, step in enumerate(task_steps, start=1):
            task_tree.insert(
                "",
                "end",
                values=(f"{index:02d}", step, "完成" if self.run_completed else "待执行", "已记录" if self.run_completed else "等待生成"),
            )

        payload_card = self._card(body)
        payload_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        payload_card.columnconfigure(0, weight=1)
        payload_card.rowconfigure(1, weight=1)
        self._card_header(payload_card, "任务请求与追溯载荷")
        self.task_text = tk.Text(payload_card, relief="flat", bd=0, bg=self.SOFT, fg=self.TEXT, wrap="word", font=self.small_font)
        self.task_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.task_text.insert("1.0", self.task_payload_text)

    def _render_backend_page(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=52)
        root.columnconfigure(1, weight=48)
        root.rowconfigure(0, weight=1)

        api_card = self._card(root)
        api_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        api_card.columnconfigure(0, weight=1)
        api_card.rowconfigure(2, weight=1)
        self._card_header(api_card, "后端服务接口")
        tk.Label(
            api_card,
            text="前端负责请求组装与状态展示，后端负责转换算法、质量校验、文件存储和 MySQL 持久化。",
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.small_font,
            justify="left",
            wraplength=620,
        ).grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 9))
        api_tree = ttk.Treeview(
            api_card,
            columns=("name", "method", "path", "purpose"),
            show="headings",
            style="Dashboard.Treeview",
            height=12,
        )
        for key, title, width in (("name", "接口", 125), ("method", "方法", 70), ("path", "路径", 255), ("purpose", "用途", 170)):
            api_tree.heading(key, text=title)
            api_tree.column(key, width=width, anchor="w")
        api_tree.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        purposes = {
            "create_project": "创建项目",
            "upload_dataset": "上传与登记数据",
            "save_template": "保存转换规则模板",
            "create_task": "创建转换任务",
            "run_task": "执行转换任务",
            "task_status": "查询运行状态",
            "quality_report": "获取质量报告",
            "version_archive": "归档模型版本",
        }
        for name, endpoint in BACKEND_ENDPOINTS.items():
            method, path = endpoint.split(" ", 1)
            api_tree.insert("", "end", values=(name, method, path, purposes[name]))

        db_card = self._card(root)
        db_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        db_card.columnconfigure(0, weight=1)
        db_card.rowconfigure(3, weight=1)
        self._card_header(db_card, "MySQL 数据与成果存储")
        self.mysql_var.set(
            f"{self.backend.mysql_config['host']}:{self.backend.mysql_config['port']} / "
            f"{self.backend.mysql_config['database']} / {self.backend.mysql_config['user']}"
        )
        tk.Label(db_card, text=self.mysql_var.get(), bg="#f7faf9", fg=self.TEAL_DARK, font=(self.font_family, 9, "bold"), anchor="w", padx=11, pady=9).grid(
            row=1, column=0, sticky="ew", padx=12, pady=(0, 9)
        )
        tk.Label(
            db_card,
            text="当前模块关联表",
            bg=self.PANEL,
            fg=self.TEXT,
            font=self.section_font,
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=13, pady=(0, 7))
        table_tree = ttk.Treeview(
            db_card,
            columns=("table", "content", "state"),
            show="headings",
            style="Dashboard.Treeview",
            height=11,
        )
        for key, title, width in (("table", "数据表", 210), ("content", "保存内容", 230), ("state", "状态", 80)):
            table_tree.heading(key, text=title)
            table_tree.column(key, width=width, anchor="w")
        table_tree.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_notes = ("源数据与元信息", "转换任务与参数", "成果文件与质量记录", "版本与追溯关系")
        all_tables = tuple(self.active_module.mysql_tables) + ("conversion_tasks", "task_artifacts", "operation_logs")
        for index, table in enumerate(dict.fromkeys(all_tables)):
            table_tree.insert("", "end", values=(table, table_notes[index % len(table_notes)], "接口预留"))

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(parent, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)

    def _card_header(self, parent: tk.Widget, title: str, columnspan: int = 1) -> None:
        tk.Label(parent, text=title, bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(
            row=0, column=0, columnspan=columnspan, sticky="ew", padx=13, pady=(12, 9)
        )

    def _section_title(self, parent: tk.Widget, title: str, subtitle: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.columnconfigure(0, weight=1)
        tk.Label(frame, text=title, bg=self.PANEL, fg=self.TEXT, font=self.section_font, anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(frame, text=subtitle, bg=self.PANEL, fg=self.MUTED, font=self.small_font, anchor="w", wraplength=1100).grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )
        return frame

    def _profile(self) -> dict[str, object]:
        return MODULE_UI_PROFILES[self.active_module.name]

    def _workflow_strip(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        for index in range(4):
            frame.columnconfigure(index, weight=1)
        for col, title in enumerate(self._profile()["workflow"]):
            card = tk.Frame(frame, bg="#f7faf9", highlightbackground=self.BORDER, highlightthickness=1, padx=10, pady=8)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 0))
            tk.Label(
                card,
                text=str(col + 1),
                bg=self.TEAL if col == 0 else "#dce9e6",
                fg="#ffffff" if col == 0 else self.TEAL_DARK,
                font=(self.font_family, 9, "bold"),
                padx=7,
                pady=4,
            ).pack(side="left")
            tk.Label(card, text=title, bg="#f7faf9", fg=self.TEXT, font=(self.font_family, 9, "bold")).pack(
                side="left", padx=(8, 0)
            )
        return frame

    def _quality_strip(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        for index in range(4):
            frame.columnconfigure(index, weight=1)
        for col, title in enumerate(self._profile()["checks"]):
            card = tk.Frame(frame, bg="#f7faf9", highlightbackground=self.BORDER, highlightthickness=1, padx=11, pady=9)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 0))
            tk.Label(card, text=title, bg="#f7faf9", fg=self.TEXT, font=(self.font_family, 9, "bold")).pack(anchor="w")
            tk.Label(
                card,
                text="通过" if self.run_completed else "待执行",
                bg="#f7faf9",
                fg=self.GREEN if self.run_completed else self.MUTED,
                font=self.tiny_font,
            ).pack(anchor="w", pady=(4, 0))
        return frame

    def _backend_strip(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL)
        for index in range(3):
            frame.columnconfigure(index, weight=1)
        items = (
            ("服务层", "REST API / 算法服务"),
            ("数据库", self.backend.mysql_config["database"]),
            ("追溯链", "数据源 · 参数 · 过程 · 成果"),
        )
        for col, (title, caption) in enumerate(items):
            card = tk.Frame(frame, bg="#f7faf9", highlightbackground=self.BORDER, highlightthickness=1, padx=13, pady=10)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 0))
            tk.Label(card, text=title, bg="#f7faf9", fg=self.TEAL_DARK, font=(self.font_family, 9, "bold")).pack(anchor="w")
            tk.Label(card, text=caption, bg="#f7faf9", fg=self.MUTED, font=self.small_font).pack(anchor="w", pady=(5, 0))
        return frame

    def _metric_card(self, parent: tk.Widget, title: str, value: str, caption: str, accent: str) -> tk.Frame:
        card = tk.Frame(parent, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1, padx=12, pady=5, height=72)
        card.pack_propagate(False)
        tk.Frame(card, bg=accent, width=4).pack(side="left", fill="y", padx=(0, 11))
        content = tk.Frame(card, bg=self.PANEL)
        content.pack(side="left", fill="both", expand=True)
        tk.Label(content, text=title, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").pack(anchor="w")
        tk.Label(content, text=value, bg=self.PANEL, fg=self.TEXT, font=(self.font_family, 14, "bold"), anchor="w").pack(
            anchor="w", pady=(3, 0)
        )
        tk.Label(content, text=caption, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").pack(anchor="w", pady=(3, 0))
        return card

    def _compact_info_section(self, parent: tk.Widget, row: int, title: str, items: tuple[str, ...] | list[str], accent: str) -> None:
        block = tk.Frame(parent, bg=self.PANEL)
        block.grid(row=row, column=0, sticky="ew", pady=(0, 9))
        block.columnconfigure(0, weight=1)
        header = tk.Frame(block, bg=self.PANEL)
        header.grid(row=0, column=0, sticky="ew")
        tk.Frame(header, bg=accent, width=4, height=16).pack(side="left")
        tk.Label(header, text=title, bg=self.PANEL, fg=self.TEXT, font=(self.font_family, 9, "bold")).pack(side="left", padx=(7, 0))
        tk.Label(
            block,
            text=" · ".join(str(item) for item in items),
            bg=self.PANEL,
            fg=self.MUTED,
            font=self.tiny_font,
            justify="left",
            anchor="w",
            wraplength=310,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def _info_section(self, parent: tk.Widget, row: int, title: str, items: tuple[str, ...] | list[str], accent: str) -> None:
        block = tk.Frame(parent, bg="#f8faf9", highlightbackground=self.BORDER, highlightthickness=1)
        block.grid(row=row, column=0, sticky="ew", pady=(0, 7))
        block.columnconfigure(0, weight=1)
        header = tk.Frame(block, bg="#f8faf9")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(9, 5))
        tk.Frame(header, bg=accent, width=4, height=17).pack(side="left")
        tk.Label(header, text=title, bg="#f8faf9", fg=self.TEXT, font=(self.font_family, 9, "bold")).pack(side="left", padx=(7, 0))
        text = "\n".join(f"• {item}" for item in items)
        tk.Label(
            block,
            text=text,
            bg="#f8faf9",
            fg=self.MUTED,
            font=self.tiny_font,
            justify="left",
            anchor="w",
            wraplength=300,
        ).grid(row=1, column=0, sticky="ew", padx=11, pady=(0, 9))

    def _input_format_hint(self, item: str) -> str:
        value = item.lower()
        if "点云" in item:
            return "LAS / LAZ / PLY"
        if "栅格" in item or "dem" in value or "影像" in item:
            return "TIFF / IMG"
        if "矢量" in item or "图" in item or "线" in item or "边界" in item:
            return "SHP / DXF / GeoJSON"
        if "网格" in item or "模型" in item or "空间对象" in item:
            return "VTK / OBJ / IFC"
        if "表" in item or "记录" in item or "字典" in item or "指标" in item:
            return "CSV / XLSX / JSON"
        return "待识别"

    def _parameter_defaults(self) -> dict[str, str]:
        return {
            "目标坐标系": "CGCS2000 / 工程坐标系",
            "目标高程基准": "1985 国家高程基准",
            "单位体系": "m / kN / MPa",
            "转换精度": "工程级",
            "目标格式": "GeoJSON / VTK / IFC",
            "输出格式": "LAS / LAZ / PLY",
            "日志级别": "INFO",
            "失败重试次数": "3",
            "并发数量": "4",
            "版本号": "V1.0.0",
            "预览模式": "二维 + 三维 + 剖切",
        }

    def _quality_score(self) -> int:
        if not self.run_completed:
            return 0
        seed = sum(ord(ch) for ch in self.active_module.name)
        return 86 + seed % 10

    @staticmethod
    def _quality_grade(score: int) -> str:
        if score == 0:
            return "待检查"
        if score >= 90:
            return "优秀"
        if score >= 80:
            return "合格"
        return "需复核"

    # 兼容原报告字段，现解释为质量评分而非风险评分。
    def _score_values(self) -> list[int]:
        score = self._quality_score()
        if score == 0:
            return [0, 0, 0, 0, 0]
        return [max(0, min(100, score + offset)) for offset in (-3, 2, -1, 3, 0)]

    def _overall_score(self) -> int:
        return self._quality_score()

    @staticmethod
    def _risk_level(score: int) -> str:
        return GeoConversionApp._quality_grade(score)

    def _result_rows(self) -> list[tuple[str, str, str, str, str]]:
        rows: list[tuple[str, str, str, str, str]] = []
        status = "已生成" if self.run_completed else "待生成"
        quality = f"{self._quality_score()} 分 / {self._quality_grade(self._quality_score())}" if self.run_completed else "待执行质量检查"
        for index, output in enumerate(self.active_module.outputs):
            artifact_type = "模型成果" if any(token in output for token in ("模型", "网格", "对象", "数据")) else "报告/记录"
            trace = f"{self.active_module.mysql_tables[index % len(self.active_module.mysql_tables)]} · 可追溯"
            rows.append((output, artifact_type, status, quality, trace))
        return rows

    def _draw_process_pipeline(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 260)
        height = max(canvas.winfo_height(), 50)
        steps = ("源数据",) + tuple(self._profile()["workflow"]) + ("成果",)
        count = len(steps)

        # 当窗口高度较小时使用紧凑流程图，避免图形被裁切。
        if height < 145:
            left, right = 24, width - 24
            center_y = max(20, height * 0.35)
            gap = (right - left) / max(count - 1, 1)
            radius = 9
            for index, step in enumerate(steps):
                x = left + index * gap
                finished = self.run_completed or (index == 0 and self.selected_files)
                active = (index == 1 and self.selected_files and not self.run_completed) or (index == 0 and not self.selected_files)
                color = self.GREEN if finished else self.TEAL if active else "#c8d5d1"
                if index < count - 1:
                    next_x = left + (index + 1) * gap
                    canvas.create_line(x + radius, center_y, next_x - radius, center_y, fill=color, width=2)
                canvas.create_oval(x - radius, center_y - radius, x + radius, center_y + radius, fill=color, outline="")
                canvas.create_text(x, center_y, text="✓" if finished else str(index + 1), fill="#ffffff", font=(self.font_family, 7, "bold"))
                canvas.create_text(x, center_y + 18, text=step, width=max(50, gap - 3), fill=self.TEXT, font=(self.font_family, 7), justify="center")
            return

        canvas.create_rectangle(10, 10, width - 10, height - 10, fill="#fbfcfc", outline=self.BORDER)
        canvas.create_text(25, 28, text=self.active_module.name, anchor="w", fill=self.TEXT, font=self.section_font)
        canvas.create_text(width - 25, 28, text=self._profile()["layout"].upper(), anchor="e", fill=self.MUTED, font=self.tiny_font)
        left, right = 45, width - 45
        center_y = min(92, height * 0.42)
        gap = (right - left) / max(count - 1, 1)
        for index, step in enumerate(steps):
            x = left + index * gap
            finished = self.run_completed or (index == 0 and self.selected_files)
            active = (index == 1 and self.selected_files and not self.run_completed) or (index == 0 and not self.selected_files)
            fill = self.GREEN if finished else self.TEAL if active else "#dfe8e5"
            outline = self.GREEN if finished else self.TEAL if active else "#bdcbc7"
            if index < count - 1:
                next_x = left + (index + 1) * gap
                canvas.create_line(x + 17, center_y, next_x - 17, center_y, fill=self.TEAL if finished else "#c8d5d1", width=3)
            canvas.create_oval(x - 16, center_y - 16, x + 16, center_y + 16, fill=fill, outline=outline, width=2)
            canvas.create_text(x, center_y, text="✓" if finished else str(index + 1), fill="#ffffff" if finished or active else self.MUTED, font=(self.font_family, 8, "bold"))
            canvas.create_text(x, center_y + 29, text=step, width=max(60, gap - 5), fill=self.TEXT, font=(self.font_family, 7, "bold"), justify="center")

        if height < 205:
            return
        visual = self._profile()["visual"]
        preview_y = height * 0.78
        if visual in {"coordinate", "section_map", "raster_vector", "boundary"}:
            canvas.create_line(width * 0.24, preview_y + 20, width * 0.43, preview_y - 14, width * 0.62, preview_y + 10, width * 0.78, preview_y - 20, fill=self.TEAL, width=3, smooth=True)
            canvas.create_line(width * 0.25, preview_y - 8, width * 0.43, preview_y + 15, width * 0.61, preview_y - 12, width * 0.76, preview_y + 16, fill=self.AMBER, width=2, smooth=True)
        elif visual in {"borehole", "point_cloud"}:
            for index in range(32):
                x = width * 0.28 + (index * 41) % int(max(width * 0.45, 1))
                y = preview_y - 24 + (index * 29) % 48
                canvas.create_oval(x, y, x + 4, y + 4, fill=self.TEAL if index % 3 else self.AMBER, outline="")
        elif visual in {"mesh", "voxel", "local_detail", "property_map", "multiscale"}:
            size = 22
            start_x = width / 2 - 4 * size
            for row in range(3):
                for col in range(8):
                    fill = self.RED if visual == "local_detail" and 2 <= col <= 5 and row == 1 else self.TEAL if (row + col) % 3 else self.AMBER
                    canvas.create_rectangle(start_x + col * size, preview_y - 30 + row * size, start_x + col * size + size - 3, preview_y - 30 + row * size + size - 3, fill=fill, outline="#ffffff")
        else:
            for index, value in enumerate((0.78, 0.56, 0.88, 0.69)):
                y = preview_y - 32 + index * 16
                canvas.create_rectangle(width * 0.34, y, width * 0.67, y + 8, fill="#e6eeec", outline="")
                canvas.create_rectangle(width * 0.34, y, width * (0.34 + 0.33 * value), y + 8, fill=self.TEAL if index != 2 else self.AMBER, outline="")

    def _draw_radar(self, canvas: tk.Canvas) -> None:
        """保留旧调用兼容性，统一绘制新的转换流程图。"""
        self._draw_process_pipeline(canvas)

    def _build_conclusion_text(self) -> str:
        if not self.run_completed:
            return (
                "当前任务尚未执行。请先接入源数据、配置转换规则，再执行转换与质量检查。\n\n"
                "系统将输出模型成果、质量报告以及来源—参数—过程—成果追溯记录。"
            )
        return (
            f"转换已完成，质量评分 {self._quality_score()} 分，等级为“{self._quality_grade(self._quality_score())}”。\n\n"
            f"已完成：{'、'.join(self._profile()['checks'])}。\n"
            f"可输出：{'、'.join(self.active_module.outputs)}。"
        )

    def _draw_preview(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 720)
        height = max(canvas.winfo_height(), 430)
        canvas.create_rectangle(16, 16, width - 16, height - 16, fill="#fbfcfc", outline=self.BORDER)
        canvas.create_text(34, 35, text=f"{self.active_module.name} · 成果预览", fill=self.TEXT, anchor="w", font=self.section_font)
        canvas.create_text(width - 34, 35, text="2D  |  3D  |  SECTION", fill=self.MUTED, anchor="e", font=self.small_font)

        split_x = width * 0.52
        canvas.create_rectangle(34, 58, split_x - 8, height - 62, fill="#f6f9f8", outline=self.BORDER)
        canvas.create_rectangle(split_x + 8, 58, width - 34, height - 62, fill="#f6f9f8", outline=self.BORDER)
        canvas.create_text(48, 76, text="转换前", fill=self.MUTED, anchor="w", font=(self.font_family, 9, "bold"))
        canvas.create_text(split_x + 22, 76, text="转换后", fill=self.TEAL_DARK, anchor="w", font=(self.font_family, 9, "bold"))

        visual = self._profile()["visual"]
        centers = ((width * 0.27, height * 0.52, False), (width * 0.75, height * 0.52, True))
        for cx, cy, converted in centers:
            accent = self.TEAL if converted else "#8fa5a0"
            if visual in {"coordinate", "section_map", "raster_vector", "boundary"}:
                for index in range(5):
                    y = cy - 88 + index * 40
                    canvas.create_line(cx - 150, y, cx + 150, y + (16 if index % 2 else -10), fill="#b9cac5")
                canvas.create_line(cx - 135, cy + 58, cx + 128, cy - 46, fill=accent, width=3, smooth=True)
                canvas.create_line(cx - 120, cy - 60, cx + 118, cy + 48, fill=self.AMBER, width=2, smooth=True)
            elif visual in {"borehole", "point_cloud"}:
                for index in range(72):
                    x = cx - 150 + (index * 37) % 300
                    y = cy - 92 + (index * 53) % 184
                    canvas.create_oval(x, y, x + 4, y + 4, fill=accent if index % 4 else self.AMBER, outline="")
                if visual == "borehole":
                    for x in (cx - 85, cx - 25, cx + 45, cx + 105):
                        canvas.create_line(x, cy - 105, x, cy + 105, fill=self.RED if converted else "#a98b86", width=3)
            elif visual in {"mesh", "voxel", "local_detail", "property_map", "multiscale"}:
                size = 34
                for row in range(5):
                    for col in range(8):
                        fill = accent if (row + col) % 3 else self.AMBER
                        if visual == "local_detail" and converted and 2 <= row <= 3 and 2 <= col <= 5:
                            fill = self.RED
                        canvas.create_rectangle(cx - 136 + col * size, cy - 86 + row * size, cx - 136 + col * size + size - 4, cy - 86 + row * size + size - 4, fill=fill, outline="#ffffff")
            else:
                for index, length in enumerate((230, 170, 260, 205, 145)):
                    y = cy - 92 + index * 42
                    canvas.create_rectangle(cx - 145, y, cx + 145, y + 25, fill="#edf3f1", outline=self.BORDER)
                    canvas.create_rectangle(cx - 135, y + 8, cx - 135 + length * (1.0 if converted else 0.72), y + 17, fill=accent if index != 2 else self.AMBER, outline="")

        state_text = "转换完成，可进行空间、属性与边界对比检查" if self.run_completed else "演示预览：执行转换后显示后端返回的真实模型与差异结果"
        canvas.create_text(width / 2, height - 36, text=state_text, fill=self.GREEN if self.run_completed else self.MUTED, font=self.small_font)

    def _choose_files(self) -> None:
        files = list(filedialog.askopenfilenames(title="选择源数据文件"))
        if not files:
            return
        for file_path in files:
            if file_path not in self.selected_files:
                self.selected_files.append(file_path)
        self._append_log(f"已加载 {len(files)} 个数据文件。")
        self.status_var.set(f"已添加 {len(files)} 个文件")
        self.run_status_var.set("数据已加载")
        self._render_current_page()

    def _clear_files(self) -> None:
        if not self.selected_files:
            self.status_var.set("当前没有已加载的数据")
            return
        count = len(self.selected_files)
        self.selected_files.clear()
        self.run_completed = False
        self.run_status_var.set("待处理")
        self._append_log(f"已清空 {count} 个数据文件。")
        self.status_var.set("数据列表已清空")
        self._render_progress_strip()
        self._render_current_page()

    def _apply_params(self) -> None:
        self.param_values.update({name: var.get().strip() for name, var in self.param_vars.items()})
        self._append_log(f"已应用 {len(self.param_values)} 项参数配置。")
        self.status_var.set("参数配置已应用")
        self.run_status_var.set("参数已配置")

    def _save_template_stub(self) -> None:
        self._apply_params()
        self._append_log(f"已调用模板保存接口占位：{BACKEND_ENDPOINTS['save_template']}")
        self.status_var.set(f"已预留模板保存接口：{BACKEND_ENDPOINTS['save_template']}")

    def _run_stub(self) -> None:
        self.run_completed = True
        self.run_status_var.set("处理完成")
        self.status_var.set(f"已预留任务执行接口：{BACKEND_ENDPOINTS['run_task']}")
        workflow = self._profile()["workflow"]
        self._append_log("开始执行模块处理流程。")
        for index, step in enumerate(workflow, start=1):
            self._append_log(f"[步骤 {index}/4] {step} —— 完成")
        self._append_log("质量检查和结果汇总已完成。")
        self.task_payload_text += "\n接口占位：后端接入后将提交任务并轮询运行状态。\n"
        self._render_progress_strip()
        self._render_current_page()

    def _one_click_analysis(self) -> None:
        self._run_stub()
        self.current_page = "工作台"
        self._render_current_page()
        self.status_var.set("一键分析完成，已刷新汇总研判结果")

    def _show_results(self) -> None:
        self.current_page = "工作台"
        self._render_current_page()
        self.status_var.set("已切换至结果汇总研判界面")

    def _archive_stub(self) -> None:
        self.status_var.set(f"已预留版本归档接口：{BACKEND_ENDPOINTS['version_archive']}")
        self._append_log("版本归档接口已调用，等待后端写入 model_versions 与 lineage_records。")
        self.task_payload_text += "\n接口占位：后端接入后将写入 model_versions 与 lineage_records。\n"
        if hasattr(self, "task_text") and self.task_text.winfo_exists():
            self.task_text.delete("1.0", tk.END)
            self.task_text.insert("1.0", self.task_payload_text)

    def _generate_task_payload(self) -> None:
        if self.param_vars:
            self.param_values.update({name: var.get().strip() for name, var in self.param_vars.items()})
        payload = self.backend.build_task_payload(self.active_module, self.selected_files, self.param_values)
        self.task_payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.status_var.set(f"已生成任务请求：{BACKEND_ENDPOINTS['create_task']}")
        self._append_log("任务请求 JSON 已生成。")
        if hasattr(self, "task_text") and self.task_text.winfo_exists():
            self.task_text.delete("1.0", tk.END)
            self.task_text.insert("1.0", self.task_payload_text)

    def _export_report(self) -> None:
        report = {
            "app": APP_TITLE,
            "project": self.project_var.get(),
            "module": self.active_module.name,
            "status": self.run_status_var.get(),
            "input_files": self.selected_files,
            "parameters": self.param_values,
            "outputs": list(self.active_module.outputs),
            "quality_score": self._quality_score(),
            "quality_grade": self._quality_grade(self._quality_score()),
            "logs": self.logs,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }
        path = filedialog.asksaveasfilename(
            title="导出分析报告",
            defaultextension=".json",
            filetypes=(("JSON 报告", "*.json"), ("文本文件", "*.txt")),
            initialfile=f"{self.active_module.name.removesuffix('模块')}_分析报告.json",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as file:
                if path.lower().endswith(".txt"):
                    file.write(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    json.dump(report, file, ensure_ascii=False, indent=2)
            self._append_log(f"分析报告已导出：{path}")
            self.status_var.set("分析报告导出完成")
        except OSError as exc:
            self.status_var.set(f"报告导出失败：{exc}")

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"{timestamp}  {message}")
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        self._refresh_log_widget()

    def _refresh_log_widget(self) -> None:
        if not hasattr(self, "log_text") or not self.log_text.winfo_exists():
            return
        self.log_text.delete("1.0", tk.END)
        if not self.logs:
            self.log_text.insert("1.0", "等待加载数据并执行处理任务……")
        else:
            self.log_text.insert("1.0", "\n".join(self.logs))
            self.log_text.see(tk.END)

    def _select_module(self, module: ModuleSpec, keep_page: bool = False) -> None:
        self.active_module = module
        self.module_title.set(module.name)
        self.module_desc.set(module.description)
        if hasattr(self, "group_badge") and self.group_badge.winfo_exists():
            self.group_badge.configure(text=module.group)
        self.status_var.set(f"当前模块：{module.name}")
        self.run_status_var.set("待处理")
        self.run_completed = False
        self.param_values = {}
        if not keep_page:
            self.current_page = "工作台"
        self._append_log(f"已切换模块：{module.name}")
        self._refresh_menu()
        self._render_progress_strip()
        self._render_current_page()

    def _refresh_menu(self) -> None:
        active_name = self.active_module.name
        for button in self.menu_buttons:
            active = getattr(button, "module_name", "") == active_name
            button.configure(
                bg=self.TEAL if active else self.SIDEBAR_ITEM,
                fg="#ffffff",
                font=(self.font_family, 9, "bold" if active else "normal"),
            )

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self, bg="#dde9e6", height=27)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(0, weight=1)
        tk.Label(bar, textvariable=self.status_var, bg="#dde9e6", fg="#516660", anchor="w", padx=12, font=self.small_font).grid(
            row=0, column=0, sticky="nsew"
        )
        tk.Label(bar, text="地质模型转换工作台 · MySQL 与算法服务接口已预留", bg="#dde9e6", fg=self.TEAL, padx=12, font=self.small_font).grid(
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