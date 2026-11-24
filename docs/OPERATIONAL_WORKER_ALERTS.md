# Operational worker alerts

The operational alert monitor reuses the existing Telegram and STARTTLS-validated SMTP delivery configuration. It watches the SQLite-backed worker heartbeat and emits notifications for `stale`, `stopped`, and `degraded` states.

Delivery is deduplicated per channel and 30-minute state bucket. A failed delivery can be retried on the next poll; an in-flight claim older than ten minutes can be reclaimed. The alert text contains only component name, coarse state, and heartbeat age.

Configuration: `OPERATIONAL_ALERT_POLL_SECONDS` (30–3600 seconds, default 60), plus the existing `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` or safe SMTP variables.

No credentials are created or changed by this code. With no configured channel, monitoring is non-delivering and returns without storing alert attempts. This monitor does not guarantee delivery during total process/database failure; external uptime monitoring is still required.