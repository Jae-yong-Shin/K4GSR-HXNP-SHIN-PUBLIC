"""
batch_manager.py - Sequential batch job queue for reconstructions
"""
import uuid
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BatchJob:
    job_id: str = ''
    engine: str = 'DM'
    params: dict = field(default_factory=dict)
    status: str = 'pending'       # pending, running, completed, failed, cancelled
    history_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: float = 0

    def __post_init__(self):
        if not self.job_id:
            self.job_id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self):
        return {
            'job_id': self.job_id,
            'engine': self.engine,
            'params': {k: v for k, v in self.params.items()
                       if isinstance(v, (int, float, str, bool))},
            'status': self.status,
            'history_id': self.history_id,
        }


class BatchManager:
    """Manages a queue of reconstruction jobs."""

    def __init__(self):
        self.queue: List[BatchJob] = []
        self.running = False
        self._current_index = 0

    def add_job(self, engine, params):
        """Add a job to the queue. Returns job_id."""
        job = BatchJob(engine=engine, params=dict(params))
        self.queue.append(job)
        return job.job_id

    def remove_job(self, job_id):
        """Remove a pending job from the queue."""
        self.queue = [j for j in self.queue if j.job_id != job_id or j.status != 'pending']

    def get_queue_status(self):
        """Return list of all jobs with their status."""
        return {
            'queue': [j.to_dict() for j in self.queue],
            'running': self.running,
            'current_index': self._current_index,
        }

    def get_next_pending(self):
        """Get the next pending job, or None if all done."""
        for i, job in enumerate(self.queue):
            if job.status == 'pending':
                self._current_index = i
                return job
        return None

    def mark_running(self, job_id):
        for j in self.queue:
            if j.job_id == job_id:
                j.status = 'running'

    def mark_completed(self, job_id, history_id=None):
        for j in self.queue:
            if j.job_id == job_id:
                j.status = 'completed'
                j.history_id = history_id

    def mark_failed(self, job_id, error_message=''):
        for j in self.queue:
            if j.job_id == job_id:
                j.status = 'failed'
                j.error_message = error_message

    def clear_completed(self):
        """Remove completed/failed jobs."""
        self.queue = [j for j in self.queue if j.status == 'pending']

    def reset(self):
        """Clear all jobs."""
        self.queue.clear()
        self.running = False
        self._current_index = 0
