from __future__ import annotations

import csv
import json
import math
import os
import re
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================================
# 常量
# ============================================================================

# 支持批量扫描的格式
SCAN_EXTENSIONS: dict[str, list[str]] = {
    "表格": [".csv", ".txt"],
    "三维模型": [".obj", ".stl", ".ply", ".vtk"],
    "地理空间": [".geojson", ".json"],
    "点云": [".las", ".laz"],
    "BIM/IFC": [".ifc"],
    "全部": [".csv", ".txt", ".obj", ".stl", ".ply", ".vtk", ".geojson", ".json", ".las", ".laz", ".ifc"],
}

FORMAT_CATEGORY: dict[str, str] = {}
for _cat, _exts in SCAN_EXTENSIONS.items():
    if _cat != "全部":
        for _ext in _exts:
            FORMAT_CATEGORY[_ext] = _cat

JOB_STATUSES = ("排队中", "运行中", "已完成", "部分失败", "已失败", "已取消")
RETRY_STRATEGIES = ("立即重试", "延迟重试", "跳过", "中止")

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class FileEntry:
    """扫描到的文件条目。"""
    path: str
    name: str = ""
    suffix: str = ""
    category: str = "未知"
    size_bytes: int = 0
    selected: bool = True

    def __post_init__(self):
        if not self.name:
            self.name = Path(self.path).name
        if not self.suffix:
            self.suffix = Path(self.path).suffix.lower()
        if self.category == "未知":
            self.category = FORMAT_CATEGORY.get(self.suffix, "未知")


@dataclass
class BatchConfig:
    """批次配置。"""
    name: str = ""
    directories: list[str] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=lambda: ["*"])
    format_category: str = "全部"           # 全部 / 表格 / 三维模型 / 地理空间 / 点云 / BIM/IFC
    recursive: bool = True
    max_files: int = 500
    template_name: str = ""                 # 绑定的规则模板
    target_format: str = "OBJ"
    coordinate_rule: str = "保留源坐标"
    attribute_rule: str = "全部保留"
    output_dir: str = ""


@dataclass
class RetryPolicy:
    """失败重试策略。"""
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    strategy: str = "立即重试"              # 立即重试 / 延迟重试 / 跳过 / 中止
    retryable_errors: list[str] = field(default_factory=lambda: ["超时", "连接", "I/O", "临时"])


@dataclass
class JobLogEntry:
    """作业日志条目。"""
    timestamp: str
    level: str                              # DEBUG / INFO / WARNING / ERROR
    file_name: str = ""
    message: str = ""


@dataclass
class BatchJob:
    """批量转换作业。"""
    job_id: str
    name: str
    config: BatchConfig = field(default_factory=BatchConfig)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    status: str = "排队中"
    files: list[FileEntry] = field(default_factory=list)
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    retried: int = 0
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    progress_pct: float = 0.0
    logs: list[JobLogEntry] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


# ============================================================================
# 作业管理器
# ============================================================================

