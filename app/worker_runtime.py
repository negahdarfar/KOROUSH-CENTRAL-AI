"""Opt-in single-process durable job polling loop."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from .job_handlers import default_job_handlers
from .job_worker import run_once

logger = logging.getLogger(__name__)


def worker_enabled() -> bool:
    return os.getenv("JOB_WORKER_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


async def run_worker_loop() -> None:
    if not worker_enabled():
        logger.info("Durable job worker disabled by configuration")
        return
    if not os.getenv("JOB_PAYLOAD_ENCRYPTION_KEY", "").strip():
        logger.error("Durable job worker not started: JOB_PAYLOAD_ENCRYPTION_KEY is missing")
        return
    try:
        poll_interval = float(os.getenv("JOB_WORKER_POLL_SECONDS", "2"))
    except ValueError:
        poll_interval = 2.0
    poll_interval = max(0.5, min(poll_interval, 30.0))
    worker_id = "central-" + str(uuid.uuid4())
    handlers = default_job_handlers()
    logger.info("Durable job worker started with %d registered handler(s)", len(handlers))
    while True:
        try:
            outcome = await run_once(worker_id, handlers, lease_seconds=120)
            if outcome == "idle":
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Durable job worker shutting down")
            raise
        except Exception:
            logger.exception("Durable job worker loop iteration failed")
            await asyncio.sleep(poll_interval)
