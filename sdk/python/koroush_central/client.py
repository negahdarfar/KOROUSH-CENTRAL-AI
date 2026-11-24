"""Minimal async SDK for tenant repositories integrating with KOROUSH CENTRAL AI."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


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
        if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("Central API must use HTTPS (HTTP is allowed only for localhost)")
        if not tenant_key or len(tenant_key) > 256:
            raise ValueError("A valid tenant key is required")
        repo = repository.strip().lower()
        if repo.count("/") != 1 or any(ch.isspace() for ch in repo):
            raise ValueError("repository must use owner/repository format")
        self.base_url = url
        self.repository = repo
        self._headers = {"X-Tenant-Key": tenant_key}
        self._client = client or httpx.AsyncClient(timeout=timeout)
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
                # Never include request headers or tenant credentials in exception text.
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
        return await self._request(
            "GET", "/api/agents", params={"repository": self.repository}
        )

    async def apis(self) -> dict:
        return await self._request(
            "GET", "/api/apis", params={"repository": self.repository}
        )

    async def agent(self, agent_id: str) -> dict:
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

    async def job_status(self, job_id: str) -> dict:
        return await self._request(
            "GET", "/api/jobs/" + quote(job_id, safe=""),
            params={"repository": self.repository},
        )
