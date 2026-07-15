from __future__ import annotations

import csv
import hashlib
import json
import time
import threading
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    # 放在 function/ 目录中时使用相对导入。
    from .model_format_conversion import convert_model_files as _convert_model_files
except Exception:  # pragma: no cover - 兼容直接运行或模块尚未放入项目
    try:
        from model_format_conversion import convert_model_files as _convert_model_files  # type: ignore
    except Exception:
        _convert_model_files = None

try:
    from .rule_template_library import apply_template_to_data, get_template, template_fingerprint
except Exception:  # pragma: no cover - 兼容直接运行
    try:
        from rule_template_library import apply_template_to_data, get_template, template_fingerprint  # type: ignore
    except Exception:
        apply_template_to_data = get_template = template_fingerprint = None


# ============================================================================
# 常量
# ============================================================================

SCAN_EXTENSIONS: dict[str, list[str]] = {
    "表格": [".csv", ".txt"],
    "三维模型": [".obj", ".stl", ".ply", ".vtk"],
    "地理空间": [".geojson", ".json"],
    "点云": [".las", ".laz"],
    "BIM/IFC": [".ifc"],
    "全部": [
        ".csv", ".txt", ".obj", ".stl", ".ply", ".vtk",
        ".geojson", ".json", ".las", ".laz", ".ifc",
    ],
}

FORMAT_CATEGORY: dict[str, str] = {}
for _category, _extensions in SCAN_EXTENSIONS.items():
    if _category != "全部":
        for _extension in _extensions:
            FORMAT_CATEGORY[_extension] = _category

JOB_STATUSES = ("排队中", "运行中", "已完成", "部分失败", "已失败", "已取消")
RETRY_STRATEGIES = ("立即重试", "延迟重试", "跳过", "中止")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_LOG_RANK = {name: index for index, name in enumerate(LOG_LEVELS)}

WORKFLOW_STEPS = (
    "目录扫描与文件发现",
    "格式识别与分类",
    "规则模板匹配",
    "批量格式转换",
    "质量检查与校验",
    "成果汇总与归档",
)


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

    def __post_init__(self) -> None:
        file_path = Path(self.path).expanduser()
        if not self.name:
            self.name = file_path.name
        if not self.suffix:
            self.suffix = file_path.suffix.lower()
        if self.category == "未知":
            self.category = FORMAT_CATEGORY.get(self.suffix, "未知")
        if self.size_bytes <= 0 and file_path.is_file():
            try:
                self.size_bytes = file_path.stat().st_size
            except OSError:
                self.size_bytes = 0


@dataclass
class BatchConfig:
    """批次配置。"""

    name: str = ""
    directories: list[str] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=lambda: ["*"])
    format_category: str = "全部"
    recursive: bool = True
    max_files: int = 500
    template_name: str = ""
    target_format: str = "OBJ"
    coordinate_rule: str = "保留源坐标"
    attribute_rule: str = "全部保留"
    output_dir: str = ""
    concurrency: int = 4
    log_level: str = "INFO"
    overwrite: bool = True

    def __post_init__(self) -> None:
        self.max_files = max(1, int(self.max_files or 1))
        self.concurrency = max(1, min(32, int(self.concurrency or 1)))
        if self.log_level not in LOG_LEVELS:
            self.log_level = "INFO"
        if self.format_category not in SCAN_EXTENSIONS:
            self.format_category = "全部"


@dataclass
class RetryPolicy:
    """失败重试策略。"""

    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    strategy: str = "延迟重试"
    retryable_errors: list[str] = field(
        default_factory=lambda: ["解析", "读取", "写入", "超时", "连接", "I/O", "临时"]
    )

    def __post_init__(self) -> None:
        self.max_retries = max(0, min(20, int(self.max_retries or 0)))
        self.retry_delay_seconds = max(0.0, float(self.retry_delay_seconds or 0.0))
        if self.strategy not in RETRY_STRATEGIES:
            self.strategy = "延迟重试"


@dataclass
class JobLogEntry:
    timestamp: str
    level: str
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
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    workflow: list[dict[str, Any]] = field(default_factory=list)


# ============================================================================
# 作业管理器
# ============================================================================

