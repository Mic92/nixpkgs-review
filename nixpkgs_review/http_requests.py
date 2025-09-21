"""Configure urllib with default settings for nixpkgs-review."""

from __future__ import annotations

import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from http.client import HTTPResponse

# Configure global User-Agent for urllib
opener = urllib.request.build_opener()
opener.addheaders = [("User-Agent", "nixpkgs-review")]
urllib.request.install_opener(opener)


def urlopen(url: str | urllib.request.Request, timeout: int = 30) -> HTTPResponse:
    """Wrapper for urllib.request.urlopen with default timeout."""
    # Validate URL scheme for security
    if isinstance(url, str):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            msg = f"Only HTTP/HTTPS URLs are allowed, got: {url}"
            raise ValueError(msg)
    elif isinstance(url, urllib.request.Request):
        parsed = urllib.parse.urlparse(url.full_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            msg = f"Only HTTP/HTTPS URLs are allowed, got: {url.full_url}"
            raise ValueError(msg)

    return cast("HTTPResponse", urllib.request.urlopen(url, timeout=timeout))  # noqa: S310
