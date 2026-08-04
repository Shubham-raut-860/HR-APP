from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from threading import RLock

from fastapi import HTTPException, status

from app.config import settings
from app.schemas.a2a import AgentArtifact, AgentTask, TaskStatus
from app.schemas.a2a import A2AAuditEvent

logger = logging.getLogger(__name__)


class A2ATaskManager:
    def __init__(
        self,
        *,
        max_tasks: int = 1000,
        ttl_seconds: float = 3600.0,
        persistence_enabled: bool = False,
        persistence_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._max_tasks = max(10, int(max_tasks))
        self._ttl_seconds = max(300.0, float(ttl_seconds))
        self._persistence_enabled = bool(persistence_enabled)
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._tasks: dict[str, AgentTask] = {}
        self._artifacts: dict[str, AgentArtifact] = {}
        self._task_artifacts: dict[str, list[str]] = {}
        self._audit_events: list[A2AAuditEvent] = []
        self._created_monotonic: dict[str, float] = {}
        self._lock = RLock()
        self._load_snapshot()

    def _load_snapshot(self) -> None:
        if not self._persistence_enabled or self._persistence_path is None or not self._persistence_path.exists():
            return

        try:
            payload = json.loads(self._persistence_path.read_text(encoding="utf-8"))
            now_epoch = time.time()
            loaded_tasks = [
                AgentTask.model_validate(item)
                for item in payload.get("tasks", [])
                if isinstance(item, dict)
            ]
            tasks = {
                task.id: task
                for task in loaded_tasks
                if (now_epoch - task.created_at.timestamp()) <= self._ttl_seconds
            }
            artifacts = {
                artifact.id: artifact
                for artifact in (
                    AgentArtifact.model_validate(item)
                    for item in payload.get("artifacts", [])
                    if isinstance(item, dict)
                )
            }
            task_artifacts = {
                str(task_id): [str(artifact_id) for artifact_id in artifact_ids if str(artifact_id) in artifacts]
                for task_id, artifact_ids in (payload.get("task_artifacts") or {}).items()
                if isinstance(artifact_ids, list) and str(task_id) in tasks
            }
            audit_events = [
                A2AAuditEvent.model_validate(item)
                for item in payload.get("audit_events", [])
                if isinstance(item, dict)
            ][-1000:]
        except Exception as exc:
            logger.warning("Failed to load A2A persistence snapshot: %s", exc)
            return

        now = time.monotonic()
        self._tasks = tasks
        referenced_artifact_ids = {
            artifact_id
            for artifact_ids in task_artifacts.values()
            for artifact_id in artifact_ids
        }
        self._artifacts = {
            artifact_id: artifact
            for artifact_id, artifact in artifacts.items()
            if artifact_id in referenced_artifact_ids
        }
        self._task_artifacts = task_artifacts
        self._audit_events = audit_events
        self._created_monotonic = {task_id: now for task_id in tasks}
        logger.info("Loaded %d A2A task(s) from persistence snapshot.", len(tasks))

    def _persist_locked(self) -> None:
        if not self._persistence_enabled or self._persistence_path is None:
            return

        payload = {
            "version": 1,
            "tasks": [task.model_dump(mode="json") for task in self._tasks.values()],
            "artifacts": [artifact.model_dump(mode="json") for artifact in self._artifacts.values()],
            "task_artifacts": self._task_artifacts,
            "audit_events": [event.model_dump(mode="json") for event in self._audit_events[-1000:]],
            "saved_at_epoch": time.time(),
        }
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persistence_path.with_suffix(self._persistence_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_path, self._persistence_path)
        except Exception as exc:
            logger.warning("Failed to persist A2A task snapshot: %s", exc)

    def _evict_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            task_id
            for task_id, created in self._created_monotonic.items()
            if (now - created) > self._ttl_seconds
        ]
        for task_id in expired:
            self._delete_task_locked(task_id)

        if len(self._tasks) <= self._max_tasks:
            return

        oldest = sorted(self._created_monotonic.items(), key=lambda item: item[1])
        for task_id, _ in oldest[: max(0, len(self._tasks) - self._max_tasks)]:
            self._delete_task_locked(task_id)

    def _delete_task_locked(self, task_id: str) -> None:
        for artifact_id in self._task_artifacts.pop(task_id, []):
            self._artifacts.pop(artifact_id, None)
        self._tasks.pop(task_id, None)
        self._created_monotonic.pop(task_id, None)

    def create(self, task: AgentTask) -> AgentTask:
        with self._lock:
            self._evict_expired_locked()
            self._tasks[task.id] = task
            self._created_monotonic[task.id] = time.monotonic()
            self._task_artifacts.setdefault(task.id, [])
            self._persist_locked()
            return task

    def update(self, task: AgentTask) -> AgentTask:
        with self._lock:
            if task.id not in self._tasks:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A task not found")
            self._tasks[task.id] = task
            self._persist_locked()
            return task

    def add_artifact(self, owner_id: str, artifact: AgentArtifact) -> AgentArtifact:
        with self._lock:
            task = self.require_task(artifact.task_id, owner_id)
            self._artifacts[artifact.id] = artifact
            artifact_ids = self._task_artifacts.setdefault(task.id, [])
            if artifact.id not in artifact_ids:
                artifact_ids.append(artifact.id)
            task.artifact_ids = list(artifact_ids)
            self._tasks[task.id] = task
            self._persist_locked()
            return artifact

    def require_task(self, task_id: str, owner_id: str) -> AgentTask:
        with self._lock:
            self._evict_expired_locked()
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A task not found")
            if task.owner_id != owner_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A2A task access denied")
            return task

    def list_artifacts(self, task_id: str, owner_id: str) -> list[AgentArtifact]:
        with self._lock:
            self.require_task(task_id, owner_id)
            return [
                self._artifacts[artifact_id]
                for artifact_id in self._task_artifacts.get(task_id, [])
                if artifact_id in self._artifacts
            ]

    def require_artifact(self, task_id: str, artifact_id: str, owner_id: str) -> AgentArtifact:
        with self._lock:
            self.require_task(task_id, owner_id)
            if artifact_id not in self._task_artifacts.get(task_id, []):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A artifact not found")
            artifact = self._artifacts.get(artifact_id)
            if artifact is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A2A artifact not found")
            return artifact

    def mark_failed(self, task: AgentTask, error: str) -> AgentTask:
        task.status = TaskStatus.failed
        task.error = error[:2000]
        return self.update(task)

    def record_audit(self, event: A2AAuditEvent) -> A2AAuditEvent:
        with self._lock:
            self._audit_events.append(event)
            if len(self._audit_events) > 1000:
                self._audit_events = self._audit_events[-1000:]
            self._persist_locked()
            return event

    def recent_audit(self, limit: int = 100) -> list[A2AAuditEvent]:
        n = max(1, min(1000, int(limit)))
        with self._lock:
            return list(reversed(self._audit_events[-n:]))


a2a_task_manager = A2ATaskManager(
    persistence_enabled=settings.A2A_PERSISTENCE_ENABLED,
    persistence_path=settings.A2A_PERSISTENCE_PATH,
)