class BatchJobManager:
    """线程安全的内存任务队列。后续可替换为数据库或消息队列。"""

    def __init__(self) -> None:
        self._jobs: dict[str, BatchJob] = {}
        self._queue: list[str] = []
        self._counter = 0
        self._lock = threading.RLock()

    def create_job(
        self,
        name: str,
        config: BatchConfig,
        retry_policy: RetryPolicy | None = None,
        files: list[FileEntry] | None = None,
    ) -> BatchJob:
        with self._lock:
            self._counter += 1
            job_id = f"BATCH-{datetime.now().strftime('%Y%m%d')}-{self._counter:04d}"
            imported_files = list(files) if files is not None else scan_directories(config)
            job = BatchJob(
                job_id=job_id,
                name=name,
                config=config,
                retry_policy=retry_policy or RetryPolicy(),
                files=imported_files,
                total=len(imported_files),
                created_at=_ts(),
                workflow=build_workflow(config),
            )
            source_text = "导入" if files is not None else "扫描"
            self._append_job_log(job, "INFO", f"作业已创建，{source_text}到 {job.total} 个文件。")
            self._jobs[job_id] = job
            return job

    def submit(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "排队中" or job_id in self._queue:
                return False
            self._queue.append(job_id)
            self._append_job_log(job, "INFO", "已加入执行队列。")
            return True

    def get_job(self, job_id: str) -> BatchJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[BatchJob]:
        with self._lock:
            jobs = list(self._jobs.values())
        if status:
            jobs = [job for job in jobs if job.status == status]
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in ("已完成", "已取消"):
                return False
            job.status = "已取消"
            job.finished_at = _ts()
            self._append_job_log(job, "WARNING", "作业已被取消。")
            while job_id in self._queue:
                self._queue.remove(job_id)
            return True

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            while job_id in self._queue:
                self._queue.remove(job_id)
            return self._jobs.pop(job_id, None) is not None

    def run_job(self, job_id: str) -> BatchJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in ("运行中", "已取消"):
                return job
            while job_id in self._queue:
                self._queue.remove(job_id)
            job.status = "运行中"
            job.started_at = _ts()
            job.finished_at = ""
            job.processed = job.success = job.failed = job.skipped = job.retried = 0
            job.progress_pct = 0.0
            job.errors.clear()
            job.outputs.clear()
            job.artifacts.clear()
            self._append_job_log(job, "INFO", f"开始执行批量转换，共 {job.total} 个文件。")

        results = _execute_batch_run(job)

        with self._lock:
            job.status = str(results["status"])
            job.processed = int(results["processed"])
            job.success = int(results["success"])
            job.failed = int(results["failed"])
            job.skipped = int(results["skipped"])
            job.retried = int(results["retried"])
            completed_count = job.success + job.failed + job.skipped
            job.progress_pct = completed_count / max(job.total, 1)
            job.finished_at = _ts()
            job.outputs = list(results["outputs"])
            job.errors = list(results["errors"])
            job.artifacts = list(results["artifacts"])
            job.workflow = list(results["workflow"])
            for item in results["logs"]:
                self._append_job_log(
                    job,
                    str(item.get("level", "INFO")),
                    str(item.get("message", "")),
                    str(item.get("file_name", "")),
                    timestamp=str(item.get("timestamp", "")) or None,
                )
            self._append_job_log(
                job,
                "INFO",
                f"作业结束：成功 {job.success} / 失败 {job.failed} / 跳过 {job.skipped} / 重试 {job.retried}。",
            )
            return job

    def run_all_queued(self) -> list[BatchJob]:
        results: list[BatchJob] = []
        while True:
            with self._lock:
                if not self._queue:
                    break
                job_id = self._queue[0]
            job = self.run_job(job_id)
            if job:
                results.append(job)
        return results

    @property
    def queue_length(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            jobs = list(self._jobs.values())
        return {
            "total": len(jobs),
            "queued": sum(job.status == "排队中" for job in jobs),
            "running": sum(job.status == "运行中" for job in jobs),
            "completed": sum(job.status == "已完成" for job in jobs),
            "failed": sum(job.status in ("已失败", "部分失败") for job in jobs),
            "cancelled": sum(job.status == "已取消" for job in jobs),
        }

    @staticmethod
    def _append_job_log(
        job: BatchJob,
        level: str,
        message: str,
        file_name: str = "",
        timestamp: str | None = None,
    ) -> None:
        if _should_log(level, job.config.log_level):
            job.logs.append(JobLogEntry(timestamp or _ts(), level, file_name, message))


_manager = BatchJobManager()


def get_manager() -> BatchJobManager:
    return _manager


# ============================================================================
# 文件扫描
# ============================================================================

def scan_directories(config: BatchConfig) -> list[FileEntry]:
    """扫描多个目录，自动去重并限制最大文件数。"""

    extensions = set(SCAN_EXTENSIONS.get(config.format_category, SCAN_EXTENSIONS["全部"]))
    found: dict[str, FileEntry] = {}

    for directory in config.directories:
        base = Path(directory).expanduser()
        if not base.is_dir():
            continue
        walker: Callable[[str], Any] = base.rglob if config.recursive else base.glob
        for pattern in config.file_patterns or ["*"]:
            try:
                candidates = walker(pattern)
                for path in candidates:
                    if not path.is_file() or path.suffix.lower() not in extensions:
                        continue
                    try:
                        resolved = str(path.resolve())
                    except OSError:
                        resolved = str(path)
                    found.setdefault(resolved, FileEntry(path=resolved))
                    if len(found) >= config.max_files:
                        break
            except OSError:
                continue
            if len(found) >= config.max_files:
                break
        if len(found) >= config.max_files:
            break

    return sorted(found.values(), key=lambda item: (item.category, item.name, item.path))


def scan_directory_flat(
    directory: str | Path,
    recursive: bool = True,
    max_files: int = 500,
    format_category: str = "全部",
) -> list[FileEntry]:
    config = BatchConfig(
        directories=[str(directory)],
        recursive=recursive,
        max_files=max_files,
        format_category=format_category,
    )
    return scan_directories(config)


# ============================================================================
# 执行器
# ============================================================================

def _execute_batch_run(job: BatchJob) -> dict[str, Any]:
    logs: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    outputs: list[str] = []
    artifacts: list[dict[str, Any]] = []
    workflow = build_workflow(job.config)
    started = time.perf_counter()

    selected = [(index, item) for index, item in enumerate(job.files, start=1) if item.selected]
    skipped_unselected = sum(not item.selected for item in job.files)
    for item in job.files:
        if not item.selected:
            _append_log(logs, job, "INFO", "已跳过（未选中）。", item.name)

    if not selected:
        status = "已完成" if job.total else "已失败"
        if not job.total:
            errors.append({"file": "", "message": "批次中没有可执行文件。", "retries": "0"})
            _append_log(logs, job, "ERROR", "批次中没有可执行文件。")
        result = {
            "status": status,
            "processed": 0,
            "success": 0,
            "failed": 0 if job.total else 1,
            "skipped": skipped_unselected,
            "retried": 0,
            "outputs": outputs,
            "errors": errors,
            "logs": logs,
            "artifacts": artifacts,
            "workflow": _finish_workflow(workflow, status),
        }
        manifest_path = _write_batch_manifest(job, result)
        result["outputs"] = [manifest_path]
        return result

    if _convert_model_files is None:
        message = "未找到 function/model_format_conversion.py，无法执行真实格式转换。"
        for _, item in selected:
            errors.append({"file": item.name, "message": message, "retries": "0"})
            _append_log(logs, job, "ERROR", message, item.name)
        result = {
            "status": "已失败",
            "processed": len(selected),
            "success": 0,
            "failed": len(selected),
            "skipped": skipped_unselected,
            "retried": 0,
            "outputs": outputs,
            "errors": errors,
            "logs": logs,
            "artifacts": artifacts,
            "workflow": _finish_workflow(workflow, "已失败"),
        }
        manifest_path = _write_batch_manifest(job, result)
        result["outputs"] = [manifest_path]
        return result

    if job.config.template_name:
        template = get_template(job.config.template_name) if get_template else None
        if template is None:
            message = f"规则模板不存在：{job.config.template_name}"
            for _, item in selected:
                errors.append({"file": item.name, "message": message, "retries": "0"})
                _append_log(logs, job, "ERROR", message, item.name)
            result = {
                "status": "已失败", "processed": len(selected), "success": 0,
                "failed": len(selected), "skipped": skipped_unselected, "retried": 0,
                "outputs": [], "errors": errors, "logs": logs, "artifacts": [],
                "workflow": _finish_workflow(workflow, "已失败", template_stats={"failed": len(selected)}),
            }
            manifest_path = _write_batch_manifest(job, result)
            result["outputs"] = [manifest_path]
            return result

    stop_event = threading.Event()
    max_workers = job.config.concurrency
    if job.retry_policy.strategy == "中止":
        # “中止”要求首个失败后立刻停下，使用单线程才能保证语义准确。
        max_workers = 1
        _append_log(logs, job, "DEBUG", "重试策略为“中止”，并发数量自动调整为 1。")

    success = failed = skipped_policy = retried = processed = 0
    futures: dict[Future[dict[str, Any]], FileEntry] = {}

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="batch-convert") as executor:
        for index, item in selected:
            future = executor.submit(_convert_one_file, job, item, index, stop_event)
            futures[future] = item

        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # 后端异常不能让整个批次崩溃
                result = {
                    "state": "failed",
                    "retries": 0,
                    "outputs": [],
                    "artifacts": [],
                    "logs": [{"timestamp": _ts(), "level": "ERROR", "file_name": item.name, "message": f"执行器异常：{exc}"}],
                    "error": str(exc),
                }

            state = str(result["state"])
            if state != "cancelled":
                processed += 1
            if state == "success":
                success += 1
            elif state == "skipped":
                skipped_policy += 1
            elif state == "failed":
                failed += 1
                errors.append({
                    "file": item.name,
                    "message": str(result.get("error", "转换失败。")),
                    "retries": str(result.get("retries", 0)),
                })
            elif state == "cancelled":
                skipped_policy += 1

            retried += int(result.get("retries", 0))
            outputs.extend(str(path) for path in result.get("outputs", []))
            artifacts.extend(item for item in result.get("artifacts", []) if isinstance(item, dict))
            logs.extend(item for item in result.get("logs", []) if isinstance(item, dict))

    skipped = skipped_unselected + skipped_policy
    if stop_event.is_set() and failed > 0:
        status = "已失败"
    elif failed == 0 and skipped_policy == 0:
        status = "已完成"
    elif success > 0:
        status = "部分失败"
    else:
        status = "已失败"

    elapsed = time.perf_counter() - started
    _append_log(logs, job, "INFO", f"批次执行结束，耗时 {elapsed:.2f} 秒。")

    template_stats = _template_stats(artifacts)
    result = {
        "status": status,
        "processed": processed,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "retried": retried,
        "outputs": _deduplicate(outputs),
        "errors": errors,
        "logs": sorted(logs, key=lambda item: item.get("timestamp", "")),
        "artifacts": artifacts,
        "workflow": _finish_workflow(workflow, status, template_stats=template_stats),
    }
    manifest_path = _write_batch_manifest(job, result)
    result["outputs"] = _deduplicate([*result["outputs"], manifest_path])
    return result


def _convert_one_file(
    job: BatchJob,
    file_entry: FileEntry,
    sequence: int,
    stop_event: threading.Event,
) -> dict[str, Any]:
    local_logs: list[dict[str, str]] = []
    source = Path(file_entry.path).expanduser()
    if stop_event.is_set():
        return {"state": "cancelled", "retries": 0, "outputs": [], "artifacts": [], "logs": local_logs}
    if not source.is_file():
        message = "源文件不存在或不可访问。"
        _append_log(local_logs, job, "ERROR", message, file_entry.name)
        return {"state": "failed", "retries": 0, "outputs": [], "artifacts": [], "logs": local_logs, "error": message}

    output_root = Path(job.config.output_dir or "output").expanduser() / job.job_id
    file_output_dir = output_root / f"{sequence:03d}_{_safe_stem(source.stem)}"
    file_output_dir.mkdir(parents=True, exist_ok=True)

    conversion_source = source
    template_application = _apply_batch_template(job.config.template_name, source, file_output_dir)
    if template_application["status"] == "failed":
        message = str(template_application.get("message") or "规则模板应用失败。")
        artifact = {
            "source": str(source.resolve()), "status": "失败", "message": message,
            "template_application": template_application,
        }
        _append_log(local_logs, job, "ERROR", message, file_entry.name)
        return {
            "state": "failed", "retries": 0, "outputs": _template_outputs(template_application),
            "artifacts": [artifact], "logs": local_logs, "error": message,
        }
    if template_application["status"] == "applied":
        conversion_source = Path(str(template_application["mapped_file"]))
        _append_log(local_logs, job, "INFO", f"已应用模板“{job.config.template_name}”并生成映射中间文件。", file_entry.name)
    elif job.config.template_name:
        _append_log(local_logs, job, "INFO", str(template_application.get("message", "模板不适用，已保留原文件。")), file_entry.name)

    retries_done = 0
    last_error = "转换失败。"
    last_artifacts: list[dict[str, Any]] = []
    last_outputs: list[str] = []

    for attempt in range(job.retry_policy.max_retries + 1):
        if stop_event.is_set():
            return {
                "state": "cancelled",
                "retries": retries_done,
                "outputs": [],
                "artifacts": [],
                "logs": local_logs,
            }

        _append_log(
            local_logs,
            job,
            "DEBUG",
            f"开始第 {attempt + 1} 次转换，目标格式={job.config.target_format}。",
            file_entry.name,
        )
        try:
            report = _convert_model_files(
                [str(conversion_source)],
                file_output_dir,
                job.config.target_format,
                coordinate_rule=job.config.coordinate_rule,
                attribute_rule=job.config.attribute_rule,
                overwrite=job.config.overwrite,
            )
        except Exception as exc:
            report = {
                "success_count": 0,
                "failure_count": 1,
                "errors": [f"转换器异常：{exc}"],
                "artifacts": [],
            }

        last_artifacts = [item for item in report.get("artifacts", []) if isinstance(item, dict)]
        for artifact in last_artifacts:
            artifact["batch_source"] = str(source.resolve())
            artifact["conversion_source"] = str(conversion_source.resolve())
            artifact["template_application"] = template_application
        last_outputs = _deduplicate([*_template_outputs(template_application), *_extract_outputs(report)])
        success_count = int(report.get("success_count", 0) or 0)
        failure_count = int(report.get("failure_count", 0) or 0)

        if success_count > 0 and failure_count == 0:
            _append_log(
                local_logs,
                job,
                "INFO",
                f"转换成功，共生成 {len(last_outputs)} 个成果文件。",
                file_entry.name,
            )
            return {
                "state": "success",
                "retries": retries_done,
                "outputs": last_outputs,
                "artifacts": last_artifacts,
                "logs": local_logs,
            }

        last_error = _report_error_text(report)
        if job.retry_policy.strategy == "跳过":
            _append_log(local_logs, job, "WARNING", f"转换失败并按策略跳过：{last_error}", file_entry.name)
            return {
                "state": "skipped",
                "retries": retries_done,
                "outputs": [],
                "artifacts": last_artifacts,
                "logs": local_logs,
                "error": last_error,
            }
        if job.retry_policy.strategy == "中止":
            stop_event.set()
            _append_log(local_logs, job, "ERROR", f"转换失败，批次中止：{last_error}", file_entry.name)
            return {
                "state": "failed",
                "retries": retries_done,
                "outputs": [],
                "artifacts": last_artifacts,
                "logs": local_logs,
                "error": last_error,
            }
        if attempt >= job.retry_policy.max_retries or not _is_retryable(last_error, job.retry_policy):
            break

        retries_done += 1
        _append_log(
            local_logs,
            job,
            "WARNING",
            f"转换失败，准备{job.retry_policy.strategy}（第 {retries_done} 次）：{last_error}",
            file_entry.name,
        )
        if job.retry_policy.strategy == "延迟重试" and job.retry_policy.retry_delay_seconds > 0:
            time.sleep(job.retry_policy.retry_delay_seconds)

    _append_log(local_logs, job, "ERROR", f"转换最终失败：{last_error}", file_entry.name)
    return {
        "state": "failed",
        "retries": retries_done,
        "outputs": [],
        "artifacts": last_artifacts,
        "logs": local_logs,
        "error": last_error,
    }


def _extract_outputs(report: dict[str, Any]) -> list[str]:
    outputs: list[str] = []
    for artifact in report.get("artifacts", []):
        if isinstance(artifact, dict):
            value = artifact.get("output") or artifact.get("output_file")
            if value:
                outputs.append(str(value))
            for sidecar in artifact.get("sidecar_files", []) or []:
                outputs.append(str(sidecar))
    manifest = report.get("manifest_path")
    if manifest:
        outputs.append(str(manifest))
    return _deduplicate(outputs)


def _apply_batch_template(template_name: str, source: Path, output_dir: Path) -> dict[str, Any]:
    """在格式转换前执行可审计的字段映射。

    表格数据生成标准 CSV；GeoJSON 保留几何并只映射 properties。
    网格/IFC 不强行表格化，但会在审计信息中明确记录 skipped。
    """
    base = {
        "template": template_name, "status": "not_requested" if not template_name else "pending",
        "source": str(source.resolve()), "mapped_file": "", "warnings": [], "errors": [],
    }
    if not template_name:
        return base
    if not (get_template and apply_template_to_data and template_fingerprint):
        return {**base, "status": "failed", "message": "规则模板模块不可用。", "errors": ["规则模板模块不可用。"]}
    template = get_template(template_name)
    if template is None:
        return {**base, "status": "failed", "message": f"规则模板不存在：{template_name}", "errors": ["模板不存在。"]}

    suffix = source.suffix.lower()
    source_format = {".csv": "CSV", ".txt": "TXT", ".json": "JSON", ".geojson": "GEOJSON"}.get(suffix, suffix.lstrip(".").upper())
    allowed = {str(item).upper() for item in template.input_formats}
    if suffix not in {".csv", ".txt", ".json", ".geojson"} or (allowed and source_format not in allowed):
        return {
            **base, "status": "skipped", "template_version": template.version,
            "template_fingerprint": template_fingerprint(template),
            "message": f"模板不适用于 {source_format} 文件，已保留原数据进行转换。",
        }

    try:
        geometry_payload: dict[str, Any] | None = None
        if suffix in {".json", ".geojson"}:
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict) and isinstance(payload.get("features"), list):
                geometry_payload = payload
                rows = [dict(item.get("properties") or {}) for item in payload["features"] if isinstance(item, dict)]
            elif isinstance(payload, list):
                rows = [dict(item) for item in payload if isinstance(item, dict)]
            elif isinstance(payload, dict):
                rows = [payload]
            else:
                raise ValueError("JSON 顶层必须是对象、对象数组或 FeatureCollection。")
        else:
            delimiter = "\t" if suffix == ".txt" else ","
            with source.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=delimiter))
        mapped = apply_template_to_data(template_name, rows)
        errors = [str(item) for item in mapped.get("errors", [])]
        warnings = [str(item) for item in mapped.get("warnings", [])]
        if errors:
            return {
                **base, "status": "failed", "template_version": template.version,
                "template_fingerprint": template_fingerprint(template), "errors": errors,
                "warnings": warnings, "quality": mapped.get("quality", {}),
                "message": "模板映射质量校验失败：" + "；".join(errors[:4]),
            }

        output_dir.mkdir(parents=True, exist_ok=True)
        if geometry_payload is not None:
            mapped_file = output_dir / f"{_safe_stem(source.stem)}_template_mapped.geojson"
            features = geometry_payload.get("features", [])
            for index, props in enumerate(mapped.get("rows", [])):
                if index < len(features) and isinstance(features[index], dict):
                    features[index]["properties"] = props
            _atomic_json(mapped_file, geometry_payload)
        else:
            mapped_file = output_dir / f"{_safe_stem(source.stem)}_template_mapped.csv"
            _atomic_csv(mapped_file, list(mapped.get("rows", [])))
        return {
            **base, "status": "applied", "template_version": template.version,
            "template_fingerprint": template_fingerprint(template), "mapped_file": str(mapped_file.resolve()),
            "mapped_sha256": _sha256(mapped_file), "source_sha256": _sha256(source),
            "row_count": len(mapped.get("rows", [])), "fields_mapped": mapped.get("fields_mapped", []),
            "warnings": warnings, "errors": [], "quality": mapped.get("quality", {}),
            "message": f"已映射 {len(mapped.get('rows', []))} 条记录。",
        }
    except Exception as exc:
        return {
            **base, "status": "failed", "template_version": template.version,
            "template_fingerprint": template_fingerprint(template), "errors": [str(exc)],
            "message": f"模板映射异常：{exc}",
        }


