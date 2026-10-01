"""Unified schema for the Personal Internet Vault.

Every thing you save on the internet — a YouTube video, a Reddit post, a
GitHub repo, a Spotify track, a browser bookmark — becomes one SavedItem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

#: Services the vault knows how to normalize.
SERVICES = ("youtube", "reddit", "github", "spotify", "browser")

#: Query params that are tracking junk and should be stripped for dedupe.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "igshid", "si", "ref", "source",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_url(url: str) -> str:
    """Return a canonical dedupe key for a URL.

    Lowercases scheme+host, strips fragments and known tracking query
    params, keeps the rest so distinct pages stay distinct.
    """
    if not url:
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower()
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if not netloc:
        # Not an absolute URL (e.g. a bare video id) — use as-is, lowercased.
        return url.lower()
    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in TRACKING_PARAMS),
        doseq=True,
    )
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path.rstrip("/") or "/", query, ""))


def coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Heuristic: ms epoch vs s epoch.
        if value > 1e12:
            value = value / 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            dt = None
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return utcnow()


@dataclass
class SavedItem:
    """One saved thing, from any service."""

    service: str            # youtube | reddit | github | spotify | browser | ...
    kind: str               # video | post | repo | issue | track | bookmark | ...
    title: str
    url: str
    saved_at: datetime = field(default_factory=utcnow)
    tags: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    id: int | None = None

    def __post_init__(self):
        self.service = (self.service or "unknown").lower().strip()
        self.kind = (self.kind or "item").lower().strip()
        self.title = (self.title or "").strip()
        self.url = (self.url or "").strip()
        self.saved_at = coerce_datetime(self.saved_at)
        self.tags = sorted({str(t).strip().lower() for t in (self.tags or []) if str(t).strip()})
        if not isinstance(self.metadata, dict):
            self.metadata = {}

    @property
    def url_key(self) -> str:
        return normalize_url(self.url)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["saved_at"] = self.saved_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SavedItem":
        data = dict(data)
        data.pop("url_key", None)
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