class BatchJobManager:
    """批量转换作业管理器 —— 单例风格的任务队列。"""

    def __init__(self) -> None:
        self._jobs: dict[str, BatchJob] = {}
        self._queue: list[str] = []          # job_id 列表（FIFO）
        self._counter: int = 0

    # ---- CRUD ----

    def create_job(
        self,
        name: str,
        config: BatchConfig,
        retry_policy: RetryPolicy | None = None,
    ) -> BatchJob:
        self._counter += 1
        job_id = f"BATCH-{datetime.now().strftime('%Y%m%d')}-{self._counter:04d}"
        job = BatchJob(
            job_id=job_id,
            name=name,
            config=config,
            retry_policy=retry_policy or RetryPolicy(),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        job.files = scan_directories(config)
        job.total = len(job.files)
        job.logs.append(JobLogEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            level="INFO", message=f"作业已创建，扫描到 {job.total} 个文件。",
        ))
        self._jobs[job_id] = job
        return job

    def submit(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status != "排队中":
            return False
        self._queue.append(job_id)
        job.logs.append(JobLogEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            level="INFO", message="已加入执行队列。",
        ))
        return True

    def get_job(self, job_id: str) -> BatchJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[BatchJob]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status in ("已完成", "已取消"):
            return False
        job.status = "已取消"
        job.finished_at = datetime.now().isoformat(timespec="seconds")
        job.logs.append(JobLogEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            level="WARNING", message="作业已被取消。",
        ))
        if job_id in self._queue:
            self._queue.remove(job_id)
        return True

    def delete_job(self, job_id: str) -> bool:
        if job_id in self._queue:
            self._queue.remove(job_id)
        return self._jobs.pop(job_id, None) is not None

    # ---- 模拟执行 ----

    def run_job(self, job_id: str) -> BatchJob | None:
        """模拟执行一个批量转换作业（纯 Python 环境下的占位实现）。"""
        job = self._jobs.get(job_id)
        if not job:
            return None

        job.status = "运行中"
        job.started_at = datetime.now().isoformat(timespec="seconds")
        job.logs.append(JobLogEntry(
            timestamp=job.started_at, level="INFO",
            message=f"开始执行批量转换，共 {job.total} 个文件。",
        ))

        results = _simulate_batch_run(job)
        job.status = results["status"]
        job.processed = results["processed"]
        job.success = results["success"]
        job.failed = results["failed"]
        job.skipped = results["skipped"]
        job.retried = results["retried"]
        job.progress_pct = 1.0 if job.processed >= job.total else job.processed / max(job.total, 1)
        job.finished_at = datetime.now().isoformat(timespec="seconds")
        job.outputs = results["outputs"]
        job.errors = results["errors"]

        for log_entry in results["logs"]:
            job.logs.append(JobLogEntry(**log_entry))

        job.logs.append(JobLogEntry(
            timestamp=job.finished_at, level="INFO",
            message=f"作业完成：成功 {job.success} / 失败 {job.failed} / 跳过 {job.skipped}。",
        ))
        return job

    def run_all_queued(self) -> list[BatchJob]:
        """按 FIFO 顺序执行队列中所有作业。"""
        results: list[BatchJob] = []
        while self._queue:
            job_id = self._queue.pop(0)
            job = self.run_job(job_id)
            if job:
                results.append(job)
        return results

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    @property
    def stats(self) -> dict[str, int]:
        all_jobs = list(self._jobs.values())
        return {
            "total": len(all_jobs),
            "queued": sum(1 for j in all_jobs if j.status == "排队中"),
            "running": sum(1 for j in all_jobs if j.status == "运行中"),
            "completed": sum(1 for j in all_jobs if j.status == "已完成"),
            "failed": sum(1 for j in all_jobs if j.status in ("已失败", "部分失败")),
            "cancelled": sum(1 for j in all_jobs if j.status == "已取消"),
        }


# 全局单例
_manager = BatchJobManager()


def get_manager() -> BatchJobManager:
    return _manager


# ============================================================================
# 目录扫描
# ============================================================================

def scan_directories(config: BatchConfig) -> list[FileEntry]:
    """按配置扫描目录，返回符合条件的文件条目列表。"""
    files: list[FileEntry] = []
    extensions = SCAN_EXTENSIONS.get(config.format_category, SCAN_EXTENSIONS["全部"])

    for directory in config.directories:
        base = Path(directory).expanduser()
        if not base.exists():
            continue

        if config.recursive:
            walker = base.rglob
        else:
            walker = base.glob

        for pattern in config.file_patterns:
            for path in walker(pattern):
                if path.is_file() and path.suffix.lower() in extensions:
                    files.append(FileEntry(
                        path=str(path.resolve()),
                        size_bytes=path.stat().st_size,
                    ))
                if len(files) >= config.max_files:
                    break
            if len(files) >= config.max_files:
                break
        if len(files) >= config.max_files:
            break

    return sorted(files, key=lambda f: (f.category, f.name))


def scan_directory_flat(directory: str | Path, recursive: bool = True, max_files: int = 500) -> list[FileEntry]:
    """快速扫描单个目录。"""
    config = BatchConfig(directories=[str(directory)], recursive=recursive, max_files=max_files)
    return scan_directories(config)


# ============================================================================
# 模拟批量执行
# ============================================================================

