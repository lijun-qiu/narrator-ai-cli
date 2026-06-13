"""In-memory task registry + on-disk file metadata."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gateway.config import settings

TASK_TYPE_MAP = {
    "popular_learning": 1,
    "generate_writing": 2,
    "video_composing": 3,
    "voice_clone": 4,
    "tts": 5,
    "clip_data": 6,
    "magic_video": 7,
    "fast_writing": 9,
    "fast_clip_data": 10,
}


def new_id() -> str:
    return uuid.uuid4().hex


def new_order_num(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class FileRecord:
    file_id: str
    file_name: str
    file_size: int
    content_type: str
    category: int  # 1=video 2=audio 3=image 4=doc
    object_key: str
    path: Path
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    status: int  # 0 init 1 progress 2 success 3 failed
    body: dict
    task_order_num: str = ""
    files: list[dict] = field(default_factory=list)
    results: dict = field(default_factory=dict)
    error_message: str = ""
    consumed_points: float = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    type_name: str = ""


class Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileRecord] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._order_index: dict[str, str] = {}  # task_order_num -> task_id
        self._meta_path = settings.data_dir / "store.json"
        self._load()

    def _load(self) -> None:
        if not self._meta_path.exists():
            return
        try:
            raw = json.loads(self._meta_path.read_text(encoding="utf-8"))
            for f in raw.get("files", []):
                rec = FileRecord(**{**f, "path": Path(f["path"])})
                self._files[rec.file_id] = rec
            for t in raw.get("tasks", []):
                rec = TaskRecord(**t)
                self._tasks[rec.task_id] = rec
                if rec.task_order_num:
                    self._order_index[rec.task_order_num] = rec.task_id
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    def _persist(self) -> None:
        payload = {
            "files": [{**asdict(f), "path": str(f.path)} for f in self._files.values()],
            "tasks": [asdict(t) for t in self._tasks.values()],
        }
        self._meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- files ---
    def add_file(self, file_name: str, file_size: int, content_type: str, data: bytes) -> FileRecord:
        file_id = new_id()
        suffix = Path(file_name).suffix.lower()
        category = 1 if suffix in {".mp4", ".mkv", ".mov", ".avi"} else 2 if suffix in {".mp3", ".wav", ".m4a"} else 4
        object_key = f"uploads/{file_id}{suffix}"
        path = settings.data_dir / "files" / f"{file_id}{suffix}"
        path.write_bytes(data)
        rec = FileRecord(
            file_id=file_id,
            file_name=file_name,
            file_size=file_size,
            content_type=content_type,
            category=category,
            object_key=object_key,
            path=path,
        )
        with self._lock:
            self._files[file_id] = rec
            self._persist()
        return rec

    def register_pending_upload(
        self, file_name: str, file_size: int, content_type: str
    ) -> tuple[str, str, Path]:
        file_id = new_id()
        suffix = Path(file_name).suffix.lower()
        object_key = f"uploads/{file_id}{suffix}"
        path = settings.data_dir / "files" / f"{file_id}{suffix}"
        rec = FileRecord(
            file_id=file_id,
            file_name=file_name,
            file_size=file_size,
            content_type=content_type,
            category=0,
            object_key=object_key,
            path=path,
        )
        with self._lock:
            self._files[file_id] = rec
            self._persist()
        return file_id, object_key, path

    def finalize_upload(self, file_id: str, file_size: int) -> FileRecord | None:
        with self._lock:
            rec = self._files.get(file_id)
            if not rec or not rec.path.exists():
                return None
            suffix = rec.path.suffix.lower()
            rec.file_size = file_size
            rec.category = 1 if suffix in {".mp4", ".mkv", ".mov"} else 2 if suffix in {".mp3", ".wav", ".m4a"} else 4
            self._persist()
            return rec

    def get_file(self, file_id: str) -> FileRecord | None:
        return self._files.get(file_id)

    def read_file_bytes(self, file_id: str) -> bytes | None:
        rec = self._files.get(file_id)
        if rec and rec.path.exists():
            return rec.path.read_bytes()
        return None

    def list_files(self, page: int = 1, page_size: int = 10, search: str | None = None) -> dict:
        items = list(self._files.values())
        if search:
            items = [f for f in items if search.lower() in f.file_name.lower()]
        items.sort(key=lambda x: x.created_at, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": [
                {
                    "file_id": f.file_id,
                    "file_name": f.file_name,
                    "file_size": f.file_size,
                    "category": f.category,
                    "created_at": f.created_at,
                }
                for f in page_items
            ],
        }

    def save_output(self, file_name: str, data: bytes, content_type: str = "application/json") -> FileRecord:
        return self.add_file(file_name, len(data), content_type, data)

    # --- tasks ---
    def create_task(self, task_type: str, body: dict) -> TaskRecord:
        task_id = new_id()
        type_name = task_type.replace("_", " ").title()
        rec = TaskRecord(task_id=task_id, task_type=task_type, status=0, body=body, type_name=type_name)
        with self._lock:
            self._tasks[task_id] = rec
            self._persist()
        return rec

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def get_task_by_order(self, order_num: str) -> TaskRecord | None:
        tid = self._order_index.get(order_num)
        return self._tasks.get(tid) if tid else None

    def find_clip_for_writing_order(self, writing_order_num: str) -> TaskRecord | None:
        """Find completed clip_data task whose body.order_num matches writing order."""
        for t in self._tasks.values():
            if t.task_type != "clip_data" or t.status != 2:
                continue
            if t.body.get("order_num") == writing_order_num:
                return t
        return None

    def update_task(self, task_id: str, **kwargs: Any) -> TaskRecord | None:
        with self._lock:
            rec = self._tasks.get(task_id)
            if not rec:
                return None
            for k, v in kwargs.items():
                setattr(rec, k, v)
            if rec.task_order_num:
                self._order_index[rec.task_order_num] = rec.task_id
            self._persist()
            return rec

    def list_tasks(self, page: int = 1, limit: int = 10, status: int | None = None, task_type: int | None = None) -> dict:
        items = list(self._tasks.values())
        if status is not None:
            items = [t for t in items if t.status == status]
        if task_type is not None:
            rev = {v: k for k, v in TASK_TYPE_MAP.items()}
            name = rev.get(task_type)
            if name:
                items = [t for t in items if t.task_type == name]
        items.sort(key=lambda x: x.created_at, reverse=True)
        total = len(items)
        start = (page - 1) * limit
        page_items = items[start : start + limit]
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "task_id": t.task_id,
                    "type_name": t.type_name,
                    "status": t.status,
                    "consumed_points": t.consumed_points,
                    "created_at": t.created_at,
                }
                for t in page_items
            ],
        }

    def task_to_query(self, rec: TaskRecord) -> dict:
        file_ids = [f["file_id"] for f in rec.files if f.get("file_id")]
        if not file_ids and rec.results.get("file_ids"):
            file_ids = rec.results["file_ids"]
        return {
            "task_id": rec.task_id,
            "status": rec.status,
            "task_order_num": rec.task_order_num,
            "files": rec.files,
            "results": {**rec.results, "file_ids": file_ids},
            "consumed_points": rec.consumed_points,
            "error_message_slug": rec.error_message if rec.status == 3 else "",
            "type_name": rec.type_name,
            "created_at": rec.created_at,
        }


store = Store()
