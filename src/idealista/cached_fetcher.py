"""Replay a crawl from stored raw HTML instead of calling ZenRows.

Every record must be reproducible from the payload it was extracted from. Reading those payloads
back through the same ``HtmlFetcher`` contract the live crawl uses means parser changes can be
re-run against real pages at zero credit cost, and a suspect record can be traced to its source.

This module owns the raw-payload layout. The crawler writes with :func:`raw_html_path` and the
replay reads with the same function, so the timestamp format exists in exactly one place.
"""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .models import FetchOutcome

RAW_HTML_SUFFIX = ".html"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_SLUG_SEPARATOR = "__"
_MAX_READABLE_SLUG = 60
_DIGEST_LENGTH = 12


class MissingRawPayload(LookupError):
    """Raised when a replay finds no stored payload for a URL."""

    def __init__(self, url: str, raw_root: Path) -> None:
        super().__init__(f"no stored raw payload for {url} under {raw_root}")
        self.url = url
        self.raw_root = raw_root


def url_slug(url: str) -> str:
    """Return a filesystem-safe, collision-resistant name for ``url``.

    The readable prefix keeps the directory browsable; the digest of the full URL keeps two
    different searches from sharing a file even when their paths truncate to the same text.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
    readable = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:_MAX_READABLE_SLUG]
    readable = readable.removeprefix("https-").removeprefix("http-")
    return f"{readable}-{digest}" if readable else digest


def raw_html_path(raw_root: Path, url: str, observed_at: datetime) -> Path:
    """Return where the payload of ``url`` observed at ``observed_at`` belongs.

    Partitioned by UTC observation date to match the Bronze layout, so a day's captures can be
    pruned or shipped as a unit.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"observed_at must be timezone-aware UTC, got {observed_at!r}")

    timestamp = observed_at.strftime(_TIMESTAMP_FORMAT)
    partition = f"observed_date={observed_at.date().isoformat()}"
    name = f"{url_slug(url)}{_SLUG_SEPARATOR}{timestamp}{RAW_HTML_SUFFIX}"
    return Path(raw_root) / partition / name


class CachedHtmlFetcher:
    """An ``HtmlFetcher`` that serves stored payloads and never touches the network."""

    def __init__(self, raw_root: Path) -> None:
        self._raw_root = Path(raw_root)
        self.requests = 0
        self.credits_spent = 0
        self.stopped_reason: str | None = None

    def fetch(self, url: str) -> FetchOutcome:
        """Return the most recently stored payload for ``url``."""
        path = self._latest_payload(url)
        self.requests += 1
        return FetchOutcome(
            url=url,
            status_code=200,
            html=path.read_text(encoding="utf-8"),
            credits_spent=0,
        )

    def _latest_payload(self, url: str) -> Path:
        prefix = f"{url_slug(url)}{_SLUG_SEPARATOR}"
        candidates = [
            path
            for path in self._raw_root.rglob(f"{prefix}*{RAW_HTML_SUFFIX}")
            if path.is_file()
        ]
        if not candidates:
            raise MissingRawPayload(url, self._raw_root)
        # The timestamp format sorts lexicographically, so the last name is the newest capture.
        return max(candidates, key=lambda path: path.name)
