import httpx
import pytest

from koroush_central.client import CentralAIClient


@pytest.mark.asyncio
async def test_extension_sync_is_read_only_and_repository_scoped():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"repository": "org/repo", "extensions": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = CentralAIClient("https://central.example", "kor_test", "Org/Repo", client=http)
        result = await client.sync_extensions(kind="connector")
    assert result["extensions"] == []
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/api/extensions"
    assert requests[0].url.params["repository"] == "org/repo"
    assert requests[0].url.params["kind"] == "connector"


@pytest.mark.asyncio
async def test_event_methods_send_repository_bound_contracts():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(202, json={"event_id": "event-1", "status": "queued"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CentralAIClient("https://central.example", "kor_test", "org/repo", client=http)
        await client.publish_event(event_type="repo.sync.requested", consumer="adapter",
                                   payload={"version": 1}, idempotency_key="sync-1")
        await client.claim_event(consumer="adapter", worker_id="worker-1")
        await client.settle_event(event_id="event-1", worker_id="worker-1", success=True)
    import json
    body = json.loads(requests[0].content)
    assert body["repository"] == "org/repo"
    assert body["event_type"] == "repo.sync.requested"
    assert body["payload"] == {"version": 1}
    assert requests[1].url.path == "/api/events/claim"
    assert requests[2].url.path == "/api/events/event-1/settle"


def test_sdk_rejects_invalid_extension_kind_and_lease_bounds():
    client = CentralAIClient("https://central.example", "kor_test", "org/repo")
    with pytest.raises(ValueError, match="extension kind"):
        import asyncio
        asyncio.run(client.extensions(kind="executable"))
    with pytest.raises(ValueError, match="lease_seconds"):
        import asyncio
        asyncio.run(client.claim_event(consumer="adapter", worker_id="worker", lease_seconds=2))
    import asyncio
    asyncio.run(client.close())
