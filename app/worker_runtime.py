"""Opt-in single-process durable job polling loop with liveness heartbeat."""
from __future__ import annotations
import asyncio, logging, os, uuid
from .job_handlers import default_job_handlers
from .job_payload_store import JobPayloadError, _cipher
from .job_worker import run_once
from .worker_heartbeat import record_worker_heartbeat
logger = logging.getLogger(__name__)

def worker_enabled() -> bool:
    return os.getenv("JOB_WORKER_ENABLED", "false").strip().lower() in {"1", "true", "yes"}

def worker_ready() -> bool:
    if not worker_enabled(): return False
    try:
        _cipher()
        return True
    except JobPayloadError:
        return False

async def _heartbeat_loop(worker_id: str) -> None:
    while True:
        try:
            await asyncio.to_thread(record_worker_heartbeat, worker_id, "running")
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Worker heartbeat write failed")
            await asyncio.sleep(15)

async def run_worker_loop() -> None:
    if not worker_enabled():
        logger.info("Durable job worker disabled by configuration")
        return
    if not worker_ready():
        logger.error("Durable job worker not started: JOB_PAYLOAD_ENCRYPTION_KEY is missing")
        return
    try: poll_interval = float(os.getenv("JOB_WORKER_POLL_SECONDS", "2"))
    except ValueError: poll_interval = 2.0
    poll_interval = max(0.5, min(poll_interval, 30.0))
    worker_id = "central-" + str(uuid.uuid4())
    handlers = default_job_handlers()
    heartbeat_task = None
    try:
        await asyncio.to_thread(record_worker_heartbeat, worker_id, "starting")
        heartbeat_task = asyncio.create_task(_heartbeat_loop(worker_id))
        logger.info("Durable job worker started with %d registered handler(s)", len(handlers))
        while True:
            try:
                outcome = await run_once(worker_id, handlers, lease_seconds=120)
                if outcome == "idle": await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Durable job worker loop iteration failed")
                await asyncio.to_thread(record_worker_heartbeat, worker_id, "degraded")
                await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        logger.info("Durable job worker shutting down")
        raise
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try: await heartbeat_task
            except asyncio.CancelledError: pass
        try: await asyncio.to_thread(record_worker_heartbeat, worker_id, "stopped")
        except Exception: logger.exception("Could not persist worker shutdown state")