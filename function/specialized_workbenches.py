"""Distinct Tk workbenches for the eight specialized geology modules.

This mixin deliberately keeps the page composition separate from ``main.py``.
Shared widgets only cover real file/artifact/issue data; every module owns a
different information architecture and preview, so the UI does not regress to
eight copies of the same generic dashboard.
"""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any


SPECIALIZED_WORKBENCH_METHODS = {
    "坐标与基准统一模块": "_render_coordinate_workbench",
    "剖面与平面图转换模块": "_render_section_map_workbench",
    "地质解释线重建模块": "_render_boundary_reconstruction_workbench",
    "栅格与矢量转换模块": "_render_raster_vector_workbench",
    "点云数据转换模块": "_render_point_cloud_workbench",
    "地质属性映射模块": "_render_attribute_mapping_workbench",
    "多尺度模型转换模块": "_render_multiscale_workbench",
    "局部精细模型构建模块": "_render_local_detail_workbench",
}


class SpecializedWorkbenchMixin:
    """UI-only mixin; the host supplies colors, state and common callbacks."""

    def _render_specialized_workbench(self) -> None:
        method_name = SPECIALIZED_WORKBENCH_METHODS.get(self.active_module.name)
        if not method_name:
            raise ValueError(f"未登记专业模块工作台：{self.active_module.name}")
        getattr(self, method_name)()

    def _specialized_root(self, eyebrow: str, title: str, subtitle: str, accent: str) -> tk.Frame:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="ew")
        root.columnconfigure(0, weight=1)
        hero = tk.Frame(root, bg="#ffffff", highlightbackground=self.BORDER, highlightthickness=1)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hero.columnconfigure(1, weight=1)
        tk.Frame(hero, bg=accent, width=7).grid(row=0, column=0, rowspan=3, sticky="ns")
        tk.Label(hero, text=eyebrow, bg="#ffffff", fg=accent, font=(self.font_family, 8, "bold"), anchor="w").grid(
            row=0, column=1, sticky="ew", padx=16, pady=(11, 1)
        )
        tk.Label(hero, text=title, bg="#ffffff", fg=self.TEXT, font=self.hero_font, anchor="w").grid(
            row=1, column=1, sticky="ew", padx=16
        )
        tk.Label(hero, text=subtitle, bg="#ffffff", fg=self.MUTED, font=self.small_font, anchor="w", justify="left", wraplength=1100).grid(
            row=2, column=1, sticky="ew", padx=16, pady=(3, 12)
        )
        state = self.run_status_var.get() if self.selected_files or self.quality_report else "空白任务"
        tk.Label(hero, text=state, bg="#edf4f2", fg=accent, font=(self.font_family, 9, "bold"), padx=12, pady=6).grid(
            row=0, column=2, rowspan=3, padx=16
        )
        return root

    def _specialized_actions(self, parent: tk.Widget, execute_text: str, accent_style: str = "Blue.TButton") -> tk.Frame:
        bar = tk.Frame(parent, bg=self.PANEL)
        ttk.Button(bar, text="添加数据", style="Primary.TButton", command=self._choose_files).pack(side="left")
        ttk.Button(bar, text="加载示例数据", style="Tool.TButton", command=self._load_specialized_sample_data).pack(side="left", padx=(7, 0))
        ttk.Button(bar, text="清空", style="Tool.TButton", command=self._clear_files).pack(side="left", padx=(7, 0))
        ttk.Button(bar, text=execute_text, style=accent_style, command=self._run_stub).pack(side="right")
        return bar

    def _specialized_file_card(self, parent: tk.Widget, title: str, empty_text: str, height: int = 7) -> tk.Frame:
        card = self._card(parent)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        self._card_header(card, title)
        tk.Label(card, text=f"已加载 {len(self.selected_files)} 个真实文件", bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=12, pady=(0, 6)
        )
        tree = ttk.Treeview(card, columns=("name", "format", "size"), show="headings", style="Dashboard.Treeview", height=height)
        for key, label, width, anchor in (
            ("name", "文件", 205, "w"), ("format", "格式", 62, "center"), ("size", "大小", 78, "e")
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor=anchor)
        tree.grid(row=2, column=0, sticky="nsew", padx=12)
        for file_name in self.selected_files:
            path = Path(file_name)
            size = path.stat().st_size if path.exists() else 0
            tree.insert("", "end", values=(path.name, path.suffix.lower() or "-", self._format_bytes(size)))
        empty_label = tk.Label(
            card,
            text=empty_text if not self.selected_files else "",
            bg="#fbfcfc", fg="#8a9d98", font=self.small_font, justify="center", wraplength=300,
        )
        empty_label.grid(row=2, column=0, padx=28, pady=35)
        if self.selected_files:
            empty_label.grid_remove()
        return card

    @staticmethod
    def _format_bytes(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.1f} MB"

    def _specialized_canvas_card(self, parent: tk.Widget, title: str, kind: str, height: int = 280) -> tk.Frame:
        card = self._card(parent)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        self._card_header(card, title)
        canvas = tk.Canvas(card, bg="#fbfcfc", highlightthickness=0, height=height)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        canvas.bind("<Configure>", lambda _event, c=canvas, k=kind: self._draw_specialized_preview(c, k))
        return card

    def _specialized_issue_card(self, parent: tk.Widget, title: str, empty_text: str, height: int = 6) -> tk.Frame:
        card = self._card(parent)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        self._card_header(card, title)
        tree = ttk.Treeview(card, columns=("level", "code", "message"), show="headings", style="Dashboard.Treeview", height=height)
        for key, label, width in (("level", "级别", 58), ("code", "问题码", 130), ("message", "说明", 360)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        issues = self.quality_report.get("issues", []) if isinstance(self.quality_report, dict) else []
        for issue in issues:
            if isinstance(issue, dict):
                tree.insert("", "end", values=(issue.get("severity", ""), issue.get("code", ""), issue.get("message", "")))
        if not issues:
            tree.insert("", "end", values=("-", "-", empty_text))
        return card

    def _specialized_artifact_card(self, parent: tk.Widget, title: str, height: int = 6) -> tk.Frame:
        card = self._card(parent)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        self._card_header(card, title)
        tree = ttk.Treeview(card, columns=("name", "size", "hash"), show="headings", style="Dashboard.Treeview", height=height)
        for key, label, width in (("name", "成果", 250), ("size", "大小", 75), ("hash", "SHA-256", 150)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        artifacts = self.quality_report.get("artifacts", []) if isinstance(self.quality_report, dict) else []
        for item in artifacts:
            if isinstance(item, dict):
                tree.insert("", "end", values=(item.get("name", ""), self._format_bytes(int(item.get("size_bytes", 0) or 0)), str(item.get("sha256", ""))[:16]))
        if not artifacts:
            tree.insert("", "end", values=("尚未生成成果", "-", "-"))
        return card

    def _specialized_summary(self, parent: tk.Widget, items: tuple[tuple[str, str, str, str], ...]) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.BG)
        for index in range(len(items)):
            frame.columnconfigure(index, weight=1)
        for index, item in enumerate(items):
            self._metric_card(frame, *item).grid(
                row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 4, 0 if index == len(items) - 1 else 4)
            )
        return frame

    def _report_metric(self, key: str, default: Any = "--") -> Any:
        if not isinstance(self.quality_report, dict):
            return default
        metrics = self.quality_report.get("metrics", {})
        return metrics.get(key, default) if isinstance(metrics, dict) else default

    def _parameter_card(self, parent: tk.Widget, title: str, rows: tuple[tuple[str, str], ...], accent: str) -> tk.Frame:
        card = self._card(parent)
        card.columnconfigure(0, weight=1)
        self._card_header(card, title)
        body = tk.Frame(card, bg=self.PANEL)
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        body.columnconfigure(1, weight=1)
        defaults = self._parameter_defaults()
        for index, (label, parameter) in enumerate(rows):
            tk.Label(body, text=label, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").grid(row=index, column=0, sticky="w", pady=4)
            value = self.param_values.get(parameter, defaults.get(parameter, "待配置"))
            tk.Label(body, text=value, bg="#f5f8f7", fg=accent, font=(self.font_family, 8, "bold"), anchor="w", padx=8, pady=5).grid(
                row=index, column=1, sticky="ew", padx=(8, 0), pady=2
            )
        return card

    # ------------------------------------------------------------------
    # Eight genuinely different workbench compositions

    def _render_coordinate_workbench(self) -> None:
        root = self._specialized_root(
            "SPATIAL REFERENCE CONTROL", "坐标、基准与里程统一",
            "登记多来源坐标参考，统一平面坐标、高程基准、长度单位和工程里程，并对转换残差进行闭环检查。", self.TEAL,
        )
        report_ready = isinstance(self.quality_report, dict)
        self._specialized_summary(root, (
            ("来源文件", str(len(self.selected_files)) if self.selected_files else "--", "不同测区/坐标参考", self.TEAL),
            ("目标坐标系", str(self.param_values.get("目标坐标系", "--")) if self.selected_files else "--", "平面基准", self.BLUE),
            ("转换点", str(self._report_metric("converted_points")), "含高程与里程", self.PURPLE),
            ("最大残差", f"{self._report_metric('max_numeric_residual')}" if report_ready else "--", "与容差联检", self.ORANGE),
        )).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        body = tk.Frame(root, bg=self.BG)
        body.grid(row=2, column=0, sticky="ew")
        body.columnconfigure(0, weight=36)
        body.columnconfigure(1, weight=64)
        files = self._specialized_file_card(body, "多来源空间数据登记", "尚未加载坐标数据\n可添加 CSV、GeoJSON、OBJ 或加载示例数据", 8)
        files.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_actions(files, "执行基准统一", "Blue.TButton").grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        preview = self._specialized_canvas_card(body, "源参考系 → 目标参考系与残差视图", "coordinate", 300)
        preview.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        stages = tk.Frame(root, bg=self.BG)
        stages.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for index in range(4):
            stages.columnconfigure(index, weight=1)
        cards = (
            ("01 平面坐标", "识别 EPSG/工程仿射", "目标坐标系", self.TEAL),
            ("02 高程基准", "垂向改正与基准说明", "目标高程基准", self.BLUE),
            ("03 单位与里程", "长度单位、链桩号连续性", "单位体系", self.PURPLE),
            ("04 精度复核", "控制点残差与容差判定", "转换精度", self.ORANGE),
        )
        defaults = self._parameter_defaults()
        for index, (title, note, key, accent) in enumerate(cards):
            card = self._card(stages)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 4, 0 if index == 3 else 4))
            tk.Frame(card, bg=accent, height=4).pack(fill="x")
            tk.Label(card, text=title, bg=self.PANEL, fg=self.TEXT, font=(self.font_family, 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(9, 2))
            tk.Label(card, text=note, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").pack(fill="x", padx=12)
            tk.Label(card, text=self.param_values.get(key, defaults.get(key, "--")), bg=self.PANEL, fg=accent, font=(self.font_family, 8, "bold"), anchor="w").pack(fill="x", padx=12, pady=(5, 10))

    def _render_section_map_workbench(self) -> None:
        root = self._specialized_root(
            "2D TO 3D GEOLOGICAL POSITIONING", "剖面与平面图协同转换",
            "将剖面里程—高程线划与平面地质图层分区管理，通过控制点和基线进行三维定位，并独立显示拓扑检查结果。", self.BLUE,
        )
        work = tk.Frame(root, bg=self.BG)
        work.grid(row=1, column=0, sticky="ew")
        work.columnconfigure(0, weight=27)
        work.columnconfigure(1, weight=46)
        work.columnconfigure(2, weight=27)
        layers = self._specialized_file_card(work, "图件与图层栈", "图层栈为空\n等待剖面线、平面图斑和控制点", 10)
        layers.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_actions(layers, "定位并矢量化", "Blue.TButton").grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        canvas = self._specialized_canvas_card(work, "剖面里程-高程 / 平面 XY 联动定位", "section_map", 340)
        canvas.grid(row=0, column=1, sticky="nsew", padx=5)
        right = tk.Frame(work, bg=self.BG)
        right.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        right.columnconfigure(0, weight=1)
        self._parameter_card(right, "空间定位控制", (
            ("矢量精度", "矢量化精度"), ("定位方式", "空间定位方式"), ("图层规则", "图层映射"), ("拓扑规则", "拓扑规则"),
        ), self.BLUE).grid(row=0, column=0, sticky="ew")
        metrics = self._card(right)
        metrics.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._card_header(metrics, "拓扑即时状态")
        values = (
            ("输出要素", self._report_metric("output_features")),
            ("未闭合环", self._report_metric("open_rings")),
            ("近重复点", self._report_metric("near_duplicate_vertices")),
            ("无效短线", self._report_metric("invalid_short_parts")),
        )
        for index, (label, value) in enumerate(values):
            tk.Label(metrics, text=label, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").grid(row=index + 1, column=0, sticky="w", padx=12, pady=5)
            tk.Label(metrics, text=str(value), bg=self.PANEL, fg=self.BLUE, font=(self.font_family, 9, "bold")).grid(row=index + 1, column=1, sticky="e", padx=12)
        bottom = tk.Frame(root, bg=self.BG)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=55)
        bottom.columnconfigure(1, weight=45)
        self._specialized_issue_card(bottom, "拓扑问题定位", "尚未执行拓扑检查", 5).grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_artifact_card(bottom, "三维定位成果", 5).grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    def _render_boundary_reconstruction_workbench(self) -> None:
        root = self._specialized_root(
            "BOUNDARY GRAPH RECONSTRUCTION", "地质解释线网络重建",
            "按地层界线、断层和接触关系分组识别断点，执行端点匹配、方向纠正与平滑，保留每条边界的重建来源。", self.ORANGE,
        )
        strip = self._specialized_summary(root, (
            ("原始分段", str(self._report_metric("source_segments")), "解释线片段", self.ORANGE),
            ("已连接断口", str(self._report_metric("joined_gaps")), "容差内自动重连", self.GREEN),
            ("重建边界", str(self._report_metric("reconstructed_parts")), "三维连续线", self.BLUE),
            ("异常端点", str(self._report_metric("anomaly_endpoints")), "留待人工复核", self.RED),
        ))
        strip.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        work = tk.Frame(root, bg=self.BG)
        work.grid(row=2, column=0, sticky="ew")
        work.columnconfigure(0, weight=30)
        work.columnconfigure(1, weight=48)
        work.columnconfigure(2, weight=22)
        files = self._specialized_file_card(work, "解释线分段队列", "暂无地层界线、断层线或接触线", 9)
        files.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_actions(files, "执行边界重建", "Orange.TButton").grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        self._specialized_canvas_card(work, "断裂网络：原始断点与重建连线", "boundary", 330).grid(row=0, column=1, sticky="nsew", padx=5)
        self._parameter_card(work, "重建算法栈", (
            ("算法", "重建算法"), ("平滑", "平滑参数"), ("连接容差", "连接容差"), ("地质约束", "边界约束"),
        ), self.ORANGE).grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        self._specialized_issue_card(root, "异常断点与重建质量", "尚未检测断点；执行后显示超容差端点", 6).grid(
            row=3, column=0, sticky="ew", pady=(8, 0)
        )

    def _render_raster_vector_workbench(self) -> None:
        root = self._specialized_root(
            "RASTER ↔ VECTOR CONVERSION", "栅格与矢量双向转换",
            "左侧管理遥感/DEM 像元场，右侧管理地质图斑与专题边界；转换方向、分辨率、阈值和属性字段分别控制。", self.PURPLE,
        )
        files = self._specialized_file_card(root, "混合图层输入（栅格 + 矢量）", "尚未加载栅格或矢量图层", 5)
        files.grid(row=1, column=0, sticky="ew")
        self._specialized_actions(files, "执行双向转换", "Purple.TButton").grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        conversion = tk.Frame(root, bg=self.BG)
        conversion.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        conversion.columnconfigure(0, weight=45)
        conversion.columnconfigure(1, weight=10)
        conversion.columnconfigure(2, weight=45)
        self._specialized_canvas_card(conversion, "遥感 / DEM 像元视图", "raster", 285).grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        bridge = self._card(conversion)
        bridge.grid(row=0, column=1, sticky="nsew", padx=4)
        tk.Label(bridge, text="⇄", bg=self.PANEL, fg=self.PURPLE, font=(self.font_family, 24, "bold")).pack(pady=(45, 6))
        tk.Label(bridge, text=self.param_values.get("转换方向", "自动双向"), bg=self.PANEL, fg=self.TEXT, font=self.tiny_font, wraplength=90).pack()
        tk.Label(bridge, text=f"分辨率\n{self.param_values.get('分辨率', '10')}", bg="#f3efff", fg=self.PURPLE, font=(self.font_family, 8, "bold"), pady=8).pack(fill="x", padx=8, pady=12)
        tk.Label(bridge, text=f"阈值\n{self.param_values.get('边界提取阈值', '1')}", bg="#fff4e5", fg=self.ORANGE, font=(self.font_family, 8, "bold"), pady=8).pack(fill="x", padx=8)
        self._specialized_canvas_card(conversion, "地质图斑 / 专题边界视图", "vector", 285).grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        report = tk.Frame(root, bg=self.BG)
        report.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        report.columnconfigure(0, weight=50)
        report.columnconfigure(1, weight=50)
        self._specialized_issue_card(report, "空间精度与边界问题", "尚未生成空间精度报告", 5).grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_artifact_card(report, "栅格/矢量成果", 5).grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    def _render_point_cloud_workbench(self) -> None:
        root = self._specialized_root(
            "3D POINT CLOUD PIPELINE", "三维点云标准化与分类",
            "针对激光扫描、摄影测量和监测点云，集中展示点密度、体素重采样、分类覆盖和模型输出，不沿用二维图件界面。", self.TEAL,
        )
        self._specialized_summary(root, (
            ("输入点", str(self._report_metric("input_points")), "原始采集点", self.BLUE),
            ("输出点", str(self._report_metric("output_points")), "抽稀/重采样后", self.TEAL),
            ("保留率", f"{float(self._report_metric('retention_ratio', 0) or 0):.1%}" if self.quality_report else "--", "密度变化", self.ORANGE),
            ("分类数", str(len(self._report_metric("classes", {}) or {})) if self.quality_report else "--", "地面/坡面/高位目标", self.PURPLE),
        )).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        work = tk.Frame(root, bg=self.BG)
        work.grid(row=2, column=0, sticky="ew")
        work.columnconfigure(0, weight=66)
        work.columnconfigure(1, weight=34)
        cloud = self._specialized_canvas_card(work, "点云分类视口（按类别着色）", "point_cloud", 370)
        cloud.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_actions(cloud, "执行点云转换", "Blue.TButton").grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 11))
        right = tk.Frame(work, bg=self.BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right.columnconfigure(0, weight=1)
        files = self._specialized_file_card(right, "点云数据源", "点云视口为空\n添加 CSV/PLY 或加载示例数据", 5)
        files.grid(row=0, column=0, sticky="ew")
        pipeline = self._card(right)
        pipeline.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._card_header(pipeline, "处理流水线")
        defaults = self._parameter_defaults()
        steps = (
            ("1", "体素抽稀", "抽稀比例", self.BLUE),
            ("2", "空间重采样", "重采样间距", self.TEAL),
            ("3", "规则/分位分类", "分类规则", self.ORANGE),
            ("4", "标准点云输出", "输出格式", self.PURPLE),
        )
        for index, (number, label, key, color) in enumerate(steps):
            tk.Label(pipeline, text=number, bg=color, fg="#ffffff", font=(self.font_family, 8, "bold"), width=3, pady=4).grid(row=index + 1, column=0, padx=(12, 8), pady=5)
            tk.Label(pipeline, text=label, bg=self.PANEL, fg=self.TEXT, font=(self.font_family, 8, "bold"), anchor="w").grid(row=index + 1, column=1, sticky="w")
            tk.Label(pipeline, text=self.param_values.get(key, defaults.get(key, "--")), bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="e").grid(row=index + 1, column=2, sticky="e", padx=12)
        bottom = tk.Frame(root, bg=self.BG)
        bottom.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=45)
        bottom.columnconfigure(1, weight=55)
        self._specialized_artifact_card(bottom, "标准点云与分类成果", 5).grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_issue_card(bottom, "密度、噪声与分类检查", "尚未执行点云质量检查", 5).grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    def _render_attribute_mapping_workbench(self) -> None:
        root = self._specialized_root(
            "ATTRIBUTE INTERPOLATION & LINEAGE", "地质属性映射与来源追溯",
            "将属性样本、目标单元和插值参数分栏管理；岩性等分类属性使用最近邻，连续参数支持 IDW，并逐单元记录样本来源。", self.GREEN,
        )
        work = tk.Frame(root, bg=self.BG)
        work.grid(row=1, column=0, sticky="ew")
        work.columnconfigure(0, weight=27)
        work.columnconfigure(1, weight=45)
        work.columnconfigure(2, weight=28)
        files = self._specialized_file_card(work, "样本与目标单元", "暂无属性样本或模型单元", 9)
        files.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_actions(files, "执行属性映射", "Primary.TButton").grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        self._specialized_canvas_card(work, "样本搜索半径与单元映射关系", "attribute", 340).grid(row=0, column=1, sticky="nsew", padx=5)
        right = tk.Frame(work, bg=self.BG)
        right.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        right.columnconfigure(0, weight=1)
        self._parameter_card(right, "插值与追溯配置", (
            ("映射字段", "映射字段"), ("插值方法", "插值方法"), ("搜索半径", "搜索半径"), ("追溯标识", "追溯标识"),
        ), self.GREEN).grid(row=0, column=0, sticky="ew")
        coverage = self._card(right)
        coverage.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._card_header(coverage, "字段覆盖")
        mapped = int(self._report_metric("mapped_values", 0) or 0)
        missing = int(self._report_metric("unmapped_values", 0) or 0)
        total = mapped + missing
        ratio = mapped / total if total else 0.0
        tk.Label(coverage, text=f"{ratio:.1%}" if self.quality_report else "--", bg=self.PANEL, fg=self.GREEN, font=(self.font_family, 24, "bold")).grid(
            row=1, column=0, sticky="ew", pady=(5, 0)
        )
        tk.Label(coverage, text=f"已映射 {mapped} · 未映射 {missing}" if self.quality_report else "执行后显示逐字段覆盖率", bg=self.PANEL, fg=self.MUTED, font=self.tiny_font).grid(
            row=2, column=0, sticky="ew", pady=(0, 12)
        )
        bottom = tk.Frame(root, bg=self.BG)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=58)
        bottom.columnconfigure(1, weight=42)
        self._specialized_artifact_card(bottom, "属性化模型与映射关系表", 6).grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_issue_card(bottom, "缺失属性与搜索半径问题", "尚未执行属性映射", 6).grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    def _render_multiscale_workbench(self) -> None:
        root = self._specialized_root(
            "REGIONAL → ENGINEERING → LOCAL", "多尺度模型转换与精度平衡",
            "以尺度链而非普通文件转换组织界面，对区域、工程、局部精细模型分别展示面数、裁剪范围、抽稀/加密策略与几何误差。", self.BLUE,
        )
        scale_row = tk.Frame(root, bg=self.BG)
        scale_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for index in range(5):
            scale_row.columnconfigure(index, weight=1 if index in {0, 2, 4} else 0)
        scales = (
            (0, "区域尺度", "全域模型 / 高吞吐", self.TEAL),
            (2, "工程尺度", "裁剪抽稀 / 平衡精度", self.BLUE),
            (4, "局部精细", "关键部位 / 局部加密", self.PURPLE),
        )
        for column, title, note, accent in scales:
            card = self._card(scale_row)
            card.grid(row=0, column=column, sticky="nsew")
            tk.Label(card, text=title, bg=self.PANEL, fg=accent, font=(self.font_family, 12, "bold")).pack(pady=(12, 2))
            tk.Label(card, text=note, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font).pack(pady=(0, 12))
        for column in (1, 3):
            tk.Label(scale_row, text="→", bg=self.BG, fg="#9ab0aa", font=(self.font_family, 19, "bold")).grid(row=0, column=column, padx=12)
        work = tk.Frame(root, bg=self.BG)
        work.grid(row=2, column=0, sticky="ew")
        work.columnconfigure(0, weight=34)
        work.columnconfigure(1, weight=66)
        files = self._specialized_file_card(work, "源尺度模型与裁剪配置", "暂无区域/工程 OBJ 模型或尺度配置", 7)
        files.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._parameter_card(files, "尺度策略", (
            ("目标尺度", "目标尺度"), ("抽稀", "抽稀策略"), ("加密", "加密规则"), ("精度", "精度保留策略"),
        ), self.BLUE).grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 8))
        self._specialized_actions(files, "执行尺度转换", "Blue.TButton").grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 11))
        self._specialized_canvas_card(work, "裁剪框、网格密度与尺度误差对比", "multiscale", 355).grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        bottom = tk.Frame(root, bg=self.BG)
        bottom.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=50)
        bottom.columnconfigure(1, weight=50)
        self._specialized_artifact_card(bottom, "各尺度模型成果", 5).grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_issue_card(bottom, "精度保留与模型有效性", "尚未执行尺度精度比较", 5).grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    def _render_local_detail_workbench(self) -> None:
        root = self._specialized_root(
            "ROI-DRIVEN DETAIL MODELING", "重点工程部位局部精细建模",
            "围绕断层破碎带、洞室、边坡和隧道圈定 ROI，分级细化网格并检查过渡带、退化面、非流形边和局部边界贴合。", self.RED,
        )
        chips = tk.Frame(root, bg=self.BG)
        chips.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for index, (name, color) in enumerate((
            ("断层破碎带", self.RED), ("地下洞室", self.PURPLE), ("边坡关键区", self.ORANGE), ("隧道交叉区", self.BLUE),
        )):
            tk.Label(chips, text=name, bg="#ffffff", fg=color, font=(self.font_family, 9, "bold"), padx=18, pady=9, highlightbackground=color, highlightthickness=1).pack(side="left", padx=(0 if index == 0 else 5, 0))
        work = tk.Frame(root, bg=self.BG)
        work.grid(row=2, column=0, sticky="ew")
        work.columnconfigure(0, weight=68)
        work.columnconfigure(1, weight=32)
        mesh = self._specialized_canvas_card(work, "基础网格、ROI 边界与局部加密区", "local_detail", 390)
        mesh.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_actions(mesh, "构建局部精细模型", "Orange.TButton").grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 11))
        right = tk.Frame(work, bg=self.BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right.columnconfigure(0, weight=1)
        files = self._specialized_file_card(right, "基础模型与 ROI", "尚未加载基础网格和重点区域配置", 5)
        files.grid(row=0, column=0, sticky="ew")
        self._parameter_card(right, "局部细化控制", (
            ("加密级别", "加密级别"), ("局部边界", "局部边界"), ("细化方法", "细化方法"), ("过渡策略", "过渡区策略"),
        ), self.RED).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        quality = self._card(right)
        quality.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._card_header(quality, "局部网格质量")
        model_metrics = self._report_metric("models", [])
        latest = model_metrics[0] if isinstance(model_metrics, list) and model_metrics else {}
        for index, (label, key) in enumerate((
            ("面增长率", "face_growth_ratio"), ("退化面", "degenerate_faces"), ("非流形边", "non_manifold_edges"), ("最小边长", "min_edge_length"),
        )):
            tk.Label(quality, text=label, bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, anchor="w").grid(row=index + 1, column=0, sticky="w", padx=12, pady=5)
            value = latest.get(key, "--") if isinstance(latest, dict) else "--"
            tk.Label(quality, text=f"{value:.2f}" if isinstance(value, float) else str(value), bg=self.PANEL, fg=self.RED, font=(self.font_family, 9, "bold")).grid(row=index + 1, column=1, sticky="e", padx=12)
        bottom = tk.Frame(root, bg=self.BG)
        bottom.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=45)
        bottom.columnconfigure(1, weight=55)
        self._specialized_artifact_card(bottom, "局部精细模型成果", 5).grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._specialized_issue_card(bottom, "过渡区与网格质量问题", "尚未执行局部质量检查", 5).grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    # ------------------------------------------------------------------
    # Feature-specific blank/result canvases

    def _draw_specialized_preview(self, canvas: tk.Canvas, kind: str) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(1, 1, width - 2, height - 2, fill="#fbfcfc", outline="#d8e3e0")
        if not self.selected_files:
            messages = {
                "coordinate": "坐标转换视图为空\n等待多来源坐标与基准配置",
                "section_map": "剖面/平面联动视图为空\n等待线划、图斑和控制点",
                "boundary": "边界网络为空\n等待地层界线、断层与接触关系",
                "raster": "栅格视图为空\n等待遥感影像或 DEM",
                "vector": "矢量视图为空\n等待地质图斑或专题图层",
                "point_cloud": "点云视口为空\n等待激光扫描、摄影测量或监测点云",
                "attribute": "属性映射图为空\n等待样本与面/体/网格/体素单元",
                "multiscale": "尺度对比视图为空\n等待区域/工程/局部模型",
                "local_detail": "局部网格视图为空\n等待基础模型与 ROI",
            }
            canvas.create_text(width / 2, height / 2 - 8, text=messages.get(kind, "视图为空"), fill="#81958f", font=(self.font_family, 10, "bold"), justify="center")
            canvas.create_text(width / 2, height / 2 + 42, text="添加数据或加载示例数据后显示", fill="#a4b3af", font=self.tiny_font)
            return
        if kind == "coordinate":
            self._draw_coordinate_preview(canvas, width, height)
        elif kind == "section_map":
            self._draw_section_preview(canvas, width, height)
        elif kind == "boundary":
            self._draw_boundary_preview(canvas, width, height)
        elif kind in {"raster", "vector"}:
            self._draw_raster_vector_preview(canvas, width, height, kind)
        elif kind == "point_cloud":
            self._draw_point_cloud_preview(canvas, width, height)
        elif kind == "attribute":
            self._draw_attribute_preview(canvas, width, height)
        elif kind == "multiscale":
            self._draw_multiscale_preview(canvas, width, height)
        else:
            self._draw_local_detail_preview(canvas, width, height)

    def _draw_coordinate_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        split = width * 0.48
        for origin_x, color, title in ((55, "#7f9690", "源坐标参考"), (split + 45, self.TEAL, "统一目标参考")):
            canvas.create_text(origin_x, 24, text=title, anchor="w", fill=color, font=(self.font_family, 9, "bold"))
            canvas.create_line(origin_x, height - 48, origin_x + min(210, width * 0.32), height - 48, fill=color, width=2, arrow="last")
            canvas.create_line(origin_x, height - 48, origin_x, 62, fill=color, width=2, arrow="last")
            for index in range(6):
                x = origin_x + 20 + (index * 37) % max(80, int(width * 0.28))
                y = height - 72 - (index * 31) % max(70, height - 130)
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="#ffffff")
                canvas.create_text(x + 7, y - 7, text=f"P{index + 1}", fill=self.MUTED, font=(self.font_family, 7))
        canvas.create_line(split - 20, height / 2, split + 22, height / 2, fill=self.BLUE, width=3, arrow="last")
        canvas.create_text(split, height / 2 - 18, text="基准/单位/里程", fill=self.BLUE, font=self.tiny_font)
        canvas.create_text(width - 18, height - 20, text=f"文件 {len(self.selected_files)} · 点 {self._report_metric('converted_points', '待转换')}", anchor="e", fill=self.MUTED, font=self.tiny_font)

    def _draw_section_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        split = width * 0.52
        canvas.create_text(18, 22, text="剖面：里程 / 高程", anchor="w", fill=self.BLUE, font=(self.font_family, 9, "bold"))
        canvas.create_line(35, height - 40, split - 25, height - 40, fill="#9db0ab", arrow="last")
        canvas.create_line(35, height - 40, 35, 52, fill="#9db0ab", arrow="last")
        points = [(55, height - 82), (110, height - 105), (170, height - 95), (230, height - 142), (split - 45, height - 128)]
        canvas.create_line(*[value for point in points for value in point], fill=self.ORANGE, width=3, smooth=True)
        canvas.create_line(75, height - 65, 145, height - 155, 220, height - 105, split - 55, height - 175, fill=self.BLUE, width=2, smooth=True)
        canvas.create_line(split, 18, split, height - 18, fill="#d7e1de")
        canvas.create_text(split + 18, 22, text="平面：X / Y 图层", anchor="w", fill=self.TEAL, font=(self.font_family, 9, "bold"))
        canvas.create_polygon(split + 35, 65, width - 45, 55, width - 65, height - 55, split + 55, height - 72, fill="#dff1ec", outline=self.TEAL, width=2)
        canvas.create_line(split + 50, height - 85, split + 120, 105, width - 70, 78, fill=self.RED, width=3)
        for x, y in ((split + 55, height - 72), (width - 65, height - 55), (split + 35, 65)):
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=self.BLUE, outline="#ffffff")

    def _draw_boundary_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        mid = height * 0.48
        canvas.create_text(18, 23, text="原始解释线分段", anchor="w", fill=self.MUTED, font=(self.font_family, 9, "bold"))
        segments = (
            ((25, mid - 35), (width * .24, mid - 15)),
            ((width * .29, mid - 10), (width * .48, mid + 20)),
            ((width * .54, mid + 22), (width * .72, mid - 5)),
            ((width * .77, mid - 8), (width - 25, mid - 35)),
        )
        for first, second in segments:
            canvas.create_line(*first, *second, fill="#7e948e", width=3)
            canvas.create_oval(first[0] - 4, first[1] - 4, first[0] + 4, first[1] + 4, fill=self.RED, outline="")
            canvas.create_oval(second[0] - 4, second[1] - 4, second[0] + 4, second[1] + 4, fill=self.RED, outline="")
        canvas.create_line(20, mid + 58, width - 20, mid + 58, fill="#d8e3e0")
        canvas.create_text(18, mid + 78, text="重建空间边界", anchor="w", fill=self.ORANGE, font=(self.font_family, 9, "bold"))
        canvas.create_line(28, height - 52, width * .25, height - 70, width * .5, height - 45, width * .74, height - 75, width - 28, height - 58, fill=self.ORANGE, width=4, smooth=True)
        canvas.create_text(width - 18, 23, text=f"连接 {self._report_metric('joined_gaps', '--')} · 异常 {self._report_metric('anomaly_endpoints', '--')}", anchor="e", fill=self.RED, font=self.tiny_font)

    def _draw_raster_vector_preview(self, canvas: tk.Canvas, width: int, height: int, kind: str) -> None:
        if kind == "raster":
            cols, rows = 10, 7
            cell = min((width - 40) / cols, (height - 55) / rows)
            start_x, start_y = (width - cols * cell) / 2, 34
            palette = ("#eef4f2", "#cde7df", "#73b8a5", "#f3b35b", "#d96a58")
            for row in range(rows):
                for col in range(cols):
                    value = (row * 3 + col * 5 + row * col) % len(palette)
                    canvas.create_rectangle(start_x + col * cell, start_y + row * cell, start_x + (col + 1) * cell, start_y + (row + 1) * cell, fill=palette[value], outline="#ffffff")
            canvas.create_text(14, height - 16, text=f"阈值 {self.param_values.get('边界提取阈值', '1')} · 分辨率 {self.param_values.get('分辨率', '10')}", anchor="w", fill=self.MUTED, font=self.tiny_font)
        else:
            canvas.create_polygon(35, 55, width * .45, 42, width * .42, height - 60, 48, height - 42, fill="#cfe9e1", outline=self.TEAL, width=2)
            canvas.create_polygon(width * .46, 42, width - 38, 62, width - 55, height - 48, width * .44, height - 62, fill="#f5d6a6", outline=self.ORANGE, width=2)
            canvas.create_line(42, height * .66, width * .35, height * .45, width * .58, height * .52, width - 48, height * .34, fill=self.RED, width=3, smooth=True)
            canvas.create_text(15, height - 16, text=f"属性字段：{self.param_values.get('属性映射规则', 'value')}", anchor="w", fill=self.MUTED, font=self.tiny_font)

    def _draw_point_cloud_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        colors = (self.TEAL, self.ORANGE, self.PURPLE)
        for index in range(180):
            x = 28 + (index * 73) % max(60, width - 56)
            base = height - 45 - ((index * 29) % 46)
            ridge = 110 * math.exp(-((x - width * .58) / max(width * .22, 1)) ** 2)
            y = base - ridge - (index % 5) * 2
            color = colors[0] if y > height * .62 else colors[1] if y > height * .38 else colors[2]
            canvas.create_oval(x, y, x + 3, y + 3, fill=color, outline="")
        canvas.create_text(18, 20, text="● 地面", fill=self.TEAL, anchor="w", font=self.tiny_font)
        canvas.create_text(90, 20, text="● 坡面", fill=self.ORANGE, anchor="w", font=self.tiny_font)
        canvas.create_text(162, 20, text="● 高位目标", fill=self.PURPLE, anchor="w", font=self.tiny_font)
        canvas.create_text(width - 16, height - 16, text=f"输出点 {self._report_metric('output_points', '待转换')}", anchor="e", fill=self.MUTED, font=self.tiny_font)

    def _draw_attribute_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        cols, rows = 5, 3
        cell_w, cell_h = (width - 70) / cols, (height - 80) / rows
        for row in range(rows):
            for col in range(cols):
                x0, y0 = 35 + col * cell_w, 45 + row * cell_h
                fill = "#dff1eb" if (row + col) % 3 == 0 else "#edf3ff" if (row + col) % 3 == 1 else "#fff1dd"
                canvas.create_rectangle(x0, y0, x0 + cell_w - 4, y0 + cell_h - 4, fill=fill, outline="#ffffff")
                canvas.create_text(x0 + 8, y0 + 8, text=f"U{row * cols + col + 1}", anchor="nw", fill=self.MUTED, font=(self.font_family, 7))
        samples = ((width * .18, height * .36), (width * .42, height * .64), (width * .64, height * .28), (width * .83, height * .62))
        for index, (x, y) in enumerate(samples):
            radius = 28 if index == 1 else 20
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=self.GREEN, dash=(3, 2))
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=self.GREEN, outline="#ffffff")
            canvas.create_text(x + 8, y - 8, text=f"S{index + 1}", fill=self.GREEN, font=(self.font_family, 7, "bold"))
        canvas.create_text(18, 20, text=f"搜索半径 {self.param_values.get('搜索半径', '100')} · {self.param_values.get('插值方法', 'IDW')}", anchor="w", fill=self.GREEN, font=(self.font_family, 8, "bold"))

    def _draw_multiscale_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        zones = ((30, width * .31, 34, height - 38, 28, self.TEAL, "区域"), (width * .35, width * .64, 58, height - 56, 18, self.BLUE, "工程"), (width * .68, width - 30, 82, height - 72, 11, self.PURPLE, "局部"))
        for left, right, top, bottom, step, color, label in zones:
            canvas.create_rectangle(left, top, right, bottom, fill="#ffffff", outline=color, width=2)
            x = left
            while x <= right:
                canvas.create_line(x, top, x, bottom, fill="#d5e0dd")
                x += step
            y = top
            while y <= bottom:
                canvas.create_line(left, y, right, y, fill="#d5e0dd")
                y += step
            canvas.create_text((left + right) / 2, top - 13, text=f"{label}尺度", fill=color, font=(self.font_family, 8, "bold"))
        canvas.create_line(width * .315, height / 2, width * .345, height / 2, fill=self.BLUE, width=3, arrow="last")
        canvas.create_line(width * .645, height / 2, width * .675, height / 2, fill=self.PURPLE, width=3, arrow="last")
        canvas.create_text(width - 16, height - 15, text=f"最大误差 {self._report_metric('max_error', '--')}", anchor="e", fill=self.MUTED, font=self.tiny_font)

    def _draw_local_detail_preview(self, canvas: tk.Canvas, width: int, height: int) -> None:
        left, top, right, bottom = 28, 35, width - 28, height - 35
        coarse = 36
        x = left
        while x <= right:
            canvas.create_line(x, top, x, bottom, fill="#cbd8d4")
            x += coarse
        y = top
        while y <= bottom:
            canvas.create_line(left, y, right, y, fill="#cbd8d4")
            y += coarse
        roi = (width * .34, height * .28, width * .72, height * .76)
        canvas.create_rectangle(*roi, fill="#fff1ee", outline=self.RED, width=3)
        fine = 12
        x = roi[0]
        while x <= roi[2]:
            canvas.create_line(x, roi[1], x, roi[3], fill="#e9a89c")
            x += fine
        y = roi[1]
        while y <= roi[3]:
            canvas.create_line(roi[0], y, roi[2], y, fill="#e9a89c")
            y += fine
        canvas.create_text(roi[0] + 8, roi[1] + 8, text="ROI 局部加密区", anchor="nw", fill=self.RED, font=(self.font_family, 9, "bold"))
        canvas.create_line(width * .2, height * .68, width * .48, height * .54, width * .8, height * .62, fill=self.ORANGE, width=4, smooth=True)
        canvas.create_text(width - 16, 18, text=f"加密级别 {self.param_values.get('加密级别', '1')} · 过渡 {self.param_values.get('过渡区策略', '1 环')}", anchor="e", fill=self.RED, font=self.tiny_font)


__all__ = ["SPECIALIZED_WORKBENCH_METHODS", "SpecializedWorkbenchMixin"]
