"""Bounded, evidence-aware discovery for public AI resources.

Search is restricted to the official GitHub API endpoint. Returned resources are
metadata-only candidates: discovery never installs, imports, executes, or registers code.
Pricing evidence remains unverified until an administrator validates an official source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Any, Iterable, Protocol
from urllib.parse import urlsplit
import ipaddress
import re

import httpx

KINDS = {"repository", "agent", "model", "api", "tool", "dataset", "connector"}
MAX_RESULTS = 50
MAX_TEXT = 500
MAX_CANDIDATES = 50
MAX_RESPONSE_BYTES = 1_000_000
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"


@dataclass(frozen=True)
class DiscoveryQuery:
    kind: str
    terms: tuple[str, ...]
    require_recent_days: int = 730
    limit: int = 20

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError("unsupported discovery kind")
        if not isinstance(self.terms, tuple) or not 1 <= len(self.terms) <= 8:
            raise ValueError("provide 1 to 8 search terms")
        for term in self.terms:
            if (
                not isinstance(term, str)
                or not 1 <= len(term.strip()) <= 80
                or len(term) > 80
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in term)
                or any(ch in term for ch in ('"', "\\", ":", "#"))
                or not all(ch.isalnum() or ch.isspace() or ch in "._+-" for ch in term)
            ):
                raise ValueError("search terms contain unsupported characters")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= MAX_RESULTS:
            raise ValueError("limit must be between 1 and 50")
        if isinstance(self.require_recent_days, bool) or not isinstance(self.require_recent_days, int) or not 1 <= self.require_recent_days <= 3650:
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


def github_query(query: DiscoveryQuery, now: datetime | None = None) -> str:
    """Build a safe, bounded GitHub repository search query."""
    terms = " ".join(f'"{term.strip()}"' for term in query.terms)
    current = now or datetime.now(timezone.utc)
    since = (current - timedelta(days=query.require_recent_days)).date().isoformat()
    return f"{terms} archived:false pushed:>={since}"


def _valid_https_url(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.port not in (None, 443) or parsed.query or parsed.fragment:
            return False
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
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
    except (ValueError, UnicodeError):
        return False


def _fresh(pushed_at: str | None, days: int, now: datetime) -> bool:
    if not isinstance(pushed_at, str) or not pushed_at:
        return False
    try:
        stamp = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = now - stamp
        return timedelta(0) <= age <= timedelta(days=days)
    except (TypeError, ValueError):
        return False


def _bounded_text(value: Any, maximum: int = MAX_TEXT) -> bool:
    return isinstance(value, str) and len(value) <= maximum


def assess_candidate(
    candidate: ResourceCandidate,
    recent_days: int = 730,
    now: datetime | None = None,
) -> DiscoveryAssessment:
    """Score metadata conservatively; never certify trust or free pricing automatically."""
    now = now or datetime.now(timezone.utc)
    missing: list[str] = ["official_pricing_verification", "license_compatibility_review"]
    reasons: list[str] = []
    score = 0

    if not isinstance(candidate, ResourceCandidate):
        return DiscoveryAssessment("", 0, "rejected", "unverified", ("invalid candidate object",), tuple(missing))
    if candidate.kind not in KINDS:
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified", ("unsupported resource kind",), tuple(missing))
    if not isinstance(candidate.source_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", candidate.source_id):
        return DiscoveryAssessment(str(candidate.source_id)[:200], 0, "rejected", "unverified", ("invalid source identifier",), tuple(missing))
    if not _valid_https_url(candidate.url):
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified", ("URL must be public HTTPS without credentials, query, or fragment",), tuple(missing))
    if candidate.archived is not False:
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified", ("repository is archived or archive state is invalid",), tuple(missing))
    if not _bounded_text(candidate.name) or not _bounded_text(candidate.description):
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified", ("candidate text is invalid or exceeds bounds",), tuple(missing))
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (candidate.stars, candidate.forks)):
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified", ("popularity metadata must be non-negative integers",), tuple(missing))
    if candidate.stars > 2_000_000_000 or candidate.forks > 2_000_000_000:
        return DiscoveryAssessment(candidate.source_id, 0, "rejected", "unverified", ("popularity metadata exceeds bounds",), tuple(missing))

    score += 10 if candidate.name else 0
    score += 10 if candidate.description else 0
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
    if isinstance(candidate.license_spdx, str) and re.fullmatch(r"[A-Za-z0-9.+-]{1,80}", candidate.license_spdx):
        score += 10
        reasons.append("license identifier supplied; compatibility still requires review")
    else:
        reasons.append("license identifier missing or invalid")

    # User-supplied evidence URLs are leads, not proof. This engine has no official-domain
    # verification or pricing-page parser, so it must never promote a resource to free.
    evidence_count = 0
    if isinstance(candidate.evidence, (tuple, list)):
        evidence_count = min(len(candidate.evidence), 20)
    if evidence_count:
        reasons.append("pricing evidence submitted; publisher authenticity and terms are unverified")
    else:
        reasons.append("no pricing evidence submitted")
    missing.append("official_publisher_domain_verification")
    status = "candidate_for_review" if score >= 45 else "low_confidence"
    return DiscoveryAssessment(
        candidate.source_id, min(score, 100), status, "unverified",
        tuple(reasons), tuple(sorted(set(missing))),
    )


class IntelligentDiscoveryEngine:
    """Bounded adapter orchestration. Does not persist or execute discovered resources."""

    def __init__(self, backend: SearchBackend):
        self.backend = backend

    def discover(self, query: DiscoveryQuery, now: datetime | None = None) -> list[DiscoveryAssessment]:
        candidates = islice(self.backend.search(query), min(query.limit, MAX_CANDIDATES))
        assessments = [assess_candidate(item, query.require_recent_days, now) for item in candidates]
        return sorted(
            assessments,
            key=lambda item: (item.status == "candidate_for_review", item.score),
            reverse=True,
        )


async def search_github_repositories(
    query: DiscoveryQuery,
    *,
    token: str = "",
    client: httpx.AsyncClient | None = None,
) -> list[ResourceCandidate]:
    """Fetch bounded public repository metadata from the fixed official GitHub API host."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "KOROUSH-CENTRAL-AI-Discovery/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"q": github_query(query), "sort": "updated", "order": "desc", "per_page": str(query.limit), "page": "1"}
    own_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    )
    try:
        response = await active_client.get(GITHUB_SEARCH_URL, params=params, headers=headers)
        if response.status_code in (301, 302, 303, 307, 308):
            raise RuntimeError("GitHub search redirects are disabled")
        response.raise_for_status()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise RuntimeError("GitHub search response exceeded the 1 MB limit")
        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("GitHub search returned an invalid response")
        results: list[ResourceCandidate] = []
        for item in items[:query.limit]:
            if not isinstance(item, dict):
                continue
            url = item.get("html_url")
            full_name = item.get("full_name")
            if not _valid_https_url(url) or not isinstance(full_name, str) or len(full_name) > 200:
                continue
            license_data = item.get("license")
            spdx = license_data.get("spdx_id") if isinstance(license_data, dict) else None
            results.append(ResourceCandidate(
                source_id=full_name,
                name=str(item.get("name") or "")[:MAX_TEXT],
                url=url,
                kind=query.kind,
                description=str(item.get("description") or "")[:MAX_TEXT],
                stars=item.get("stargazers_count", 0) if isinstance(item.get("stargazers_count", 0), int) else 0,
                forks=item.get("forks_count", 0) if isinstance(item.get("forks_count", 0), int) else 0,
                archived=item.get("archived") is True,
                pushed_at=item.get("pushed_at") if isinstance(item.get("pushed_at"), str) else None,
                license_spdx=spdx if isinstance(spdx, str) else None,
                evidence=(),
                capabilities=(),
            ))
        return results
    finally:
        if own_client:
            await active_client.aclose()
