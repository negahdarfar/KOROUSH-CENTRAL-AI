"""Declarative source connector catalog; all entries are disabled contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ConnectorDescriptor:
    connector_id: str
    protocol: str
    domains: tuple[str, ...]
    status: str = "contract-only"
    outbound_fetch_enabled: bool = False
    requires_secret: bool = False
    max_response_bytes: int = 1_000_000


_CONNECTORS = (
    ConnectorDescriptor("source.rss.v1", "rss-xml", ("forex", "youtube", "ptc", "nft")),
    ConnectorDescriptor("source.rest-json.v1", "https-json", ("forex", "youtube", "ptc", "nft"), requires_secret=True),
    ConnectorDescriptor("source.html-readonly.v1", "https-html", ("forex", "youtube", "ptc", "nft")),
    ConnectorDescriptor("source.market-data.v1", "market-data-api", ("forex",)),
    ConnectorDescriptor("source.youtube-metadata.v1", "youtube-data-api", ("youtube",), requires_secret=True),
    ConnectorDescriptor("source.chain-readonly.v1", "read-only-chain-rpc", ("nft",), requires_secret=True),
)


def list_connectors(*, domain: str | None = None) -> list[dict]:
    if domain is not None and domain not in {"forex", "youtube", "ptc", "nft"}:
        raise ValueError("unsupported source domain")
    return [
        asdict(item)
        for item in _CONNECTORS
        if domain is None or domain in item.domains
    ]