def _template_outputs(application: dict[str, Any]) -> list[str]:
    mapped = application.get("mapped_file")
    return [str(mapped)] if mapped else []


def _report_error_text(report: dict[str, Any]) -> str:
    errors = report.get("errors", [])
    if isinstance(errors, list) and errors:
        return "；".join(str(item) for item in errors[:4])
    artifacts = report.get("artifacts", [])
    messages = [
        str(item.get("message", ""))
        for item in artifacts
        if isinstance(item, dict) and item.get("status") not in ("成功", "已完成") and item.get("message")
    ]
    return "；".join(messages[:4]) or str(report.get("status", "转换失败。"))


def _is_retryable(message: str, policy: RetryPolicy | None = None) -> bool:
    text = message.lower()
    non_retryable = ("不支持的目标格式", "当前未内置该源格式", "源文件不存在", "未选择待转换文件")
    if any(token.lower() in text for token in non_retryable):
        return False
    keywords = (policy.retryable_errors if policy else RetryPolicy().retryable_errors)
    return any(str(token).lower() in text for token in keywords)


# ============================================================================
# 流程与报告
# ============================================================================

def build_workflow(config: BatchConfig) -> list[dict[str, Any]]:
    return [
        {"order": 1, "name": WORKFLOW_STEPS[0], "status": "pending", "detail": f"扫描 {len(config.directories)} 个目录，递归={config.recursive}。"},
        {"order": 2, "name": WORKFLOW_STEPS[1], "status": "pending", "detail": f"按 {config.format_category} 类别识别文件。"},
        {"order": 3, "name": WORKFLOW_STEPS[2], "status": "pending", "detail": f"应用模板“{config.template_name or '未指定'}”。"},
        {"order": 4, "name": WORKFLOW_STEPS[3], "status": "pending", "detail": f"并发数={config.concurrency}，目标格式={config.target_format}。"},
        {"order": 5, "name": WORKFLOW_STEPS[4], "status": "pending", "detail": "读取转换器返回的质量结果、警告与错误。"},
        {"order": 6, "name": WORKFLOW_STEPS[5], "status": "pending", "detail": f"输出至 {config.output_dir or 'output/'}。"},
    ]


