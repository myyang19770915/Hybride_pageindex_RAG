import logging
from concurrent.futures import Future, ThreadPoolExecutor

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class JobQueue:
    """In-process background job queue for ingestion.

    This keeps ingestion off the request path without requiring an external
    broker, which suits a single-node on-prem deployment. The ``submit``
    contract (enqueue a job_id, process asynchronously) is intentionally narrow
    so it can be swapped for a Celery/RQ task without touching call sites.
    """

    def __init__(self, max_workers: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ingest"
        )

    def submit(self, job_id: str) -> Future:
        return self._executor.submit(self._run, job_id)

    def _run(self, job_id: str) -> str:
        # Imported lazily to avoid a circular import with the document service.
        from app.services.documents import DocumentService

        try:
            job = DocumentService().process_job(job_id)
            logger.info("Background ingestion finished job %s with status %s", job_id, job.status)
            return job.status.value
        except Exception:
            logger.exception("Background ingestion failed for job %s", job_id)
            raise


_job_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue(max_workers=get_settings().worker_max_workers)
    return _job_queue
