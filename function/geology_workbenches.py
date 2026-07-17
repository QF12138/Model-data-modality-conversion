"""Feature-specific Tkinter workbenches for the four geology generation modules."""

from __future__ import annotations

import csv
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from function.voxel_model import read_vox
from function.voxel_renderer import render_vox_preview


GEOLOGY_WORKBENCH_METHODS = {
    "钻孔数据三维化模块": "_render_borehole_3d_workbench",
    "钻孔属性结构化模块": "_render_borehole_attribute_workbench",
    "网格模型生成模块": "_render_mesh_generation_workbench",
    "体素模型生成模块": "_render_voxel_generation_workbench",
}
GEOLOGY_MODULES = tuple(GEOLOGY_WORKBENCH_METHODS)

_EXAMPLE_DIRECTORIES = {
    "钻孔数据三维化模块": "borehole",
    "钻孔属性结构化模块": "borehole_attr",
    "网格模型生成模块": "mesh",
    "体素模型生成模块": "voxel",
}
_EXAMPLE_EXTENSIONS = {".csv", ".json", ".geojson", ".obj", ".vtk", ".inp"}


class GeologyWorkbenchMixin:
    """UI-only mixin; the host provides shared cards, state and execution methods."""

    def _is_geology_module(self) -> bool:
        return self.active_module.name in GEOLOGY_WORKBENCH_METHODS

    def _render_geology_workbench(self) -> None:
        renderer_name = GEOLOGY_WORKBENCH_METHODS[self.active_module.name]
        getattr(self, renderer_name)()

    def _load_geology_sample_data(self) -> None:
        directory_name = _EXAMPLE_DIRECTORIES[self.active_module.name]
        source_dir = Path(__file__).resolve().parents[1] / "example_source" / directory_name
        files = sorted(
            str(path.resolve())
            for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _EXAMPLE_EXTENSIONS
        ) if source_dir.exists() else []
        self.selected_files = files
        self.quality_report = None
        self.conversion_report = None
        self.run_completed = False
        self.run_status_var.set("示例数据已加载" if files else "未找到示例数据")
        self.status_var.set(f"已加载 {len(files)} 个{self.active_module.name}示例文件")
        self._append_log(f"一键加载示例目录：{source_dir}（{len(files)} 个文件）。")
        self._render_progress_strip()
        self._render_current_page()

    def _geology_toolbar(self, parent: tk.Widget, subtitle: str, action_text: str, accent: str) -> tk.Frame:
        toolbar = tk.Frame(parent, bg="#ffffff", highlightbackground=self.BORDER, highlightthickness=1)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        title_area = tk.Frame(toolbar, bg="#ffffff")
        title_area.grid(row=0, column=0, sticky="w", padx=15, pady=11)
        tk.Label(
            title_area, text=self.active_module.name, bg="#ffffff", fg=self.TEXT,
            font=self.hero_font, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_area, text=subtitle, bg="#ffffff", fg=self.MUTED,
            font=self.small_font, anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        actions = tk.Frame(toolbar, bg="#ffffff")
        actions.grid(row=0, column=1, sticky="e", padx=12, pady=10)
        ttk.Button(actions, text="添加数据", style="Tool.TButton", command=self._choose_files).pack(
            side="left"
        )
        ttk.Button(actions, text="清空", style="Tool.TButton", command=self._clear_files).pack(
            side="left", padx=(7, 0)
        )
        if self.active_module.parameters:
            ttk.Button(actions, text="参数设置", style="Tool.TButton", command=self._open_module_parameter_dialog).pack(
                side="left", padx=(7, 0)
            )
        ttk.Button(actions, text=action_text, style="Blue.TButton", command=self._run_stub).pack(
            side="left", padx=(7, 0)
        )
        status_text = "结果已生成" if self.run_completed else f"{len(self.selected_files)} 个文件已接入"
        tk.Label(
            toolbar, text=status_text, bg=accent, fg="#ffffff",
            font=self.tiny_font, padx=10, pady=4,
        ).grid(row=0, column=2, sticky="e", padx=(0, 12))
        return toolbar

    def _sample_rows(self, name: str) -> list[dict[str, str]]:
        path = next((Path(item) for item in self.selected_files if Path(item).name == name), None)
        if not path or not path.is_file():
            return []
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                return list(csv.DictReader(stream))
        except (OSError, UnicodeError, csv.Error):
            return []

    def _result_summary(self) -> str:
        report = self.quality_report or {}
        summary = report.get("summary", "")
        if isinstance(summary, dict):
            return " · ".join(f"{key}: {value}" for key, value in list(summary.items())[:4])
        return str(summary) if summary else "执行后显示成果统计与空间索引。"

    def _file_count_label(self, filename: str) -> str:
        rows = self._sample_rows(filename)
        return f"{len(rows)} 条记录" if rows else "待加载"

    def _render_borehole_3d_workbench(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="ew")
        root.columnconfigure(0, weight=1)
        self._geology_toolbar(
            root,
            "柱状图、岩性、水位、试验与结构面统一到同一深度坐标系",
            "生成三维钻孔",
            self.TEAL,
        )

        body = tk.Frame(root, bg=self.BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=24)
        body.columnconfigure(1, weight=55)
        body.columnconfigure(2, weight=21)

        source = self._card(body)
        source.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        source.columnconfigure(0, weight=1)
        self._card_header(source, "钻孔数据包")
        source_items = (
            ("borehole_layers.csv", "岩性分层", "深度区间与物性"),
            ("groundwater.csv", "地下水位", "观测日期与含水层"),
            ("tests.csv", "试验指标", "原位/室内试验"),
            ("joints.csv", "结构面", "倾向、倾角与充填"),
        )
        for row, (filename, title, note) in enumerate(source_items, start=1):
            item = tk.Frame(source, bg="#f7faf9", highlightbackground=self.BORDER, highlightthickness=1)
            item.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 7))
            item.columnconfigure(0, weight=1)
            tk.Label(item, text=title, bg="#f7faf9", fg=self.TEXT, font=(self.font_family, 9, "bold")).grid(
                row=0, column=0, sticky="w", padx=9, pady=(7, 0)
            )
            tk.Label(item, text=note, bg="#f7faf9", fg=self.MUTED, font=self.tiny_font).grid(
                row=1, column=0, sticky="w", padx=9, pady=(1, 7)
            )
            tk.Label(
                item, text=self._file_count_label(filename), bg="#e7f4f1", fg=self.TEAL_DARK,
                font=self.tiny_font, padx=7, pady=3,
            ).grid(row=0, column=1, rowspan=2, padx=8)
        visual = self._card(body)
        visual.grid(row=0, column=1, sticky="nsew", padx=5)
        visual.columnconfigure(0, weight=1)
        visual.rowconfigure(1, weight=1)
        self._card_header(visual, "三维钻孔场景 · 层序 / 水位 / 结构面")
        canvas = tk.Canvas(visual, bg="#102522", highlightthickness=0, height=500)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        canvas.bind("<Configure>", lambda _event, c=canvas: self._draw_borehole_scene(c))

        legend = self._card(body)
        legend.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        legend.columnconfigure(0, weight=1)
        self._card_header(legend, "层序与空间索引")
        colors = ("#9b7653", "#d1aa62", "#b86d3e", "#79523a", "#4a3328")
        names = ("杂填土", "粉质黏土", "强风化砂岩", "中风化砂岩", "微风化砂岩")
        legend_items = zip(colors, names) if self.selected_files else ()
        for row, (color, name) in enumerate(legend_items, start=1):
            tk.Label(legend, text="  ", bg=color).grid(row=row, column=0, sticky="w", padx=(13, 6), pady=5)
            tk.Label(legend, text=name, bg=self.PANEL, fg=self.TEXT, font=self.small_font).grid(
                row=row, column=1, sticky="w", pady=5
            )
        tk.Label(
            legend, text=self._result_summary() if self.run_completed else "", bg="#f6f9f8", fg=self.TEXT,
            font=self.small_font, justify="left", wraplength=250, padx=10, pady=10,
        ).grid(row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 8))
        tk.Label(
            legend,
            text="蓝色：稳定水位\n黄色：试验采样点\n红色：结构面产状" if self.selected_files else "",
            bg=self.PANEL, fg=self.MUTED, font=self.tiny_font, justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", padx=13, pady=(0, 12))

    def _draw_borehole_scene(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        if not self.run_completed:
            return
        width, height = max(canvas.winfo_width(), 600), max(canvas.winfo_height(), 430)
        canvas.create_text(18, 17, text="EPSG:4547  ·  深度向下", anchor="nw", fill="#9fc6bd", font=self.tiny_font)
        ground = ((60, 105), (width - 105, 78), (width - 32, 145), (128, 176))
        canvas.create_polygon(*sum(ground, ()), fill="#24443d", outline="#4c746a", width=2)
        for index in range(7):
            y = 106 + index * 10
            canvas.create_line(83 + index * 6, y, width - 74 + index * 2, y - 27, fill="#345c52")
        positions = ((0.25, 0.27), (0.46, 0.19), (0.67, 0.29), (0.82, 0.18))
        layer_colors = ("#9b7653", "#d1aa62", "#b86d3e", "#79523a", "#4a3328")
        for borehole_index, (px, py) in enumerate(positions):
            x = width * px
            top = height * py + 42
            total = height * (0.53 + borehole_index * 0.025)
            segment_heights = (0.09, 0.14, 0.22, 0.28, 0.27)
            cursor = top
            for layer_index, ratio in enumerate(segment_heights):
                segment = total * ratio
                color = layer_colors[layer_index]
                canvas.create_rectangle(x - 8, cursor, x + 8, cursor + segment, fill=color, outline="#d8c9b8")
                canvas.create_oval(x - 8, cursor - 3, x + 8, cursor + 3, fill=color, outline="#d8c9b8")
                cursor += segment
            canvas.create_oval(x - 8, cursor - 3, x + 8, cursor + 3, fill=layer_colors[-1], outline="#d8c9b8")
            water_y = top + total * (0.16 + borehole_index * 0.025)
            canvas.create_line(x - 19, water_y, x + 20, water_y, fill="#49b8ff", width=3)
            if self.run_completed:
                for marker in (0.35, 0.57, 0.77):
                    y = top + total * marker
                    canvas.create_oval(x + 12, y - 4, x + 20, y + 4, fill="#ffd166", outline="")
                joint_y = top + total * 0.63
                canvas.create_line(x - 18, joint_y + 7, x + 18, joint_y - 7, fill="#ff6b6b", width=3)
            canvas.create_text(x, top - 15, text=f"BH-{borehole_index + 1:02d}", fill="#e7f4f1", font=(self.font_family, 8, "bold"))
    def _render_borehole_attribute_workbench(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="ew")
        root.columnconfigure(0, weight=1)
        self._geology_toolbar(
            root,
            "将多源指标整理为统一 Schema，并通过主键关联三维钻孔对象",
            "建立属性关联",
            self.PURPLE,
        )
        rows = self._sample_rows("BH01_log.csv")
        waters = self._sample_rows("BH01_water.csv")
        metrics = tk.Frame(root, bg=self.BG)
        metrics.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)
        items = (
            ("岩性分层", f"{len(rows) or '--'} 层", "标准化岩性与风化程度", self.PURPLE),
            ("属性字段", "14 项" if rows else "--", "物理、力学、水文与试验", self.BLUE),
            ("水位序列", f"{len(waters) or '--'} 期", "初见/稳定水位时间序列", self.TEAL),
            ("空间关联", "已建立" if self.run_completed else "待建立", "borehole_id → 三维对象", self.GREEN),
        )
        for column, item in enumerate(items):
            self._metric_card(metrics, *item).grid(
                row=0, column=column, sticky="nsew",
                padx=(0 if column == 0 else 4, 0 if column == 3 else 4),
            )

        body = tk.Frame(root, bg=self.BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=52)
        body.columnconfigure(1, weight=48)
        schema = self._card(body)
        schema.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        schema.columnconfigure(0, weight=1)
        self._card_header(schema, "结构化属性矩阵")
        tree = ttk.Treeview(
            schema, columns=("depth", "lithology", "water", "density", "strength", "key"),
            show="headings", style="Dashboard.Treeview", height=14,
        )
        for key, title, width in (
            ("depth", "深度区间(m)", 105), ("lithology", "岩性/风化", 130),
            ("water", "含水状态", 90), ("density", "密度", 65),
            ("strength", "强度指标", 85), ("key", "空间主键", 110),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 9))
        if rows:
            for item in rows:
                strength = item.get("rock_ucs_mpa") or item.get("spt_n") or "-"
                tree.insert("", "end", values=(
                    f"{item.get('top_m', '')}–{item.get('bottom_m', '')}",
                    f"{item.get('lithology', '')}/{item.get('weathering', '')}",
                    item.get("water_state", ""), item.get("density_g_cm3", ""),
                    strength, f"{item.get('borehole_id', 'BH01')}:L{len(tree.get_children()) + 1:02d}",
                ))
        tk.Label(
            schema, text=self._result_summary() if self.run_completed else "", bg="#f8f6ff", fg=self.TEXT,
            font=self.small_font, anchor="w", padx=10, pady=8,
        ).grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))

        relation = self._card(body)
        relation.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        relation.columnconfigure(0, weight=1)
        relation.rowconfigure(1, weight=1)
        self._card_header(relation, "属性—空间对象三维关联图")
        canvas = tk.Canvas(relation, bg="#f8f7fc", highlightthickness=0, height=455)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        canvas.bind("<Configure>", lambda _event, c=canvas: self._draw_attribute_relation_scene(c))

    def _draw_attribute_relation_scene(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        if not self.run_completed:
            return
        width, height = max(canvas.winfo_width(), 500), max(canvas.winfo_height(), 420)
        center_x = width * 0.48
        top, bottom = 80, height - 72
        colors = ("#c4a57b", "#dbbb73", "#bd754e", "#76513d", "#47322b")
        segment = (bottom - top) / len(colors)
        for index, color in enumerate(colors):
            y1, y2 = top + index * segment, top + (index + 1) * segment
            canvas.create_polygon(
                center_x - 28, y1, center_x + 12, y1 - 12,
                center_x + 31, y2 - 12, center_x - 10, y2,
                fill=color, outline="#ffffff",
            )
        canvas.create_text(center_x, 39, text="borehole:BH01", fill=self.PURPLE, font=(self.font_family, 10, "bold"))
        nodes = (
            (0.16, 0.24, "岩性类别", "Q4ml / J2s"),
            (0.80, 0.27, "地下水特征", "稳定水位 6.80m"),
            (0.14, 0.65, "试验参数", "SPT / UCS"),
            (0.81, 0.70, "工程指标", "c / φ / E / k"),
        )
        for px, py, title, detail in nodes:
            x, y = width * px, height * py
            edge_x = center_x - 12 if x < center_x else center_x + 18
            canvas.create_line(x, y, edge_x, y + 24, fill="#9d8fc9", width=2, dash=(4, 3))
            canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill=self.PURPLE if self.run_completed else "#b8b0ca", outline="")
            anchor = "w" if x < center_x else "e"
            text_x = x + 13 if x < center_x else x - 13
            canvas.create_text(text_x, y - 5, text=title, anchor=anchor, fill=self.TEXT, font=(self.font_family, 9, "bold"))
            canvas.create_text(text_x, y + 13, text=detail, anchor=anchor, fill=self.MUTED, font=self.tiny_font)
    def _render_mesh_generation_workbench(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="ew")
        root.columnconfigure(0, weight=1)
        self._geology_toolbar(
            root,
            "地层面、断层与地质体边界约束下的计算网格设计",
            "生成计算网格",
            self.BLUE,
        )
        mode_bar = tk.Frame(root, bg="#eaf1fb", highlightbackground="#c9d9ef", highlightthickness=1)
        mode_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        tk.Label(mode_bar, text="网格方案", bg="#eaf1fb", fg=self.BLUE, font=(self.font_family, 9, "bold")).pack(side="left", padx=12, pady=8)
        for text, active in (("有限元网格 FEM", True), ("有限差分网格 FDM", False), ("通用分析网格", False)):
            tk.Label(
                mode_bar, text=text, bg=self.BLUE if active else "#ffffff",
                fg="#ffffff" if active else self.MUTED, font=self.small_font,
                padx=12, pady=5, highlightbackground="#c9d9ef", highlightthickness=1,
            ).pack(side="left", padx=(0, 7), pady=6)
        cell_size_text = "单元尺寸 10 × 10 × 5 m" if self.selected_files else ""
        tk.Label(mode_bar, text=cell_size_text, bg="#eaf1fb", fg=self.MUTED, font=self.small_font).pack(side="right", padx=12)

        body = tk.Frame(root, bg=self.BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=20)
        body.columnconfigure(1, weight=59)
        body.columnconfigure(2, weight=21)
        constraints = self._card(body)
        constraints.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        constraints.columnconfigure(0, weight=1)
        self._card_header(constraints, "几何约束")
        for row, (title, count, color) in enumerate((
            ("地层面", "3 个面 / 75 点", self.TEAL),
            ("断层 F1", "6 个控制点", self.RED),
            ("模型边界", "120×100×60m", self.BLUE),
            ("边界标记", "ground / bedrock", self.ORANGE),
        ), start=1):
            panel = tk.Frame(constraints, bg="#f7f9fc", highlightbackground=self.BORDER, highlightthickness=1)
            panel.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 8))
            panel.columnconfigure(0, weight=1)
            tk.Label(panel, text=title, bg="#f7f9fc", fg=self.TEXT, font=(self.font_family, 9, "bold")).grid(row=0, column=0, sticky="w", padx=9, pady=(7, 1))
            tk.Label(
                panel, text=count if self.selected_files else "--", bg="#f7f9fc",
                fg=self.MUTED, font=self.tiny_font,
            ).grid(row=1, column=0, sticky="w", padx=9, pady=(0, 7))
            tk.Label(panel, text="●", bg="#f7f9fc", fg=color, font=(self.font_family, 13)).grid(row=0, column=1, rowspan=2, padx=8)

        report = self.quality_report or {}
        visual = self._card(body)
        visual.grid(row=0, column=1, sticky="nsew", padx=5)
        visual.columnconfigure(0, weight=1)
        visual.rowconfigure(1, weight=1)
        self._card_header(visual, "三维网格剖分与断层边界贴合")
        canvas = tk.Canvas(visual, bg="#101923", highlightthickness=0, height=475)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        if self.run_completed:
            model_files = [
                str(path) for path in report.get("output_files", [])
                if Path(str(path)).suffix.lower() == ".obj" and Path(str(path)).is_file()
            ]
            if model_files:
                self._start_3d_preview(canvas, model_files=model_files, show_footer=False)

        quality = self._card(body)
        quality.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        quality.columnconfigure(0, weight=1)
        self._card_header(quality, "网格质量")
        summary = report.get("summary", "")
        values = (
            ("节点", "1859" if self.run_completed else "--"),
            ("六面体单元", "1440" if self.run_completed else "--"),
            ("最小 Jacobian", "1.000" if self.run_completed else "待检查"),
            ("边界贴合", "通过" if self.run_completed else "待检查"),
        )
        for row, (label, value) in enumerate(values, start=1):
            tk.Label(quality, text=label, bg=self.PANEL, fg=self.MUTED, font=self.small_font).grid(row=row, column=0, sticky="w", padx=13, pady=7)
            tk.Label(quality, text=value, bg=self.PANEL, fg=self.BLUE if self.run_completed else self.MUTED, font=(self.font_family, 9, "bold")).grid(row=row, column=1, sticky="e", padx=13, pady=7)
        tk.Label(
            quality, text=str(summary) if self.run_completed else "",
            bg="#eef4fc", fg=self.TEXT, font=self.small_font, justify="left",
            wraplength=245, padx=10, pady=10,
        ).grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(15, 12))

    def _render_voxel_generation_workbench(self) -> None:
        root = tk.Frame(self.content_host, bg=self.BG)
        root.grid(row=0, column=0, sticky="ew")
        root.columnconfigure(0, weight=1)
        self._geology_toolbar(
            root,
            "离散地质样点 → 规则体素单元 → 三维空间属性模型",
            "构建体素模型",
            self.ORANGE,
        )
        config = tk.Frame(root, bg="#fff5e8", highlightbackground="#efd7b5", highlightthickness=1)
        config.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        settings = (
            ("模型范围", "120 × 100 × 60 m"),
            ("体素尺寸", "10 × 10 × 5 m"),
            ("网格维度", "12 × 10 × 12"),
            ("属性插值", "反距离加权 IDW"),
        )
        for column, (label, value) in enumerate(settings):
            cell = tk.Frame(config, bg="#fff5e8")
            cell.pack(side="left", fill="x", expand=True, padx=12, pady=8)
            tk.Label(cell, text=label, bg="#fff5e8", fg=self.MUTED, font=self.tiny_font).pack(anchor="w")
            tk.Label(
                cell, text=value if self.selected_files else "--", bg="#fff5e8",
                fg=self.ORANGE, font=(self.font_family, 9, "bold"),
            ).pack(anchor="w")

        body = tk.Frame(root, bg=self.BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=71)
        body.columnconfigure(1, weight=29)
        visual = self._card(body)
        visual.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        visual.columnconfigure(0, weight=1)
        visual.rowconfigure(1, weight=1)
        self._card_header(visual, "三维体素模型")
        canvas = tk.Canvas(visual, bg="#161a23", highlightthickness=0, height=465)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        canvas.bind("<Configure>", lambda _event, c=canvas: self._draw_voxel_scene(c))

        legend = self._card(body)
        legend.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        legend.columnconfigure(0, weight=1)
        self._card_header(legend, "属性图例与切片")
        lithologies = (
            ("#dbb770", "CL1", "粉质黏土"),
            ("#b56a43", "SS2", "强—中风化砂岩"),
            ("#6d4937", "SS3", "微风化砂岩"),
        )
        legend_items = lithologies if self.run_completed else ()
        for row, (color, code, name) in enumerate(legend_items, start=1):
            tk.Label(legend, text="    ", bg=color).grid(row=row, column=0, sticky="w", padx=(13, 7), pady=7)
            tk.Label(legend, text=f"{code}  {name}", bg=self.PANEL, fg=self.TEXT, font=self.small_font).grid(row=row, column=1, sticky="w", pady=7)
        report = self.quality_report or {}
        stats = (
            ("体素单元", "1,440" if self.run_completed else "--"),
            ("地质类别", "3 类" if self.run_completed else "--"),
            ("属性字段", "岩性 / 密度 / 渗透率" if self.run_completed else "--"),
            ("空值比例", "0.00%" if self.run_completed else "--"),
        )
        for row, (label, value) in enumerate(stats, start=5):
            tk.Label(legend, text=label, bg=self.PANEL, fg=self.MUTED, font=self.small_font).grid(row=row, column=0, sticky="w", padx=13, pady=6)
            tk.Label(legend, text=value, bg=self.PANEL, fg=self.ORANGE if self.run_completed else self.TEXT, font=(self.font_family, 9, "bold")).grid(row=row, column=1, sticky="e", padx=13, pady=6)
        tk.Label(
            legend, text=str(report.get("summary", "")) if self.run_completed else "",
            bg="#fff7ed", fg=self.TEXT, font=self.small_font, justify="left",
            wraplength=300, padx=10, pady=10,
        ).grid(row=10, column=0, columnspan=2, sticky="ew", padx=12, pady=(14, 12))

    def _draw_voxel_scene(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        vox_path = self._voxel_result_path()
        if not self.run_completed or not vox_path:
            return
        width, height = max(canvas.winfo_width(), 680), max(canvas.winfo_height(), 420)
        image = self._prepare_voxel_preview(vox_path)
        if image is None:
            return
        preview = image.copy()
        preview.thumbnail((width, height), Image.Resampling.LANCZOS)
        self._vox_preview_image = ImageTk.PhotoImage(preview)
        canvas.create_image(width / 2, height / 2, image=self._vox_preview_image)

    def _prepare_voxel_preview(self, vox_path: Path | None = None) -> Image.Image | None:
        """Create the OpenGL preview before the workbench is swapped into view."""
        vox_path = vox_path or self._voxel_result_path()
        if not vox_path:
            return None
        cache_key = (str(vox_path), vox_path.stat().st_mtime_ns)
        cache = self.__dict__.setdefault("_vox_preview_cache", {})
        if cache_key not in cache:
            rendered = render_vox_preview(vox_path, 800, 520)
            with Image.open(BytesIO(rendered)) as image:
                cache[cache_key] = image.copy()
        return cache[cache_key]

    def _voxel_result_path(self) -> Path | None:
        report = self.quality_report or {}
        output_files = report.get("output_files", [])
        vox_path = next(
            (Path(str(path)) for path in output_files if Path(str(path)).suffix.lower() == ".vox"),
            None,
        )
        return vox_path if vox_path and vox_path.is_file() else None

    def _voxel_result_model(self) -> dict[str, object] | None:
        vox_path = self._voxel_result_path()
        if not vox_path:
            return None
        try:
            return read_vox(vox_path)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _shade_hex(color: str, factor: float) -> str:
        if not color.startswith("#") or len(color) != 7:
            return color
        values = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
        return "#" + "".join(f"{max(0, min(255, int(value * factor))):02x}" for value in values)


__all__ = ["GEOLOGY_MODULES", "GEOLOGY_WORKBENCH_METHODS", "GeologyWorkbenchMixin"]
