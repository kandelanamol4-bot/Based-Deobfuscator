"""Job model + async manager with state machine and timeouts."""
from __future__ import annotations
import asyncio
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    AWAITING_SELECTION = "awaiting_selection"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    user_id: int
    filename: str
    status: JobStatus = JobStatus.PENDING
    stage: str = "Receiving source..."
    engine_id: str | None = None
    attempts: list[dict] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    processing_time: float = 0.0
    original_size: int = 0
    output_size: int = 0
    message_id: int | None = None
    channel_id: int | None = None
    cancelled: asyncio.Event = field(default_factory=asyncio.Event, repr=False, compare=False)

    def touch(self, stage: str | None = None, status: JobStatus | None = None):
        self.updated_at = time.time()
        if stage:
            self.stage = stage
        if status:
            self.status = status


def new_job_id() -> str:
    return "BD-" + secrets.token_hex(4).upper()


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, user_id: int, filename: str, size: int) -> Job:
        async with self._lock:
            job = Job(id=new_job_id(), user_id=user_id, filename=filename, original_size=size)
            self._jobs[job.id] = job
            return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id.upper())

    async def update(self, job: Job, **kw) -> Job:
        async with self._lock:
            for k, v in kw.items():
                setattr(job, k, v)
            job.updated_at = time.time()
            return job

    async def user_active_count(self, user_id: int) -> int:
        async with self._lock:
            return sum(
                1 for j in self._jobs.values()
                if j.user_id == user_id and j.status in (
                    JobStatus.PENDING, JobStatus.ANALYZING,
                    JobStatus.AWAITING_SELECTION, JobStatus.RUNNING,
                    JobStatus.VALIDATING)
            )

    async def recent_for_user(self, user_id: int, limit: int = 5) -> list[Job]:
        async with self._lock:
            mine = [j for j in self._jobs.values() if j.user_id == user_id]
            return sorted(mine, key=lambda j: j.created_at, reverse=True)[:limit]

    async def recover_on_restart(self):
        """Mark orphaned active jobs as failed after restart."""
        async with self._lock:
            for j in self._jobs.values():
                if j.status in (JobStatus.PENDING, JobStatus.ANALYZING,
                                JobStatus.AWAITING_SELECTION, JobStatus.RUNNING,
                                JobStatus.VALIDATING):
                    j.status = JobStatus.FAILED
                    j.error = "Bot restarted during processing."
