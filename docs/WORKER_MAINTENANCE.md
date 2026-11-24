# Worker maintenance and payload lifecycle

After a job's completion is successfully committed under its current lease, the worker deletes the encrypted input payload. A worker that loses its lease does not delete the input, so a valid replacement worker can still process it. Cleanup failures are logged without changing the already committed job outcome.

The worker periodically prunes expired encrypted payload rows in bounded batches (up to 200 per pass, at most once every five minutes). This also cleans expired result payloads and inputs left behind by terminal failures. The existing payload TTL remains the upper bound for retention.

Heartbeat state is maintained independently from the periodic heartbeat writer. A loop-level failure changes the state to degraded and it remains degraded until a later successful worker iteration; heartbeat refreshes no longer overwrite the degraded state with running. Cleanup failures are isolated and do not falsely mark job execution as unhealthy.

This is best-effort bounded cleanup, not immediate secure erasure from SQLite storage pages or backups. Persistent storage and backup retention must be governed separately.
