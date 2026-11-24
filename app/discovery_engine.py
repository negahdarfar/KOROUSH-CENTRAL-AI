"""Evidence-aware discovery and ranking for public AI resources.

This module deliberately does not execute discovered code or infer that a resource
is free from repository topics, README claims, or a "free" label.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
import re
import ipaddress
from urllib.parse import urlsplit

KINDS = {"repository", "agent", "model", "api", "tool", "dataset", "connector"}
MAX_RESULTS = 50
MAX_TEXT = 500
FREE_EVIDENCE = {"official_pricing_zero", "official_free_tier", "license_allows_use"}


@dataclass(frozen=True)
class DiscoveryQuery:
    kind: str
    terms: tuple[str, ...]
    require_recent_days: int = 730
    limit: int = 20

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError("unsupported discovery kind")
        if not self.terms or len(self.terms) > 8:
            raise ValueError("provide 1 to 8 search terms")
        if any(not isinstance(t, str) or not t.strip() or len(t) > 80
               or any(ord(ch) < 32 or ord(ch) == 127 or ch in {'"', chr(92)} for ch in t)
               for t in self.terms):
            raise ValueError("search terms must be 1-80 characters without control chars, quotes, or backslashes")
        if not 1 <= self.limit <= MAX_RESULTS:
            raise ValueError("limit must be between 1 and 50")
        if not 1 <= self.require_recent_days <= 3650:
            raise ValueError("require_recent_days must be between 1 and 3650")


@dataclass(frozen=True)
class ResourceCandidate:
    source_id: str
    name: str
    url: str
    kind: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    archived: bool = False
    pushed_at: str | None = None
    license_spdx: str | None = None
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    capabilities: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiscoveryAssessment:
    source_id: str
    score: int
    status: str
    free_status: str
    reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]


class SearchBackend(Protocol):
    def search(self, query: DiscoveryQuery) -> Iterable[ResourceCandidate]: ...


def github_query(query: DiscoveryQuery) -> str:
    """Return a bounded public GitHub repository search query, not a network call."""
    terms = " ".join(f'"{term}"' for term in query.terms)
    return f'{terms} archived:false'


def _valid_https_url(url: str) -> bool:
    """Accept ordinary public DNS HTTPS URLs only; reject IPs, userinfo and fragments."""
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443) or parsed.query or parsed.fragment:
            return False
        host = parsed.hostname.lower()
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        labels = host.split(".")
        if len(labels) < 2 or any(
            not label or len(label) > 63
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in labels
        ):
            return False
        return bool(re.fullmatch(r"/?[A-Za-z0-9._~!$&'()*+,;=:@%/-]*", parsed.path))
    except ValueError:
        return False

def _fresh(pushed_at: str | None, days: int, now: datetime) -> bool:
    if not pushed_at:
        return False
    try:
        stamp = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (now - stamp).days <= days and stamp <= now
    except (TypeError, ValueError):
        return False


def assess_candidate(candidate: ResourceCandidate, recent_days: int = 730,
                     now: datetime | None = None) -> DiscoveryAssessment:
    """Score public metadata conservatively; free status requires cited evidence."""
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    missing: list[str] = []
    score = 0

    if candidate.kind not in KINDS:
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified",
                                   ("unsupported resource kind",), tuple(FREE_EVIDENCE))
    if not candidate.source_id or len(candidate.source_id) > 200:
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified",
                                   ("invalid source identifier",), tuple(FREE_EVIDENCE))
    if not _valid_https_url(candidate.url):
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified",
                                   ("URL must be HTTPS without credentials or nonstandard ports",), tuple(FREE_EVIDENCE))
    if candidate.archived:
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified",
                                   ("repository is archived",), tuple(FREE_EVIDENCE))

    if candidate.name and len(candidate.name) <= MAX_TEXT:
        score += 10
    if candidate.description and len(candidate.description) <= MAX_TEXT:
        score += 10
    if _fresh(candidate.pushed_at, recent_days, now):
        score += 20
        reasons.append("recent repository activity")
    else:
        reasons.append("activity date missing, invalid, or stale")
    if candidate.stars >= 100:
        score += 15
        reasons.append("at least 100 stars")
    elif candidate.stars >= 10:
        score += 8
        reasons.append("at least 10 stars")
    if candidate.forks >= 10:
        score += 5
        reasons.append("community forks present")
    if candidate.license_spdx:
        score += 10
        reasons.append("license identifier supplied; legal suitability still needs review")
    else:
        missing.append("license_spdx")

    verified = set()
    for item in candidate.evidence:
        if not isinstance(item, dict):
            continue
        evidence_type = item.get("type")
        url = item.get("url")
        if evidence_type in FREE_EVIDENCE and isinstance(url, str) and _valid_https_url(url):
            verified.add(evidence_type)
    missing.extend(sorted(FREE_EVIDENCE - verified))
    if "official_pricing_zero" in verified or "official_free_tier" in verified:
        free_status = "pricing_evidence_present"
        score += 15
        reasons.append("official pricing evidence supplied; terms and limits require validation")
    else:
        free_status = "unverified"
        reasons.append("free pricing not proven by an official source")

    status = "candidate_for_review" if score >= 45 else "low_confidence"
    return DiscoveryAssessment(candidate.source_id, min(score, 100), status,
                               free_status, tuple(reasons), tuple(sorted(set(missing))))


class IntelligentDiscoveryEngine:
    """Search adapter orchestration; persistence and execution are intentionally separate."""

    def __init__(self, backend: SearchBackend):
        self.backend = backend

    def discover(self, query: DiscoveryQuery,
                 now: datetime | None = None) -> list[DiscoveryAssessment]:
        candidates = list(self.backend.search(query))[:query.limit]
        assessments = [assess_candidate(c, query.require_recent_days, now) for c in candidates]
        return sorted(assessments, key=lambda item: (item.status == "candidate_for_review",
                                                     item.score), reverse=True)
