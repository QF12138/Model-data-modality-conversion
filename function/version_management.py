from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class VersionRecord:
    """单次模型版本记录。"""

    version_id: str
    version_number: str = "V1.0.0"
    project_name: str = ""
    module_name: str = ""
    description: str = ""
    created_at: str = ""
    created_by: str = ""

    # 追溯链
    data_sources: list[dict[str, Any]] = field(default_factory=list)
    conversion_params: dict[str, Any] = field(default_factory=dict)
    quality_results: dict[str, Any] = field(default_factory=dict)
    workflow_steps: list[dict[str, Any]] = field(default_factory=list)
    output_files: list[dict[str, Any]] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)

    # 归档
    archived: bool = False
    archive_path: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "project_name": self.project_name,
            "module_name": self.module_name,
            "description": self.description,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "data_sources": deepcopy(self.data_sources),
            "conversion_params": deepcopy(self.conversion_params),
            "quality_results": deepcopy(self.quality_results),
            "workflow_steps": deepcopy(self.workflow_steps),
            "output_files": deepcopy(self.output_files),
            "lineage": deepcopy(self.lineage),
            "archived": self.archived,
            "archive_path": self.archive_path,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VersionRecord":
        record = cls(
            version_id=str(payload.get("version_id", "")),
            version_number=str(payload.get("version_number", "V1.0.0")),
            project_name=str(payload.get("project_name", "")),
            module_name=str(payload.get("module_name", "")),
            description=str(payload.get("description", "")),
            created_at=str(payload.get("created_at", "")),
            created_by=str(payload.get("created_by", "")),
            data_sources=list(payload.get("data_sources", []) or []),
            conversion_params=dict(payload.get("conversion_params", {}) or {}),
            quality_results=dict(payload.get("quality_results", {}) or {}),
            workflow_steps=list(payload.get("workflow_steps", []) or []),
            output_files=list(payload.get("output_files", []) or []),
            lineage=dict(payload.get("lineage", {}) or {}),
            archived=bool(payload.get("archived", False)),
            archive_path=str(payload.get("archive_path", "")),
            tags=[str(item) for item in (payload.get("tags", []) or [])],
        )
        if not record.lineage:
            record.lineage = _build_lineage(record)
        return record


@dataclass
class DiffResult:
    """版本间差异。"""

    field: str
    before: Any
    after: Any
    changed: bool
    summary: str = ""


# ============================================================================
# 版本管理器
# ============================================================================


