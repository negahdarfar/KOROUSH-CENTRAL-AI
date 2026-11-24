import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from koroush_central import CentralAIClient, CentralAIError


def test_sdk_rejects_insecure_remote_url_and_bad_repository():
    try:
        CentralAIClient("http://central.example", "kor_secret", "org/repo")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("insecure remote URL must be rejected")

    try:
        CentralAIClient("https://central.example", "kor_secret", "org/repo/path")
    except ValueError as exc:
        assert "owner/repository" in str(exc)
    else:
        raise AssertionError("invalid repository must be rejected")


def test_sdk_uses_tenant_scope_and_never_echoes_key_in_errors():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(403, json={"detail": "Repository not assigned"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = CentralAIClient(
                "https://central.example", "kor_sensitive_value", "org/repo", client=http
            )
            try:
                await client.agents()
            except CentralAIError as exc:
                assert "kor_sensitive_value" not in str(exc)
                assert "Repository not assigned" in str(exc)
            else:
                raise AssertionError("HTTP error must be surfaced")
            assert seen[0].headers["X-Tenant-Key"] == "kor_sensitive_value"
            await client.close()

    asyncio.run(run())


def test_sdk_job_submission_binds_repository_and_idempotency_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(202, json={"job_id": "job-123", "status": "queued"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = CentralAIClient("https://central.example", "kor_key", "org/repo", client=http)
            result = await client.submit_job(
                job_type="chat.completion", payload={"input": "hello"},
                idempotency_key="stable-1",
            )
            assert result["status"] == "queued"
            body = seen[0].read().decode()
            assert '"repository":"org/repo"' in body
            assert '"idempotency_key":"stable-1"' in body
            await client.close()

    asyncio.run(run())



def test_sdk_rejects_lookalike_localhost_hosts_and_invalid_keys():
    for url in ("http://localhost.attacker.test", "http://127.0.0.1.attacker.test"):
        try:
            CentralAIClient(url, "kor_secret", "org/repo")
        except ValueError as exc:
            assert "HTTPS" in str(exc)
        else:
            raise AssertionError("lookalike localhost host must be rejected")

    try:
        CentralAIClient("https://central.example", "not-a-tenant-key", "org/repo")
    except ValueError as exc:
        assert "tenant key" in str(exc)
    else:
        raise AssertionError("invalid tenant key prefix must be rejected")


def test_sdk_rejects_malformed_repository_and_job_arguments():
    try:
        CentralAIClient("https://central.example", "kor_secret", "org/repo.git")
    except ValueError as exc:
        assert "owner/repository" in str(exc)
    else:
        raise AssertionError("git suffix must be rejected")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})
        )) as http:
            client = CentralAIClient("https://central.example", "kor_key", "org/repo", client=http)
            for kwargs in (
                {"job_type": "chat.completion", "payload": [], "idempotency_key": "id"},
                {"job_type": "chat.completion", "payload": {}, "idempotency_key": ""},
                {"job_type": "chat.completion", "payload": {}, "idempotency_key": "id", "max_attempts": True},
            ):
                try:
                    await client.submit_job(**kwargs)
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid job arguments must be rejected")
            await client.close()

    asyncio.run(run())
