"""
URL validation and SSRF protection.

The website-enrichment connector fetches URLs that ultimately came from
external, untrusted sources (a Google Places result, a search result). A
malicious or misconfigured "website" field could point at an internal
address (169.254.169.254 for cloud metadata, 127.0.0.1, an internal admin
panel on the same network, etc). Every outbound fetch in this project must
go through `is_safe_url()` first — see app/connectors/website.py.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Hostnames that should never be fetched even if they resolve publicly.
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def _is_private_or_reserved(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse it -> treat as unsafe
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_safe_url(url: str) -> bool:
    """Reject anything that isn't a plain public http(s) URL.

    This resolves the hostname and checks the *resolved* IP, not just the
    hostname string, so a public-looking hostname that DNS-rebinds to a
    private address is also rejected. Errors resolve to "unsafe" (fail
    closed), which is the correct default for a crawler operating on
    third-party-supplied URLs.
    """
    if not is_valid_url(url):
        return False

    hostname = urlparse(url).hostname
    if not hostname:
        return False
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False

    try:
        # getaddrinfo resolves both IPv4 and IPv6 records.
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    resolved_ips = {res[4][0] for res in results}
    if not resolved_ips:
        return False

    return all(not _is_private_or_reserved(ip) for ip in resolved_ips)
