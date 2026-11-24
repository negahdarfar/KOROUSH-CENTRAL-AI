# Worker heartbeat and operational observability

The optional single-process worker writes a liveness heartbeat to the same SQLite database as the durable queue. A background task refreshes it every 15 seconds, including during provider requests.

The /readyz response includes a secret-free components.job_worker object with these states: disabled, not_started, starting, running, degraded, stale, stopped, or unknown. A heartbeat older than 60 seconds is stale.

This is only a liveness signal. It does not prove provider reachability, job success, or persistent-volume durability. The API readiness decision remains based on database health; a disabled or stale optional worker does not make the API itself unready.

The heartbeat table stores one worker identity, a coarse state, and a timestamp. It contains no secrets, tenant identifiers, prompts, or job IDs. This is not leader election and is not safe evidence of multi-replica coordination.