def build_batch_report(job_ids: list[str] | None = None) -> dict[str, Any]:
    manager = get_manager()
    if job_ids:
        jobs = [job for job_id in job_ids if (job := manager.get_job(job_id)) is not None]
    else:
        jobs = manager.list_jobs()

    report_jobs: list[dict[str, Any]] = []
    for job in jobs:
        report_jobs.append({
            "job_id": job.job_id,
            "name": job.name,
            "status": job.status,
            "total": job.total,
            "processed": job.processed,
            "success": job.success,
            "failed": job.failed,
            "skipped": job.skipped,
            "retried": job.retried,
            "progress_pct": round(job.progress_pct, 4),
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "config": asdict(job.config),
            "retry_policy": asdict(job.retry_policy),
            "outputs": list(job.outputs),
            "errors": list(job.errors),
            "artifacts": list(job.artifacts),
            "logs": [asdict(item) for item in job.logs],
            "workflow": list(job.workflow),
        })

    total_files = sum(job.total for job in jobs)
    total_success = sum(job.success for job in jobs)
    total_failed = sum(job.failed for job in jobs)
    total_skipped = sum(job.skipped for job in jobs)
    total_retried = sum(job.retried for job in jobs)
    attempted = total_success + total_failed

    return {
        "schema_version": "2.0",
        "report_type": "batch_conversion",
        "report_id": f"BATCH-REPORT-{uuid.uuid4().hex[:12].upper()}",
        "generated_at": _ts(),
        "stats": manager.stats,
        "jobs": report_jobs,
        "summary": {
            "total_jobs": len(jobs),
            "total_files": total_files,
            "total_success": total_success,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "total_retried": total_retried,
            "success_rate": round(total_success / max(attempted, 1), 4),
        },
    }


