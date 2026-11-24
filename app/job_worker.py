"""Opt-in durable worker execution framework.

No handlers are registered by default. Inference must not be enabled until a
secure payload resolver and execution-time zero-price/quota policy are supplied.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .durable_jobs import claim_job, fail_job, finish_job
from .tenant_auth import authorize_job_execution
from .job_payload_store import get_payload, JobPayloadError

logger = logging.getLogger(__name__)
JobHandler = Callable[[dict], Awaitable[None]]
PolicyCheck = Callable[[dict], bool]


class WorkerConfigurationError(RuntimeError):
    pass


async def run_once(worker_id: str, handlers: dict[str, JobHandler],
                   *, policy_check: PolicyCheck = authorize_job_execution,
                   lease_seconds: int = 60, payload_resolver=get_payload) -> str:
    """Execute one registered job after tenant revalidation; never infer by default."""
    job = claim_job(worker_id, lease_seconds=lease_seconds)
    if job is None:
        return "idle"
    job_id = job["id"]
    try:
        if not job.get("tenant_key_id") or not policy_check(
            job.get("tenant_key_id"), job.get("repository"), job.get("team_id")
        ):
            fail_job(job_id, worker_id, "tenant_authorization_revoked", retryable=False)
            return "rejected"
        handler = handlers.get(job["job_type"])
        if handler is None:
            fail_job(job_id, worker_id, "handler_not_registered", retryable=False)
            return "unsupported"
        payload = payload_resolver(job["payload_ref"])
        safe_job = {key: value for key, value in job.items() if key != "payload_ref"}
        safe_job["payload"] = payload
        await handler(safe_job)
        if not finish_job(job_id, worker_id):
            logger.warning("Job completion fenced: lease is no longer owned")
            return "lease_lost"
        return "succeeded"
    except asyncio.CancelledError:
        # Leave the lease to expire so another worker can safely reclaim it.
        raise
    except JobPayloadError:
        logger.warning("Job payload could not be securely resolved; marking job terminal")
        fail_job(job_id, worker_id, "payload_unavailable", retryable=False)
        return "payload_unavailable"
    except Exception:
        logger.exception("Durable job handler failed")
        fail_job(job_id, worker_id, "handler_failed", retryable=True)
        return "failed"