def _simulate_batch_run(job: BatchJob) -> dict[str, Any]:
    """模拟执行批量转换，生成接近真实的结果报告。"""
    processed = 0
    success = 0
    failed = 0
    skipped = 0
    retried = 0
    logs: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    outputs: list[str] = []
    t0 = datetime.now().isoformat(timespec="seconds")

    for idx, file_entry in enumerate(job.files):
        if not file_entry.selected:
            skipped += 1
            logs.append({"timestamp": _ts(), "level": "INFO", "file_name": file_entry.name, "message": "已跳过（未选中）。"})
            continue

        processed += 1
        suffix = file_entry.suffix

        # 模拟不同格式的转换成功率
        success_rate = {
            ".obj": 0.92, ".stl": 0.90, ".ply": 0.88, ".vtk": 0.85,
            ".geojson": 0.95, ".json": 0.93, ".csv": 0.96, ".txt": 0.94,
            ".las": 0.80, ".laz": 0.78, ".ifc": 0.75,
        }.get(suffix, 0.85)

        # 模拟偶尔的失败和重试
        file_failed = False
        retry_count = 0
        while retry_count <= job.retry_policy.max_retries:
            if _random_ok(success_rate):
                # 成功
                out_name = Path(file_entry.name).stem + "_converted." + job.config.target_format.lower()
                out_path = str(Path(job.config.output_dir or "output") / out_name)
                outputs.append(out_path)
                logs.append({"timestamp": _ts(), "level": "INFO", "file_name": file_entry.name, "message": f"转换成功 → {out_name}"})
                success += 1
                break
            else:
                retry_count += 1
                if retry_count <= job.retry_policy.max_retries:
                    if job.retry_policy.strategy not in ("跳过", "中止"):
                        retried += 1
                        logs.append({"timestamp": _ts(), "level": "WARNING", "file_name": file_entry.name,
                                     "message": f"转换失败，{job.retry_policy.strategy}（第 {retry_count} 次）。"})
                    else:
                        break
                else:
                    file_failed = True
                    break

        if file_failed or (retry_count > 0 and job.retry_policy.strategy == "跳过"):
            failed += 1
            err_msg = f"转换失败，已重试 {retry_count} 次。" if retry_count > 0 else "转换失败。"
            logs.append({"timestamp": _ts(), "level": "ERROR", "file_name": file_entry.name, "message": err_msg})
            errors.append({"file": file_entry.name, "message": err_msg, "retries": str(retry_count)})
            if job.retry_policy.strategy == "中止":
                logs.append({"timestamp": _ts(), "level": "ERROR", "message": "策略为“中止”，停止后续处理。"})
                break

    t1 = datetime.now().isoformat(timespec="seconds")
    logs.insert(0, {"timestamp": t0, "level": "INFO", "message": f"批次执行开始。"})
    logs.append({"timestamp": t1, "level": "INFO", "message": f"批次执行结束，耗时约 {len(job.files) * 0.05:.1f}s（模拟）。"})

    if failed == 0:
        status = "已完成"
    elif success > 0:
        status = "部分失败"
    else:
        status = "已失败"

    return {
        "status": status,
        "processed": processed,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "retried": retried,
        "outputs": outputs,
        "errors": errors,
        "logs": logs,
    }


def _random_ok(rate: float) -> bool:
    """伪随机判断（基于文件名哈希，使结果可复现）。"""
    return rate > 0.5  # 简化：直接用成功率阈值


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ============================================================================
# 流程编排
# ============================================================================

WORKFLOW_STEPS = (
    "目录扫描与文件发现",
    "格式识别与分类",
    "规则模板匹配",
    "批量格式转换",
    "质量检查与校验",
    "成果汇总与归档",
)


def build_workflow(config: BatchConfig) -> list[dict[str, Any]]:
    """根据配置编排批处理工作流步骤。"""
    steps: list[dict[str, Any]] = []
    steps.append({"order": 1, "name": "目录扫描与文件发现", "status": "pending",
                  "detail": f"扫描 {len(config.directories)} 个目录，递归={config.recursive}。"})
    steps.append({"order": 2, "name": "格式识别与分类", "status": "pending",
                  "detail": f"按 {config.format_category} 类别过滤文件。"})
    steps.append({"order": 3, "name": "规则模板匹配", "status": "pending",
                  "detail": f"应用模板“{config.template_name or '未指定'}”中的映射规则。"})
    steps.append({"order": 4, "name": "批量格式转换", "status": "pending",
                  "detail": f"转换为 {config.target_format}，坐标规则={config.coordinate_rule}。"})
    steps.append({"order": 5, "name": "质量检查与校验", "status": "pending",
                  "detail": "几何闭合性、拓扑关系、属性完整性、坐标精度。"})
    steps.append({"order": 6, "name": "成果汇总与归档", "status": "pending",
                  "detail": f"输出至 {config.output_dir or 'output/'}，生成操作日志。"})
    return steps