# ============================================================================
# 创建作业入口
# ============================================================================

def create_batch_from_paths(
    file_paths: list[str],
    job_name: str = "",
    target_format: str = "OBJ",
    output_dir: str = "",
    template_name: str = "",
    coordinate_rule: str = "保留源坐标",
    attribute_rule: str = "全部保留",
    concurrency: int = 4,
    log_level: str = "INFO",
    retry_policy: RetryPolicy | None = None,
) -> BatchJob:
    config = BatchConfig(
        name=job_name or f"手动导入批次 {_ts()}",
        target_format=target_format,
        output_dir=output_dir or "output",
        template_name=template_name,
        coordinate_rule=coordinate_rule,
        attribute_rule=attribute_rule,
        concurrency=concurrency,
        log_level=log_level,
    )
    unique_files: dict[str, FileEntry] = {}
    for raw_path in file_paths:
        path = Path(raw_path).expanduser()
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key not in unique_files:
            unique_files[key] = FileEntry(path=key)
    return get_manager().create_job(
        name=config.name,
        config=config,
        retry_policy=retry_policy,
        files=list(unique_files.values()),
    )


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
    coordinate_rule: str = "保留源坐标",
    attribute_rule: str = "全部保留",
    concurrency: int = 4,
    log_level: str = "INFO",
) -> BatchJob:
    config = BatchConfig(
        name=job_name or f"目录扫描批次 {_ts()}",
        directories=list(directories),
        format_category=format_category,
        recursive=recursive,
        max_files=max_files,
        target_format=target_format,
        output_dir=output_dir or "output",
        template_name=template_name,
        coordinate_rule=coordinate_rule,
        attribute_rule=attribute_rule,
        concurrency=concurrency,
        log_level=log_level,
    )
    return get_manager().create_job(name=config.name, config=config, retry_policy=retry_policy)


