"""Minimal async SDK for tenant repositories integrating with KOROUSH CENTRAL AI."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx


_REPOSITORY = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?/"
    r"[a-z0-9](?:[a-z0-9._-]{0,98}[a-z0-9])?$"
)


class CentralAIError(RuntimeError):
    """Sanitized central API error with HTTP status."""


class CentralAIClient:
    """Use one central tenant key; do not store it in source control."""

    def __init__(
        self,
        base_url: str,
        tenant_key: str,
        repository: str,
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        url = base_url.strip().rstrip("/")
        parsed = urlsplit(url)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if parsed.scheme != "https" and not local_http:
            raise ValueError("Central API must use HTTPS (HTTP is allowed only for localhost)")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Central API base URL is invalid")
        if not isinstance(tenant_key, str) or not tenant_key.startswith("kor_") or len(tenant_key) > 256:
            raise ValueError("A valid tenant key is required")
        repo = repository.strip().lower()
        if not _REPOSITORY.fullmatch(repo) or repo.endswith(".git"):
            raise ValueError("repository must use valid owner/repository format")
        self.base_url = url
        self.repository = repo
        self._headers = {"X-Tenant-Key": tenant_key}
        bounded_timeout = max(1.0, min(float(timeout), 120.0))
        self._client = client or httpx.AsyncClient(timeout=bounded_timeout)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "CentralAIClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            response = await self._client.request(
                method, self.base_url + path, headers=self._headers, **kwargs
            )
            if response.status_code >= 400:
                detail = "Central API request failed"
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("detail"), str):
                        detail = body["detail"][:300]
                except ValueError:
                    pass
                raise CentralAIError(f"{detail} (HTTP {response.status_code})")
            data = response.json()
            if not isinstance(data, dict):
                raise CentralAIError("Central API returned an invalid response shape")
            return data
        except httpx.HTTPError as exc:
            raise CentralAIError(f"Central API transport error: {type(exc).__name__}") from exc

    async def manifest(self) -> dict:
        return await self._request("GET", "/api/platform/manifest")

    async def agents(self) -> dict:
        return await self._request("GET", "/api/agents", params={"repository": self.repository})

    async def apis(self) -> dict:
        return await self._request("GET", "/api/apis", params={"repository": self.repository})

    async def agent(self, agent_id: str) -> dict:
        if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 128:
            raise ValueError("agent_id must be non-empty text up to 128 characters")
        return await self._request(
            "GET", "/api/agents/" + quote(agent_id, safe=""),
            params={"repository": self.repository},
        )

    async def submit_job(
        self,
        *,
        job_type: str,
        payload: dict,
        idempotency_key: str,
        max_attempts: int = 5,
    ) -> dict:
        if not isinstance(job_type, str) or not 2 <= len(job_type) <= 80:
            raise ValueError("job_type must contain 2 to 80 characters")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise ValueError("idempotency_key must contain 1 to 128 characters")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be an integer from 1 to 20")
        return await self._request(
            "POST", "/api/jobs",
            json={
                "repository": self.repository,
                "job_type": job_type,
                "payload": payload,
                "idempotency_key": idempotency_key,
                "max_attempts": max_attempts,
            },
        )

    async def submit_agent(
        self,
        *,
        agent_id: str,
        payload: dict,
        idempotency_key: str,
        max_attempts: int = 5,
    ) -> dict:
        if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 128:
            raise ValueError("agent_id must be non-empty text up to 128 characters")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        return await self.submit_job(
            job_type="agent.execute",
            payload={**payload, "agent_id": agent_id, "schema_version": 1},
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )


    async def extensions(self, *, kind: str | None = None) -> dict:
        """Discover versioned extension metadata; never downloads or executes code."""
        params = {"repository": self.repository}
        if kind is not None:
            if not isinstance(kind, str) or kind not in {"agent", "model", "tool", "api", "data_source", "connector"}:
                raise ValueError("unsupported extension kind")
            params["kind"] = kind
        return await self._request("GET", "/api/extensions", params=params)

    async def sync_extensions(self, *, kind: str | None = None) -> dict:
        """Fetch a read-only registry snapshot for caller-controlled compatibility checks."""
        return await self.extensions(kind=kind)

    async def publish_event(
        self, *, event_type: str, consumer: str, payload: dict,
        idempotency_key: str, producer: str = "repository-adapter",
        schema_version: int = 1, max_attempts: int = 5,
        correlation_id: str | None = None, causation_id: str | None = None,
    ) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("event payload must be an object")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise ValueError("idempotency_key must contain 1 to 128 characters")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int) or not 1 <= schema_version <= 1000:
            raise ValueError("schema_version must be an integer from 1 to 1000")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be an integer from 1 to 20")
        return await self._request("POST", "/api/events", json={
            "repository": self.repository, "event_type": event_type,
            "schema_version": schema_version, "producer": producer, "consumer": consumer,
            "idempotency_key": idempotency_key, "payload": payload,
            "max_attempts": max_attempts, "correlation_id": correlation_id,
            "causation_id": causation_id,
        })

    async def claim_event(self, *, consumer: str, worker_id: str, lease_seconds: int = 60) -> dict:
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be from 10 to 3600")
        return await self._request("POST", "/api/events/claim", json={
            "repository": self.repository, "consumer": consumer,
            "worker_id": worker_id, "lease_seconds": lease_seconds,
        })

    async def settle_event(self, *, event_id: str, worker_id: str, success: bool, retryable: bool = True) -> dict:
        if not isinstance(success, bool) or not isinstance(retryable, bool):
            raise ValueError("success and retryable must be booleans")
        return await self._request("POST", "/api/events/" + quote(event_id, safe="") + "/settle", json={
            "repository": self.repository, "worker_id": worker_id,
            "success": success, "retryable": retryable,
        })

    async def job_status(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not job_id or len(job_id) > 128:
            raise ValueError("job_id must be non-empty text up to 128 characters")
        return await self._request(
            "GET", "/api/jobs/" + quote(job_id, safe=""),
            params={"repository": self.repository},
        )
