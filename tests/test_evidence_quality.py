from datetime import datetime, timezone

import pytest

from app.evidence_quality import EvidenceMetadataError, assess_evidence_item, assess_evidence_pack


def test_evidence_assessment_hashes_content_and_classifies_freshness():
    now = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
    record = assess_evidence_item({
        "source_id": "market-report",
        "text": "A supplied report excerpt.",
        "publisher": "Example Research",
        "source_url": "https://example.org/reports/1",
        "observed_at": "2026-11-24T08:00:00Z",
    }, now=now)
    assert len(record["sha256"]) == 64
    assert record["freshness"] == "fresh"
    assert record["provenance_completeness"] == 3
    assert record["credibility"] == "unverified"


def test_evidence_assessment_marks_old_or_missing_timestamps():
    now = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
    stale = assess_evidence_item({
        "source_id": "old",
        "text": "Old excerpt",
        "observed_at": "2026-11-01T00:00:00+00:00",
    }, now=now)
    unknown = assess_evidence_item({"source_id": "unknown", "text": "Excerpt"}, now=now)
    assert stale["freshness"] == "stale"
    assert unknown["freshness"] == "unknown"


@pytest.mark.parametrize("source_url", [
    "http://example.org/report",
    "file:///etc/passwd",
    "https://user:password@example.org/report",
    "https://",
])
def test_evidence_assessment_rejects_unsafe_or_invalid_source_urls(source_url):
    with pytest.raises(EvidenceMetadataError):
        assess_evidence_item({
            "source_id": "source",
            "text": "Evidence",
            "source_url": source_url,
        })


@pytest.mark.parametrize("observed_at", [
    "2026-11-24T10:00:00",
    "not-a-date",
    "",
])
def test_evidence_assessment_requires_timezone_aware_iso_timestamp(observed_at):
    with pytest.raises(EvidenceMetadataError):
        assess_evidence_item({
            "source_id": "source",
            "text": "Evidence",
            "observed_at": observed_at,
        })


def test_evidence_pack_rejects_duplicate_source_ids_case_insensitively():
    with pytest.raises(EvidenceMetadataError):
        assess_evidence_pack([
            {"source_id": "Report-A", "text": "First"},
            {"source_id": "report-a", "text": "Second"},
        ])
