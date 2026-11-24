import test from "node:test";
import assert from "node:assert/strict";
import { CentralAIClient, CentralAIError } from "../sdk/node/koroush-central.mjs";

test("SDK rejects insecure remote URLs and malformed repositories", () => {
  assert.throws(() => new CentralAIClient({
    baseUrl: "http://central.example", tenantKey: "kor_secret", repository: "org/repo",
  }), /HTTPS/);
  assert.throws(() => new CentralAIClient({
    baseUrl: "https://central.example", tenantKey: "kor_secret", repository: "org/repo/path",
  }), /owner\/repository/);
});

test("SDK sends tenant identity and scopes jobs to its repository", async () => {
  let captured;
  const client = new CentralAIClient({
    baseUrl: "https://central.example/",
    tenantKey: "kor_sensitive_value",
    repository: "Org/Repo",
    fetchImpl: async (url, options) => {
      captured = { url: String(url), options };
      return new Response(JSON.stringify({ job_id: "job-1", status: "queued" }), {
        status: 202, headers: { "Content-Type": "application/json" },
      });
    },
  });
  const result = await client.submitJob({
    jobType: "chat.completion",
    idempotencyKey: "stable-1",
    payload: { task: "general", messages: [{ role: "user", content: "hello" }] },
  });
  assert.equal(result.job_id, "job-1");
  assert.equal(captured.options.headers["X-Tenant-Key"], "kor_sensitive_value");
  assert.equal(captured.url, "https://central.example/api/jobs");
  const body = JSON.parse(captured.options.body);
  assert.equal(body.repository, "org/repo");
  assert.equal(body.idempotency_key, "stable-1");
});

test("SDK never echoes tenant credentials in HTTP errors", async () => {
  const secret = "kor_do_not_leak";
  const client = new CentralAIClient({
    baseUrl: "https://central.example",
    tenantKey: secret,
    repository: "org/repo",
    fetchImpl: async () => new Response(JSON.stringify({ detail: "Repository denied" }), {
      status: 403, headers: { "Content-Type": "application/json" },
    }),
  });
  await assert.rejects(client.agents(), (error) => {
    assert.ok(error instanceof CentralAIError);
    assert.match(error.message, /Repository denied/);
    assert.ok(!error.message.includes(secret));
    return true;
  });
});

test("SDK validates job bounds and opaque identifiers", () => {
  const client = new CentralAIClient({
    baseUrl: "https://central.example",
    tenantKey: "kor_test",
    repository: "org/repo",
    fetchImpl: async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
  });
  assert.throws(() => client.submitJob({
    jobType: "chat.completion", payload: {}, idempotencyKey: "id", maxAttempts: 0,
  }), /maxAttempts/);
  assert.throws(() => client.submitJob({
    jobType: "chat.completion", payload: {}, idempotencyKey: "",
  }), /idempotencyKey/);
  assert.throws(() => client.agent(""), /agentId/);
  assert.throws(() => client.jobStatus(""), /jobId/);
});

test("SDK rejects lookalike localhost and credential-bearing API URLs", () => {
  for (const baseUrl of [
    "http://localhost.attacker.test",
    "http://127.0.0.1.attacker.test",
    "https://user:pass@central.example",
    "https://central.example/?token=secret",
  ]) {
    assert.throws(() => new CentralAIClient({
      baseUrl, tenantKey: "kor_test", repository: "org/repo",
    }));
  }
});

test("submitAgent pins the selected allowlisted agent and durable job type", async () => {
  let requestBody;
  const client = new CentralAIClient({
    baseUrl: "https://central.example",
    tenantKey: "kor_test",
    repository: "org/repo",
    fetchImpl: async (_url, options) => {
      requestBody = JSON.parse(options.body);
      return new Response(JSON.stringify({ job_id: "agent-1", status: "queued" }), { status: 202 });
    },
  });
  const result = await client.submitAgent({
    agentId: "koroush.text-summarizer",
    payload: { text: "summarize", agent_id: "tenant.override" },
    idempotencyKey: "summary-1",
  });
  assert.equal(result.status, "queued");
  assert.equal(requestBody.job_type, "agent.execute");
  assert.equal(requestBody.payload.agent_id, "koroush.text-summarizer");
  assert.equal(client.headers, undefined);
});