# ============================================================================
# 批量报告
# ============================================================================

def build_batch_report(job_ids: list[str] | None = None) -> dict[str, Any]:
    """汇总批量转换作业报告。"""
    mgr = get_manager()
    jobs = [mgr.get_job(jid) for jid in (job_ids or []) if mgr.get_job(jid)]
    if not job_ids:
        jobs = mgr.list_jobs()

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": mgr.stats,
        "jobs": [],
        "summary": {},
    }

    total_files = 0
    total_success = 0
    total_failed = 0
    total_retried = 0

    for job in jobs:
        total_files += job.total
        total_success += job.success
        total_failed += job.failed
        total_retried += job.retried
        report["jobs"].append({
            "job_id": job.job_id, "name": job.name, "status": job.status,
            "total": job.total, "processed": job.processed,
            "success": job.success, "failed": job.failed, "skipped": job.skipped,
            "retried": job.retried, "progress_pct": job.progress_pct,
            "created_at": job.created_at, "finished_at": job.finished_at,
            "error_count": len(job.errors),
        })

    report["summary"] = {
        "total_jobs": len(jobs),
        "total_files": total_files,
        "total_success": total_success,
        "total_failed": total_failed,
        "total_retried": total_retried,
        "success_rate": round(total_success / max(total_files, 1), 4),
    }
    return report


# ============================================================================
# 入口：导入数据并创建批处理作业
# ============================================================================

def create_batch_from_paths(
    file_paths: list[str],
    job_name: str = "",
    target_format: str = "OBJ",
    output_dir: str = "",
    template_name: str = "",
) -> BatchJob:
    """从用户选择的文件列表创建批处理作业。"""
    mgr = get_manager()
    config = BatchConfig(
        name=job_name or f"手动导入批次 {_ts()}",
        target_format=target_format,
        output_dir=output_dir or "output",
        template_name=template_name,
    )
    files = [FileEntry(path=fp) for fp in file_paths if Path(fp).exists()]
    job = mgr.create_job(name=config.name, config=config)
    job.files = files
    job.total = len(files)
    return job


def create_batch_from_directories(
    directories: list[str],
    job_name: str = "",
    format_category: str = "全部",
    recursive: bool = True,
    target_format: str = "OBJ",
    output_dir: str = "",
    template_name: str = "",
    max_files: int = 500,
    retry_policy: RetryPolicy | None = None,
) -> BatchJob:
    """从目录扫描创建批处理作业。"""
    mgr = get_manager()
    config = BatchConfig(
        name=job_name or f"目录扫描批次 {_ts()}",
        directories=directories,
        format_category=format_category,
        recursive=recursive,
        max_files=max_files,
        target_format=target_format,
        output_dir=output_dir or "output",
        template_name=template_name,
    )
    job = mgr.create_job(name=config.name, config=config, retry_policy=retry_policy)
    return job


# ============================================================================
# 统计工具
# ============================================================================

def format_summary(files: list[FileEntry]) -> dict[str, dict[str, int]]:
    """按格式类别统计文件分布。"""
    dist: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "size_bytes": 0})
    for f in files:
        dist[f.category]["count"] += 1
        dist[f.category]["size_bytes"] += f.size_bytes
    return dict(dist)


def size_fmt(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


__all__ = [
    "BatchJob", "BatchConfig", "BatchJobManager", "RetryPolicy",
    "FileEntry", "JobLogEntry", "WORKFLOW_STEPS", "SCAN_EXTENSIONS",
    "JOB_STATUSES", "RETRY_STRATEGIES", "LOG_LEVELS",
    "get_manager", "scan_directories", "scan_directory_flat",
    "create_batch_from_paths", "create_batch_from_directories",
    "build_batch_report", "build_workflow", "format_summary", "size_fmt",
]
