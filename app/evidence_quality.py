"""Deterministic provenance and freshness assessment for caller-supplied evidence.

This module never fetches URLs or treats publisher metadata as proof of truth.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


MAX_SOURCE_URL_CHARS = 2048
MAX_PUBLISHER_CHARS = 160


class EvidenceMetadataError(ValueError):
    """Evidence provenance metadata is malformed."""


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or len(value) > 40:
        raise EvidenceMetadataError("observed_at must be an ISO-8601 timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EvidenceMetadataError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceMetadataError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def assess_evidence_item(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return a secret-free provenance record; never infer source credibility."""
    if not isinstance(item, dict):
        raise EvidenceMetadataError("evidence item must be an object")
    source_id = item.get("source_id")
    source_text = item.get("text")
    if not isinstance(source_id, str) or not source_id.strip():
        raise EvidenceMetadataError("source_id is required")
    if not isinstance(source_text, str) or not source_text.strip():
        raise EvidenceMetadataError("evidence text is required")

    publisher = item.get("publisher")
    if publisher is not None and (
        not isinstance(publisher, str) or not publisher.strip()
        or len(publisher.strip()) > MAX_PUBLISHER_CHARS
    ):
        raise EvidenceMetadataError("publisher must be non-empty text up to 160 characters")

    source_url = item.get("source_url")
    if source_url is not None:
        if not isinstance(source_url, str) or len(source_url) > MAX_SOURCE_URL_CHARS:
            raise EvidenceMetadataError("source_url must be HTTPS and at most 2048 characters")
        parsed_url = urlsplit(source_url)
        if (
            parsed_url.scheme.lower() != "https"
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise EvidenceMetadataError("source_url must be an HTTPS URL without embedded credentials")

    observed_at = item.get("observed_at")
    age_bucket = "unknown"
    observed_iso = None
    if observed_at is not None:
        observed = _parse_timestamp(observed_at)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None or reference.utcoffset() is None:
            raise EvidenceMetadataError("assessment clock must be timezone-aware")
        age_hours = max(0.0, (reference.astimezone(timezone.utc) - observed).total_seconds() / 3600)
        age_bucket = "fresh" if age_hours <= 24 else "recent" if age_hours <= 168 else "stale"
        observed_iso = observed.isoformat()

    metadata_present = sum(value is not None for value in (publisher, source_url, observed_at))
    return {
        "source_id": source_id.strip(),
        "sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "publisher": publisher.strip() if isinstance(publisher, str) else None,
        "source_url": source_url,
        "observed_at": observed_iso,
        "freshness": age_bucket,
        "provenance_completeness": metadata_present,
        "credibility": "unverified",
    }


def assess_evidence_pack(items: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Assess a bounded list and reject duplicate source identifiers."""
    records = [assess_evidence_item(item, now=now) for item in items]
    ids = [record["source_id"].casefold() for record in records]
    if len(ids) != len(set(ids)):
        raise EvidenceMetadataError("evidence source_id values must be unique")
    return records
