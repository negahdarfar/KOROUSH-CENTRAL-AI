"""Safe, metadata-only source connector contracts.

No network requests are made in this module. A future transport must enforce the
returned policy, disable redirects, and pin validated DNS results before connecting.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


MAX_CONNECT_TIMEOUT_SECONDS = 10
MAX_READ_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 1_000_000
MAX_REDIRECTS = 0


class SourcePolicyError(ValueError):
    """A source request violates the connector security contract."""


@dataclass(frozen=True)
class FetchPolicy:
    connect_timeout_seconds: int = 5
    read_timeout_seconds: int = 10
    max_response_bytes: int = 512_000
    allow_redirects: bool = False
    require_https: bool = True

    def validate(self) -> "FetchPolicy":
        if not 1 <= self.connect_timeout_seconds <= MAX_CONNECT_TIMEOUT_SECONDS:
            raise SourcePolicyError("connect timeout must be between 1 and 10 seconds")
        if not 1 <= self.read_timeout_seconds <= MAX_READ_TIMEOUT_SECONDS:
            raise SourcePolicyError("read timeout must be between 1 and 15 seconds")
        if not 1 <= self.max_response_bytes <= MAX_RESPONSE_BYTES:
            raise SourcePolicyError("response size must be between 1 byte and 1 MB")
        if self.allow_redirects:
            raise SourcePolicyError("automatic redirects are prohibited")
        if not self.require_https:
            raise SourcePolicyError("HTTPS is mandatory")
        return self


def validate_source_url(url: str, *, allowed_hosts: set[str]) -> str:
    """Validate exact host allowlist and HTTPS URL syntax; never performs DNS or HTTP."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise SourcePolicyError("source URL must be non-empty and at most 2048 characters")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise SourcePolicyError("source URL is malformed") from exc
    if parsed.scheme.lower() != "https" or not host:
        raise SourcePolicyError("source URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise SourcePolicyError("embedded URL credentials are prohibited")
    if port not in (None, 443):
        raise SourcePolicyError("only the default HTTPS port is allowed")
    if parsed.fragment:
        raise SourcePolicyError("URL fragments are not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SourcePolicyError("IP-literal hosts are prohibited")
    try:
        normalized = host.encode("idna").decode("ascii").lower().rstrip(".")
        allowed = {entry.encode("idna").decode("ascii").lower().rstrip(".") for entry in allowed_hosts}
    except (UnicodeError, AttributeError) as exc:
        raise SourcePolicyError("host allowlist is invalid") from exc
    if normalized not in allowed:
        raise SourcePolicyError("source host is not on the exact allowlist")
    return normalized


def validate_fetch_request(*, url: str, allowed_hosts: set[str], policy: FetchPolicy) -> dict:
    """Return a transport contract after validating URL and bounded fetch settings."""
    policy.validate()
    return {
        "url": url,
        "host": validate_source_url(url, allowed_hosts=allowed_hosts),
        "connect_timeout_seconds": policy.connect_timeout_seconds,
        "read_timeout_seconds": policy.read_timeout_seconds,
        "max_response_bytes": policy.max_response_bytes,
        "allow_redirects": False,
        "require_https": True,
        "dns_rebinding_protection_required": True,
    }
