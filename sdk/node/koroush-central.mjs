/**
 * Dependency-free Node.js client for KOROUSH CENTRAL AI.
 * Requires Node.js 18+ (native fetch).
 */
export class CentralAIError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "CentralAIError";
    this.status = status;
  }
}

export class CentralAIClient {
  #headers;

  constructor({ baseUrl, tenantKey, repository, timeoutMs = 30000, fetchImpl = globalThis.fetch }) {
    const url = String(baseUrl || "").trim().replace(/\/+$/, "");
    let parsed;
    try { parsed = new URL(url); } catch {
      throw new TypeError("Central API base URL is invalid");
    }
    const localHttp = parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && !localHttp) {
      throw new TypeError("Central API must use HTTPS (HTTP is allowed only for localhost)");
    }
    if (!parsed.hostname || parsed.username || parsed.password || parsed.search || parsed.hash) {
      throw new TypeError("Central API base URL is invalid");
    }
    if (typeof tenantKey !== "string" || !tenantKey.startsWith("kor_") || tenantKey.length > 256) {
      throw new TypeError("A valid tenant API key is required");
    }
    const repo = String(repository || "").trim().toLowerCase();
    if (!/^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?\/[a-z0-9](?:[a-z0-9._-]{0,98}[a-z0-9])?$/.test(repo) || repo.endsWith(".git")) {
      throw new TypeError("repository must use valid owner/repository format");
    }
    if (typeof fetchImpl !== "function") throw new TypeError("A fetch implementation is required");
    this.baseUrl = url;
    this.repository = repo;
    this.timeoutMs = Math.max(1000, Math.min(Number(timeoutMs) || 30000, 120000));
    this.fetchImpl = fetchImpl;
    this.#headers = { "X-Tenant-Key": tenantKey };
  }

  async request(method, path, options = {}) {
    const url = new URL(this.baseUrl + path);
    if (options.query) {
      for (const [key, value] of Object.entries(options.query)) {
        if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
      }
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const hasBody = options.body !== undefined;
      const response = await this.fetchImpl(url, {
        method,
        headers: { ...this.#headers, ...(hasBody ? { "Content-Type": "application/json" } : {}) },
        ...(hasBody ? { body: JSON.stringify(options.body) } : {}),
        signal: controller.signal,
      });
      if (!response.ok) {
        let detail = "Central API request failed";
        try {
          const data = await response.json();
          if (typeof data?.detail === "string") detail = data.detail.slice(0, 300);
        } catch {}
        throw new CentralAIError(detail + " (HTTP " + response.status + ")", response.status);
      }
      const data = await response.json();
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new CentralAIError("Central API returned an invalid response shape");
      }
      return data;
    } catch (error) {
      if (error instanceof CentralAIError) throw error;
      if (error?.name === "AbortError") throw new CentralAIError("Central API request timed out");
      throw new CentralAIError("Central API transport error: " + (error?.name || "Error"));
    } finally {
      clearTimeout(timer);
    }
  }

  manifest() { return this.request("GET", "/api/platform/manifest"); }
  agents() { return this.request("GET", "/api/agents", { query: { repository: this.repository } }); }
  apis() { return this.request("GET", "/api/apis", { query: { repository: this.repository } }); }

  agent(agentId) {
    if (typeof agentId !== "string" || !agentId || agentId.length > 128) {
      throw new TypeError("agentId must be non-empty text up to 128 characters");
    }
    return this.request("GET", "/api/agents/" + encodeURIComponent(agentId), {
      query: { repository: this.repository },
    });
  }

  submitJob({ jobType, payload, idempotencyKey, maxAttempts = 5 }) {
    if (typeof jobType !== "string" || jobType.length < 2 || jobType.length > 80
        || !payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("jobType and object payload are required");
    }
    if (typeof idempotencyKey !== "string" || !idempotencyKey || idempotencyKey.length > 128) {
      throw new TypeError("A stable idempotencyKey of at most 128 characters is required");
    }
    if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 20) {
      throw new TypeError("maxAttempts must be an integer from 1 to 20");
    }
    return this.request("POST", "/api/jobs", {
      body: {
        repository: this.repository,
        job_type: jobType,
        payload,
        idempotency_key: idempotencyKey,
        max_attempts: maxAttempts,
      },
    });
  }

  submitDomainResearch({ domain, evidence, idempotencyKey, targetLanguage, maxAttempts = 3 }) {
    if (!["forex", "youtube", "ptc", "nft"].includes(domain)) {
      throw new TypeError("domain must be forex, youtube, ptc or nft");
    }
    if (!Array.isArray(evidence) || evidence.length < 1 || evidence.length > 8
        || evidence.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
      throw new TypeError("evidence must contain 1 to 8 source objects");
    }
    if (typeof idempotencyKey !== "string" || !idempotencyKey || idempotencyKey.length > 128) {
      throw new TypeError("A stable idempotencyKey of at most 128 characters is required");
    }
    if (targetLanguage !== undefined && (typeof targetLanguage !== "string"
        || !targetLanguage.trim() || targetLanguage.length > 80)) {
      throw new TypeError("targetLanguage must be non-empty text up to 80 characters");
    }
    if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 10) {
      throw new TypeError("maxAttempts must be an integer from 1 to 10");
    }
    return this.request("POST", "/api/integrations/" + domain + "/research", {
      body: {
        repository: this.repository,
        evidence,
        idempotency_key: idempotencyKey,
        target_language: targetLanguage,
        max_attempts: maxAttempts,
      },
    });
  }

  submitIntegrationResearch({ integrationId, evidence, idempotencyKey, targetLanguage, maxAttempts = 3 }) {
    if (typeof integrationId !== "string"
        || !/^[a-z][a-z0-9]*(?:[.-][a-z0-9]+){1,7}$/.test(integrationId)
        || integrationId.length > 100) {
      throw new TypeError("integrationId must be a stable registered extension identifier");
    }
    if (!Array.isArray(evidence) || evidence.length < 1 || evidence.length > 8
        || evidence.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
      throw new TypeError("evidence must contain 1 to 8 source objects");
    }
    if (typeof idempotencyKey !== "string" || !idempotencyKey || idempotencyKey.length > 128) {
      throw new TypeError("A stable idempotencyKey of at most 128 characters is required");
    }
    if (targetLanguage !== undefined && (typeof targetLanguage !== "string"
        || !targetLanguage.trim() || targetLanguage.length > 80)) {
      throw new TypeError("targetLanguage must be non-empty text up to 80 characters");
    }
    if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 10) {
      throw new TypeError("maxAttempts must be an integer from 1 to 10");
    }
    return this.request("POST", "/api/integrations/" + integrationId + "/research", {
      body: {
        repository: this.repository,
        evidence,
        idempotency_key: idempotencyKey,
        target_language: targetLanguage,
        max_attempts: maxAttempts,
      },
    });
  }

  submitAgent({ agentId, payload, idempotencyKey, maxAttempts = 5 }) {
    if (typeof agentId !== "string" || !agentId || agentId.length > 128) {
      throw new TypeError("agentId must be non-empty text up to 128 characters");
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("agent payload must be an object");
    }
    return this.submitJob({
      jobType: "agent.execute",
      payload: { ...payload, agent_id: agentId, schema_version: 1 },
      idempotencyKey,
      maxAttempts,
    });
  }


  extensions({ kind } = {}) {
    const allowed = ["agent", "model", "tool", "api", "data_source", "connector"];
    if (kind !== undefined && !allowed.includes(kind)) throw new TypeError("unsupported extension kind");
    return this.request("GET", "/api/extensions", { query: { repository: this.repository, kind } });
  }

  // Read-only metadata synchronization. This never installs or executes remote code.
  syncExtensions(options = {}) { return this.extensions(options); }

  publishEvent({ eventType, consumer, payload, idempotencyKey, producer = "repository-adapter",
    schemaVersion = 1, maxAttempts = 5, correlationId, causationId }) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)
        || typeof idempotencyKey !== "string" || !idempotencyKey || idempotencyKey.length > 128
        || !Number.isInteger(schemaVersion) || schemaVersion < 1 || schemaVersion > 1000
        || !Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 20) {
      throw new TypeError("valid event payload, idempotency key, schemaVersion and maxAttempts are required");
    }
    return this.request("POST", "/api/events", { body: {
      repository: this.repository, event_type: eventType, schema_version: schemaVersion,
      producer, consumer, idempotency_key: idempotencyKey, payload,
      max_attempts: maxAttempts, correlation_id: correlationId, causation_id: causationId,
    } });
  }

  claimEvent({ consumer, workerId, leaseSeconds = 60 }) {
    if (!Number.isInteger(leaseSeconds) || leaseSeconds < 10 || leaseSeconds > 3600) {
      throw new TypeError("leaseSeconds must be from 10 to 3600");
    }
    return this.request("POST", "/api/events/claim", { body: {
      repository: this.repository, consumer, worker_id: workerId, lease_seconds: leaseSeconds,
    } });
  }

  settleEvent({ eventId, workerId, success, retryable = true }) {
    if (typeof success !== "boolean" || typeof retryable !== "boolean") {
      throw new TypeError("success and retryable must be booleans");
    }
    return this.request("POST", "/api/events/" + encodeURIComponent(eventId) + "/settle", { body: {
      repository: this.repository, worker_id: workerId, success, retryable,
    } });
  }

  jobStatus(jobId) {
    if (typeof jobId !== "string" || !jobId || jobId.length > 128) {
      throw new TypeError("jobId must be non-empty text up to 128 characters");
    }
    return this.request("GET", "/api/jobs/" + encodeURIComponent(jobId), {
      query: { repository: this.repository },
    });
  }
}