class VersionManager:
    """模型版本与成果追溯管理器，支持本地 JSON 持久化。"""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._versions: dict[str, VersionRecord] = {}
        self._counter: int = 0
        self.storage_path = Path(storage_path).expanduser() if storage_path else None
        self._load_registry()

    # ------------------------------------------------------------------
    # 基础读写
    # ------------------------------------------------------------------

    def _load_registry(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        raw_versions = payload.get("versions", []) if isinstance(payload, dict) else []
        if not isinstance(raw_versions, list):
            return

        for item in raw_versions:
            if not isinstance(item, dict):
                continue
            record = VersionRecord.from_dict(item)
            if not record.version_id:
                record.version_id = self._new_version_id(_parse_datetime(record.created_at))
            self._versions[record.version_id] = record
            self._counter = max(self._counter, _counter_from_id(record.version_id))

    def save_registry(self) -> str | None:
        if not self.storage_path:
            return None
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "versions": [record.to_dict() for record in self.list_versions()],
        }
        self.storage_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(self.storage_path.resolve())

    def _new_version_id(self, ts: datetime | None = None) -> str:
        ts = ts or datetime.now()
        while True:
            self._counter += 1
            candidate = f"VER-{ts.strftime('%Y%m%d')}-{self._counter:04d}"
            if candidate not in self._versions:
                return candidate

    def _next_version_number(self, project_name: str, module_name: str) -> str:
        numbers: list[tuple[int, int, int]] = []
        for record in self.list_versions(project_name=project_name, module_name=module_name):
            match = re.fullmatch(r"V(\d+)\.(\d+)\.(\d+)", record.version_number.strip(), re.IGNORECASE)
            if match:
                numbers.append(tuple(int(value) for value in match.groups()))
        if not numbers:
            return "V1.0.0"
        major, minor, patch = max(numbers)
        return f"V{major}.{minor}.{patch + 1}"

    def _ensure_unique_version_number(self, version_number: str, project_name: str, module_name: str) -> str:
        used = {
            record.version_number
            for record in self.list_versions(project_name=project_name, module_name=module_name)
        }
        if version_number not in used:
            return version_number

        match = re.fullmatch(r"V(\d+)\.(\d+)\.(\d+)", version_number.strip(), re.IGNORECASE)
        if not match:
            suffix = 2
            while f"{version_number}-{suffix}" in used:
                suffix += 1
            return f"{version_number}-{suffix}"

        major, minor, patch = (int(value) for value in match.groups())
        while True:
            patch += 1
            candidate = f"V{major}.{minor}.{patch}"
            if candidate not in used:
                return candidate

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def create_version(
        self,
        project_name: str = "",
        module_name: str = "",
        description: str = "",
        version_number: str = "",
        created_by: str = "",
        created_at: str = "",
        version_id: str = "",
        data_sources: list[dict[str, Any]] | None = None,
        conversion_params: dict[str, Any] | None = None,
        quality_results: dict[str, Any] | None = None,
        workflow_steps: list[dict[str, Any]] | None = None,
        output_files: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        archived: bool = False,
        archive_path: str = "",
        ensure_unique_number: bool = True,
    ) -> VersionRecord:
        """创建一条版本记录并自动写入持久化注册表。"""
        ts = _parse_datetime(created_at)
        created_at_value = created_at or ts.isoformat(timespec="seconds")
        version_id_value = version_id or self._new_version_id(ts)
        if version_id_value in self._versions:
            version_id_value = self._new_version_id(ts)

        requested_number = version_number.strip() if version_number else self._next_version_number(project_name, module_name)
        version_number_value = (
            self._ensure_unique_version_number(requested_number, project_name, module_name)
            if ensure_unique_number
            else requested_number
        )

        record = VersionRecord(
            version_id=version_id_value,
            version_number=version_number_value,
            project_name=project_name,
            module_name=module_name,
            description=description,
            created_at=created_at_value,
            created_by=created_by,
            data_sources=deepcopy(data_sources or []),
            conversion_params=deepcopy(conversion_params or {}),
            quality_results=deepcopy(quality_results or {}),
            workflow_steps=deepcopy(workflow_steps or []),
            output_files=deepcopy(output_files or []),
            archived=archived,
            archive_path=archive_path,
            tags=list(tags or []),
        )
        record.lineage = _build_lineage(record)
        self._versions[record.version_id] = record
        self.save_registry()
        return record

    def get_version(self, version_id: str) -> VersionRecord | None:
        return self._versions.get(version_id)

    def list_versions(self, project_name: str = "", module_name: str = "") -> list[VersionRecord]:
        result = list(self._versions.values())
        if project_name:
            result = [record for record in result if record.project_name == project_name]
        if module_name:
            result = [record for record in result if record.module_name == module_name]
        return sorted(result, key=lambda record: (record.created_at, record.version_id), reverse=True)

    def stats_for(self, project_name: str = "", module_name: str = "") -> dict[str, int]:
        versions = self.list_versions(project_name=project_name, module_name=module_name)
        return {
            "total": len(versions),
            "archived": sum(1 for record in versions if record.archived),
            "with_sources": sum(1 for record in versions if record.data_sources),
            "with_quality": sum(1 for record in versions if record.quality_results),
            "with_outputs": sum(1 for record in versions if record.output_files),
        }

    @property
    def stats(self) -> dict[str, int]:
        return self.stats_for()

    def diff_versions(self, version_id_a: str, version_id_b: str) -> list[DiffResult]:
        """对比两个版本之间的主要差异。"""
        a = self._versions.get(version_id_a)
        b = self._versions.get(version_id_b)
        if not a or not b:
            return [
                DiffResult(
                    field="版本",
                    before=version_id_a,
                    after=version_id_b,
                    changed=True,
                    summary="版本不存在",
                )
            ]

        diffs: list[DiffResult] = []

        def add(field_name: str, before: Any, after: Any, summary: str | None = None) -> None:
            changed = before != after
            diffs.append(
                DiffResult(
                    field=field_name,
                    before=before,
                    after=after,
                    changed=changed,
                    summary=summary if summary is not None else (f"{before} → {after}" if changed else "未变"),
                )
            )

        add("版本号", a.version_number, b.version_number)
        add("功能模块", a.module_name, b.module_name)
        add("版本描述", a.description, b.description)
        add("创建人", a.created_by, b.created_by)

        source_a = [str(item.get("name", "")) for item in a.data_sources]
        source_b = [str(item.get("name", "")) for item in b.data_sources]
        add("数据来源", source_a, source_b, _list_diff_summary(source_a, source_b))

        all_keys = sorted(set(a.conversion_params) | set(b.conversion_params))
        if not all_keys:
            add("转换参数", {}, {}, "未记录转换参数")
        else:
            for key in all_keys:
                add(f"参数-{key}", a.conversion_params.get(key, ""), b.conversion_params.get(key, ""))

        add("质量评分", a.quality_results.get("score", "-"), b.quality_results.get("score", "-"))
        add("质量等级", a.quality_results.get("grade", "-"), b.quality_results.get("grade", "-"))

        output_a = [str(item.get("name", "")) for item in a.output_files]
        output_b = [str(item.get("name", "")) for item in b.output_files]
        add("输出成果", output_a, output_b, _list_diff_summary(output_a, output_b))
        add("归档状态", "已归档" if a.archived else "未归档", "已归档" if b.archived else "未归档")
        add("标签", a.tags, b.tags, _list_diff_summary(a.tags, b.tags))
        return diffs

    def archive_version(self, version_id: str, archive_dir: str | Path) -> str | None:
        """归档版本元数据、追溯信息、质量记录和成果文件。"""
        record = self._versions.get(version_id)
        if not record:
            return None

        archive_root = Path(archive_dir).expanduser()
        archive_root.mkdir(parents=True, exist_ok=True)
        safe_number = re.sub(r"[^0-9A-Za-z._-]+", "_", record.version_number)
        version_dir = archive_root / f"{safe_number}_{record.version_id}"
        artifacts_dir = version_dir / "artifacts"
        version_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        copied_artifacts: list[dict[str, Any]] = []
        for item in record.output_files:
            source = Path(str(item.get("path", ""))).expanduser()
            copied = False
            destination = artifacts_dir / source.name
            if source.exists() and source.is_file():
                if not destination.exists() or destination.stat().st_mtime < source.stat().st_mtime:
                    shutil.copy2(source, destination)
                copied = True
            copied_artifacts.append(
                {
                    "name": item.get("name", source.name),
                    "source_path": str(source),
                    "archive_path": str(destination) if copied else "",
                    "copied": copied,
                }
            )

        record.archived = True
        record.archive_path = str(version_dir.resolve())
        record.lineage = _build_lineage(record)

        (version_dir / "version_metadata.json").write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (version_dir / "lineage_report.json").write_text(
            json.dumps(self.get_lineage_report(version_id), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (version_dir / "quality_report.json").write_text(
            json.dumps(record.quality_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (version_dir / "conversion_params.json").write_text(
            json.dumps(record.conversion_params, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (version_dir / "workflow_steps.json").write_text(
            json.dumps(record.workflow_steps, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (version_dir / "artifact_copy_manifest.json").write_text(
            json.dumps(copied_artifacts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.save_registry()
        return record.archive_path

    def get_lineage_report(self, version_id: str) -> dict[str, Any]:
        """获取完整的追溯链路报告。"""
        record = self._versions.get(version_id)
        if not record:
            return {}
        return {
            "version_id": record.version_id,
            "version_number": record.version_number,
            "project_name": record.project_name,
            "module_name": record.module_name,
            "created_at": record.created_at,
            "created_by": record.created_by,
            "lineage": {
                "sources": [f"{item.get('name', '')} ({item.get('format', '')})" for item in record.data_sources],
                "parameters": deepcopy(record.conversion_params),
                "workflow": [item.get("step", "") for item in record.workflow_steps],
                "quality": f"{record.quality_results.get('score', '-')}分 / {record.quality_results.get('grade', '-')}",
                "outputs": [item.get("name", "") for item in record.output_files],
            },
            "trace_chain": _trace_text(record),
            "archived": record.archived,
            "archive_path": record.archive_path,
        }

    # ------------------------------------------------------------------
    # 示例/外部清单导入
    # ------------------------------------------------------------------

    def import_manifest(self, manifest_path: str | Path, skip_duplicates: bool = True) -> list[VersionRecord]:
        """从 JSON 版本清单导入历史版本，清单中的相对路径按清单目录解析。"""
        path = Path(manifest_path).expanduser()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("版本清单根节点必须是 JSON 对象")

        project_name = str(payload.get("project_name", ""))
        module_name = str(payload.get("module_name", "模型版本管理与成果追溯模块"))
        raw_versions = payload.get("versions", [])
        if not isinstance(raw_versions, list):
            raise ValueError("versions 字段必须是数组")

        existing_keys = {
            (record.project_name, record.module_name, record.version_number, record.created_at)
            for record in self._versions.values()
        }
        imported: list[VersionRecord] = []
        for item in raw_versions:
            if not isinstance(item, dict):
                continue
            item_project = str(item.get("project_name", project_name))
            item_module = str(item.get("module_name", module_name))
            item_number = str(item.get("version_number", ""))
            item_created_at = str(item.get("created_at", ""))
            duplicate_key = (item_project, item_module, item_number, item_created_at)
            if skip_duplicates and duplicate_key in existing_keys:
                continue

            sources = _resolve_file_records(item.get("data_sources", []), path.parent)
            outputs = _resolve_file_records(item.get("output_files", []), path.parent)
            quality = _resolve_embedded_json(item.get("quality_results", {}), path.parent)

            record = self.create_version(
                project_name=item_project,
                module_name=item_module,
                description=str(item.get("description", "")),
                version_number=item_number,
                created_by=str(item.get("created_by", "")),
                created_at=item_created_at,
                version_id=str(item.get("version_id", "")),
                data_sources=sources,
                conversion_params=dict(item.get("conversion_params", {}) or {}),
                quality_results=quality,
                workflow_steps=list(item.get("workflow_steps", []) or []),
                output_files=outputs,
                tags=[str(tag) for tag in (item.get("tags", []) or [])],
                archived=bool(item.get("archived", False)),
                archive_path=str(item.get("archive_path", "")),
                ensure_unique_number=not bool(item_number),
            )
            imported.append(record)
            existing_keys.add((record.project_name, record.module_name, record.version_number, record.created_at))

        self.save_registry()
        return imported


# ============================================================================
# 追溯链辅助
# ============================================================================


def _build_lineage(record: VersionRecord) -> dict[str, Any]:
    return {
        "trace_id": record.version_id,
        "trace_type": "model_conversion",
        "project_name": record.project_name,
        "version_number": record.version_number,
        "phases": [
            {"phase": "数据接入", "records": [item.get("name", "") for item in record.data_sources]},
            {"phase": "参数配置", "records": deepcopy(record.conversion_params)},
            {"phase": "流程执行", "records": [item.get("step", "") for item in record.workflow_steps]},
            {"phase": "质量检查", "records": deepcopy(record.quality_results)},
            {"phase": "成果输出", "records": [item.get("name", "") for item in record.output_files]},
        ],
    }


def _trace_text(record: VersionRecord) -> str:
    segments: list[str] = []
    if record.data_sources:
        segments.append("数据源: " + ", ".join(str(item.get("name", "")) for item in record.data_sources[:3]))
    if record.conversion_params:
        segments.append(
            "参数: "
            + ", ".join(f"{key}={value}" for key, value in list(record.conversion_params.items())[:3])
        )
    if record.workflow_steps:
        segments.append("流程: " + " / ".join(str(item.get("step", "")) for item in record.workflow_steps[:3]))
    if record.quality_results:
        segments.append(f"质量: {record.quality_results.get('score', '-')}分")
    if record.output_files:
        segments.append("成果: " + ", ".join(str(item.get("name", "")) for item in record.output_files[:3]))
    prefix = f"版本 {record.version_number} ({record.version_id})"
    return prefix + (" | " + " → ".join(segments) if segments else "")


def _parse_datetime(value: str) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now()


def _counter_from_id(version_id: str) -> int:
    match = re.search(r"-(\d{4,})$", version_id)
    return int(match.group(1)) if match else 0


def _list_diff_summary(before: Iterable[str], after: Iterable[str]) -> str:
    before_set = set(before)
    after_set = set(after)
    added = sorted(after_set - before_set)
    removed = sorted(before_set - after_set)
    if not added and not removed:
        return "未变"
    parts: list[str] = []
    if added:
        parts.append("新增: " + "、".join(added))
    if removed:
        parts.append("移除: " + "、".join(removed))
    return "；".join(parts)


def _file_record(path_value: str | Path, base_dir: Path | None = None, name: str = "", file_format: str = "") -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if base_dir and not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve() if path.exists() else path
    return {
        "name": name or path.name,
        "path": str(path),
        "format": file_format or path.suffix.lower(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
        "exists": path.exists() and path.is_file(),
    }


def _resolve_file_records(raw_records: Any, base_dir: Path) -> list[dict[str, Any]]:
    if not isinstance(raw_records, list):
        return []
    records: list[dict[str, Any]] = []
    for item in raw_records:
        if isinstance(item, str):
            records.append(_file_record(item, base_dir=base_dir))
        elif isinstance(item, dict):
            path_value = str(item.get("path", ""))
            record = _file_record(
                path_value,
                base_dir=base_dir,
                name=str(item.get("name", "")),
                file_format=str(item.get("format", "")),
            )
            for key, value in item.items():
                if key not in {"name", "path", "format", "size_bytes", "exists"}:
                    record[key] = value
            records.append(record)
    return records


def _resolve_embedded_json(raw_value: Any, base_dir: Path) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        if set(raw_value) == {"path"} or ("path" in raw_value and len(raw_value) <= 2):
            path = Path(str(raw_value.get("path", "")))
            if not path.is_absolute():
                path = base_dir / path
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return payload if isinstance(payload, dict) else {}
        return deepcopy(raw_value)
    if isinstance(raw_value, str):
        path = Path(raw_value)
        if not path.is_absolute():
            path = base_dir / path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


# ============================================================================
# 全局单例
# ============================================================================


_DEFAULT_REGISTRY = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "version_management"
    / "version_registry.json"
)
_vm = VersionManager(_DEFAULT_REGISTRY)


def get_manager() -> VersionManager:
    return _vm


# ============================================================================
# 便捷函数
# ============================================================================


def create_version_from_task(
    project_name: str = "",
    module_name: str = "",
    description: str = "",
    version_number: str = "",
    created_by: str = "",
    data_files: list[str] | None = None,
    conversion_params: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
    workflow_steps: list[dict[str, Any]] | None = None,
    output_files: list[str] | None = None,
    tags: list[str] | None = None,
) -> VersionRecord:
    """从一次转换任务快速创建版本记录。"""
    manager = get_manager()
    sources = [_file_record(file_path) for file_path in (data_files or [])]
    outputs = [_file_record(file_path) for file_path in (output_files or [])]

    workflow = workflow_steps or [
        {"step": "数据接入", "status": "完成", "timestamp": datetime.now().isoformat(timespec="seconds")},
        {"step": "参数配置", "status": "完成"},
        {"step": "转换执行", "status": "完成"},
        {"step": "质量检查", "status": "完成" if quality_report else "未提供"},
        {"step": "成果登记", "status": "完成" if outputs else "未提供"},
    ]

    return manager.create_version(
        project_name=project_name,
        module_name=module_name,
        description=description,
        version_number=version_number,
        created_by=created_by,
        data_sources=sources,
        conversion_params=conversion_params or {},
        quality_results=quality_report or {},
        workflow_steps=workflow,
        output_files=outputs,
        tags=tags,
    )


def import_versions_from_manifest(manifest_path: str | Path, skip_duplicates: bool = True) -> list[VersionRecord]:
    return get_manager().import_manifest(manifest_path, skip_duplicates=skip_duplicates)


def build_version_report(
    file_paths: list[str] | None = None,
    project_name: str = "默认项目",
    module_name: str = "",
    version_number: str = "",
) -> dict[str, Any]:
    """生成只读版本管理摘要，不在报告阶段隐式创建版本。"""
    manager = get_manager()
    all_versions = manager.list_versions(project_name=project_name, module_name=module_name)
    current_files = [_file_record(file_path) for file_path in (file_paths or [])]

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_name": project_name,
        "module_name": module_name,
        "manager_stats": manager.stats_for(project_name=project_name, module_name=module_name),
        "versions": [],
        "current_files": current_files,
    }

    for record in all_versions:
        report["versions"].append(
            {
                "version_id": record.version_id,
                "version_number": record.version_number,
                "description": record.description,
                "created_at": record.created_at,
                "created_by": record.created_by,
                "source_count": len(record.data_sources),
                "output_count": len(record.output_files),
                "quality_score": record.quality_results.get("score", "-") if record.quality_results else "-",
                "quality_grade": record.quality_results.get("grade", "-") if record.quality_results else "-",
                "archived": record.archived,
                "archive_path": record.archive_path,
                "tags": list(record.tags),
                "trace_chain": _trace_text(record),
            }
        )

    current = next((record for record in all_versions if record.version_number == version_number), None)
    latest = all_versions[0] if all_versions else None
    report["summary"] = {
        "total_versions": len(all_versions),
        "latest_version": latest.version_number if latest else None,
        "latest_id": latest.version_id if latest else None,
        "current_version": current.version_number if current else (version_number or None),
        "current_id": current.version_id if current else None,
    }
    return report


__all__ = [
    "VersionRecord",
    "VersionManager",
    "DiffResult",
    "get_manager",
    "create_version_from_task",
    "import_versions_from_manifest",
    "build_version_report",
]