# ============================================================================
# 工具函数
# ============================================================================

def format_summary(files: list[FileEntry]) -> dict[str, dict[str, int]]:
    distribution: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "size_bytes": 0})
    for item in files:
        distribution[item.category]["count"] += 1
        distribution[item.category]["size_bytes"] += item.size_bytes
    return dict(distribution)


def size_fmt(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


def _finish_workflow(
    workflow: list[dict[str, Any]],
    status: str,
    template_stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    final = []
    for step in workflow:
        item = dict(step)
        item["status"] = "completed" if status in ("已完成", "部分失败") else "failed"
        if item.get("name") == WORKFLOW_STEPS[2] and template_stats is not None:
            item["detail"] = (
                f"模板已应用 {template_stats.get('applied', 0)} 个，"
                f"不适用 {template_stats.get('skipped', 0)} 个，"
                f"未请求 {template_stats.get('not_requested', 0)} 个，"
                f"失败 {template_stats.get('failed', 0)} 个。"
            )
        final.append(item)
    return final


def _template_stats(artifacts: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"applied": 0, "skipped": 0, "not_requested": 0, "failed": 0}
    for artifact in artifacts:
        application = artifact.get("template_application", {}) if isinstance(artifact, dict) else {}
        status = str(application.get("status", "not_requested"))
        stats[status if status in stats else "failed"] += 1
    return stats


def _write_batch_manifest(job: BatchJob, result: dict[str, Any]) -> str:
    output_root = Path(job.config.output_dir or "output").expanduser() / job.job_id
    manifest_path = output_root / "batch_manifest.json"
    payload = {
        "schema_version": "2.0",
        "manifest_type": "batch_conversion",
        "job_id": job.job_id,
        "generated_at": _ts(),
        "name": job.name,
        "status": result.get("status"),
        "config": asdict(job.config),
        "retry_policy": asdict(job.retry_policy),
        "summary": {key: result.get(key, 0) for key in ("processed", "success", "failed", "skipped", "retried")},
        "artifacts": result.get("artifacts", []),
        "errors": result.get("errors", []),
        "outputs": [
            {"path": path, "sha256": _sha256(Path(path)) if Path(path).is_file() else ""}
            for path in result.get("outputs", [])
        ],
        "workflow": result.get("workflow", []),
    }
    _atomic_json(manifest_path, payload)
    return str(manifest_path.resolve())


def _append_log(
    logs: list[dict[str, str]],
    job: BatchJob,
    level: str,
    message: str,
    file_name: str = "",
) -> None:
    if _should_log(level, job.config.log_level):
        logs.append({"timestamp": _ts(), "level": level, "file_name": file_name, "message": message})


def _should_log(level: str, configured_level: str) -> bool:
    return _LOG_RANK.get(level, 1) >= _LOG_RANK.get(configured_level, 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if str(key) not in fields:
                fields.append(str(key))
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["value"])
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _safe_stem(value: str) -> str:
    allowed = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return allowed.strip("_") or "file"


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ts() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


__all__ = [
    "BatchJob", "BatchConfig", "BatchJobManager", "RetryPolicy",
    "FileEntry", "JobLogEntry", "WORKFLOW_STEPS", "SCAN_EXTENSIONS",
    "JOB_STATUSES", "RETRY_STRATEGIES", "LOG_LEVELS",
    "get_manager", "scan_directories", "scan_directory_flat",
    "create_batch_from_paths", "create_batch_from_directories",
    "build_batch_report", "build_workflow", "format_summary", "size_fmt",
]
