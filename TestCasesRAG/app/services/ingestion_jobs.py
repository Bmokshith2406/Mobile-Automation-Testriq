import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson.binary import Binary
from pymongo import ReturnDocument

from app.core.config import get_settings
from app.core.logging import logger
from app.core.metrics import Metrics
from app.db.mongo import build_id_query, get_ingestion_jobs_collection
from app.services.upload_pipeline import process_upload_bytes, validate_upload_filename

settings = get_settings()


class IngestionJobManager:
    """Persistent background ingestion queue backed by MongoDB job records."""

    def __init__(self):
        self.queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=settings.INGESTION_QUEUE_MAX_SIZE
        )
        self.workers: List[asyncio.Task] = []
        self.started = False

    async def start(self) -> None:
        if self.started:
            return

        await self._cleanup_old_jobs()
        await self._requeue_pending_jobs()

        self.started = True
        self.workers = [
            asyncio.create_task(
                self._worker_loop(worker_index),
                name=f"ingestion-worker-{worker_index}",
            )
            for worker_index in range(settings.INGESTION_WORKER_COUNT)
        ]

        logger.info(
            "ingestion_job_manager_started",
            extra={
                "workers": settings.INGESTION_WORKER_COUNT,
                "queue_max_size": settings.INGESTION_QUEUE_MAX_SIZE,
            },
        )

    async def stop(self) -> None:
        for worker in self.workers:
            worker.cancel()

        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)

        self.workers = []
        self.started = False
        logger.info("ingestion_job_manager_stopped")

    async def submit_job(
        self,
        filename: str,
        contents: bytes,
        requested_by: Optional[dict],
    ) -> Dict[str, Any]:
        validate_upload_filename(filename)

        if self.queue.full():
            raise RuntimeError("Background ingestion queue is full. Please retry later.")

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        job_doc = {
            "_id": job_id,
            "filename": filename,
            "status": "queued",
            "requested_by": requested_by or {},
            "payload": Binary(contents),
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
            "progress": {
                "stage": "queued",
            },
        }

        col = get_ingestion_jobs_collection()
        await col.insert_one(job_doc)
        await self.queue.put(job_id)
        Metrics.record_background_job("queued")

        logger.info(
            "ingestion_job_enqueued",
            extra={"job_id": job_id, "filename": filename},
        )

        return {
            "job_id": job_id,
            "status": "queued",
            "filename": filename,
            "created_at": now.isoformat(),
        }

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        col = get_ingestion_jobs_collection()
        job = await col.find_one(build_id_query(job_id))
        return self._serialize_job(job)

    async def list_jobs(
        self,
        limit: int = 20,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        col = get_ingestion_jobs_collection()
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status

        cursor = col.find(query).sort("created_at", -1).limit(limit)
        jobs = []
        async for job in cursor:
            jobs.append(self._serialize_job(job))
        return jobs

    def get_runtime_stats(self) -> Dict[str, Any]:
        return {
            "started": self.started,
            "worker_count": len(self.workers),
            "active_workers": sum(1 for worker in self.workers if not worker.done()),
            "queue_size": self.queue.qsize(),
            "queue_max_size": settings.INGESTION_QUEUE_MAX_SIZE,
        }

    async def _requeue_pending_jobs(self) -> None:
        col = get_ingestion_jobs_collection()

        await col.update_many(
            {"status": "processing"},
            {
                "$set": {
                    "status": "queued",
                    "updated_at": datetime.now(timezone.utc),
                    "progress.stage": "queued",
                }
            },
        )

        pending_ids = await col.find(
            {"status": "queued"},
            {"_id": 1},
        ).to_list(length=settings.INGESTION_QUEUE_MAX_SIZE)

        for job in pending_ids:
            if self.queue.full():
                break
            await self.queue.put(str(job["_id"]))

    async def _cleanup_old_jobs(self) -> None:
        col = get_ingestion_jobs_collection()
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.INGESTION_JOB_RETENTION_HOURS
        )
        await col.delete_many(
            {
                "status": {"$in": ["completed", "failed"]},
                "updated_at": {"$lt": cutoff},
            }
        )

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            job_id = None
            queued_item = False
            try:
                try:
                    job_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                    queued_item = True
                except asyncio.TimeoutError:
                    job_id = None

                processed = False
                if job_id is not None:
                    processed = await self._process_job(job_id, worker_index)

                if not processed:
                    processed = await self._process_next_available_job(worker_index)

                if not processed:
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "ingestion_worker_iteration_failed",
                    extra={"job_id": job_id, "worker_index": worker_index},
                    exc_info=True,
                )
            finally:
                if queued_item:
                    self.queue.task_done()

    async def _claim_job(self, query: Dict[str, Any], worker_index: int) -> Optional[Dict[str, Any]]:
        col = get_ingestion_jobs_collection()
        now = datetime.now(timezone.utc)
        return await col.find_one_and_update(
            query,
            {
                "$set": {
                    "status": "processing",
                    "updated_at": now,
                    "started_at": now,
                    "error": None,
                    "progress.stage": "processing",
                    "progress.worker_index": worker_index,
                },
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )

    async def _run_claimed_job(self, job: Dict[str, Any], worker_index: int) -> bool:
        col = get_ingestion_jobs_collection()
        job_id = str(job["_id"])
        Metrics.record_background_job("processing")

        try:
            raw_payload = job.get("payload") or b""
            contents = bytes(raw_payload)
            result = await process_upload_bytes(
                filename=job.get("filename", ""),
                contents=contents,
                current_user=job.get("requested_by") or None,
                audit_endpoint=f"/api/upload/jobs/{job_id}",
            )

            completed_at = datetime.now(timezone.utc)
            await col.update_one(
                build_id_query(job_id),
                {
                    "$set": {
                        "status": "completed",
                        "updated_at": completed_at,
                        "completed_at": completed_at,
                        "result": result,
                        "error": None,
                        "progress.stage": "completed",
                    },
                    "$unset": {
                        "payload": "",
                    },
                },
            )
            Metrics.record_background_job("completed")

            logger.info(
                "ingestion_job_completed",
                extra={"job_id": job_id, "worker_index": worker_index},
            )
            return True

        except Exception as err:
            completed_at = datetime.now(timezone.utc)
            await col.update_one(
                build_id_query(job_id),
                {
                    "$set": {
                        "status": "failed",
                        "updated_at": completed_at,
                        "completed_at": completed_at,
                        "error": str(err),
                        "progress.stage": "failed",
                    },
                    "$unset": {
                        "payload": "",
                    },
                },
            )
            Metrics.record_background_job("failed")

            logger.error(
                "ingestion_job_failed",
                extra={"job_id": job_id, "worker_index": worker_index, "error": str(err)},
                exc_info=True,
            )
            return True
        finally:
            await self._cleanup_old_jobs()

    async def _process_job(self, job_id: str, worker_index: int) -> bool:
        job = await self._claim_job(
            {
                **build_id_query(job_id),
                "status": "queued",
            },
            worker_index,
        )
        if not job:
            return False
        return await self._run_claimed_job(job, worker_index)

    async def _process_next_available_job(self, worker_index: int) -> bool:
        job = await self._claim_job({"status": "queued"}, worker_index)
        if not job:
            return False
        return await self._run_claimed_job(job, worker_index)

    def _serialize_job(self, job: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not job:
            return None

        serialized = dict(job)
        serialized["id"] = str(serialized.pop("_id"))
        serialized.pop("payload", None)

        for field in ("created_at", "updated_at", "started_at", "completed_at"):
            if serialized.get(field) and hasattr(serialized[field], "isoformat"):
                serialized[field] = serialized[field].isoformat()

        requested_by = serialized.get("requested_by") or {}
        serialized["requested_by"] = {
            "id": requested_by.get("id"),
            "username": requested_by.get("username"),
            "role": requested_by.get("role"),
        }
        return serialized


ingestion_job_manager = IngestionJobManager()
