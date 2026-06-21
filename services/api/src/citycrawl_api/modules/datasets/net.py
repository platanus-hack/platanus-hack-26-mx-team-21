"""Outbound-fetch SSRF guard shared by every adapter that hits an upstream URL (CKAN
resource URLs returned by upstream, RSS feeds, Nominatim).

Without this, the server would fetch attacker-influenced URLs with follow_redirects=True and
no validation — a classic SSRF / metadata-exfil vector. Every guarded GET:

  * requires https
  * checks the host against an allowlist (datos.cdmx.gob.mx + any *.gob.mx, the configured
    Nominatim host, the RSS feed hosts declared in registry/sources.yaml, plus any extra
    hosts from OUTBOUND_ALLOWED_HOSTS)
  * resolves the host and rejects private / loopback / link-local / metadata IPs (so an
    allowlisted name that resolves to 169.254.169.254 / 127.0.0.1 / 10.x etc. is rejected)
  * PINS the connection to the validated IP (connect-by-IP while keeping the Host header and
    TLS SNI), so a DNS rebind between our validation and httpx's own resolve can't redirect
    the request to an internal target (the TOCTOU window). When the IP can't be captured
    (e.g. tests monkeypatch the resolver), it falls back to a by-name connect and the host
    allowlist remains the primary control.
  * does NOT follow redirects (a 3xx to an internal target is surfaced, not chased)
  * caps the response body size

It is intentionally dependency-free (stdlib socket/ipaddress + httpx) so it imports without
pandas/numpy.
"""
from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlsplit

import httpx

from citycrawl_api.config import Settings, get_settings


class OutboundFetchError(Exception):
    """Raised when an outbound URL fails the SSRF guard. Adapters let this surface as a 5xx;
    it is never echoed to an end user verbatim by the routers."""


# Always-allowed base hosts. *.gob.mx is matched by suffix (see _host_allowed). The CKAN
# host and the RSS feed hosts live here too; the configured Nominatim host and any
# OUTBOUND_ALLOWED_HOSTS extras are added at runtime.
_STATIC_ALLOWED_HOSTS = {
    "datos.cdmx.gob.mx",
    "www.eluniversal.com.mx",
    "www.jornada.com.mx",
}
_ALLOWED_SUFFIXES = (".gob.mx",)


@lru_cache(maxsize=1)
def _feed_hosts_from_registry() -> frozenset[str]:
    """Hosts declared as RSS feeds in registry/sources.yaml, so the allowlist stays in sync
    with the catalog without hardcoding. Best-effort: failures fall back to the static set."""
    try:
        from citycrawl_api.modules.datasets.registry.loader import load_registry

        hosts: set[str] = set()
        for source in load_registry():
            for feed in source.feeds or []:
                host = urlsplit(feed).hostname
                if host:
                    hosts.add(host.lower())
        return frozenset(hosts)
    except Exception:  # noqa: BLE001 - registry is optional context for the allowlist
        return frozenset()


def _allowed_hosts(settings: Settings) -> set[str]:
    hosts = set(_STATIC_ALLOWED_HOSTS)
    hosts |= set(_feed_hosts_from_registry())
    hosts |= set(settings.extra_outbound_hosts)
    nom_host = urlsplit(settings.nominatim_base_url).hostname
    if nom_host:
        hosts.add(nom_host.lower())
    return hosts


def _host_allowed(host: str, settings: Settings) -> bool:
    host = host.lower()
    if host in _allowed_hosts(settings):
        return True
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_SUFFIXES)


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local       # incl. 169.254.0.0/16 cloud metadata range
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _resolve_public_addrs(host: str) -> list[str]:
    """Return the host's resolved A/AAAA addresses, or [] if it doesn't resolve. Raise
    OutboundFetchError if ANY resolved address is non-public — we require EVERY address to be
    public to avoid DNS-rebinding to an internal target."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    addrs = [info[4][0] for info in infos]
    if not addrs:
        return []
    bad = [a for a in addrs if not _is_public_ip(a)]
    if bad:
        raise OutboundFetchError(
            f"host resolves to a non-public address: {host!r} -> {bad!r}"
        )
    # De-dup preserving order so the pinned-connect path has a deterministic first choice.
    return list(dict.fromkeys(addrs))


def _resolves_to_public(host: str) -> bool:
    """Back-compat boolean wrapper (kept for existing tests that monkeypatch it). True iff
    the host resolves and every resolved address is public."""
    try:
        return bool(_resolve_public_addrs(host))
    except OutboundFetchError:
        return False


def assert_safe_url(url: str, settings: Settings | None = None) -> list[str]:
    """Raise OutboundFetchError unless `url` is https, on the host allowlist, and resolves
    only to public IPs. Returns the validated public IPs so the caller can PIN the connection
    to one of them (closing the DNS-rebinding TOCTOU between this resolve and httpx's own).
    Call before every outbound GET."""
    settings = settings or get_settings()
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise OutboundFetchError(f"outbound URL must be https: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise OutboundFetchError("outbound URL has no host")
    if not _host_allowed(host, settings):
        raise OutboundFetchError(f"host not allowlisted: {host!r}")
    # Gate on the boolean wrapper (monkeypatchable in tests). It returns False both when the
    # host doesn't resolve and when any address is non-public; either way the URL is unsafe.
    if not _resolves_to_public(host):
        raise OutboundFetchError(f"host resolves to a non-public address: {host!r}")
    # Re-resolve to capture the validated public IPs for pinning. Best-effort: if this second
    # lookup fails or returns nothing (e.g. the gate above was monkeypatched), we return [] and
    # safe_get falls back to its by-name connect (the allowlist remains the primary control).
    try:
        return _resolve_public_addrs(host)
    except OutboundFetchError:
        raise
    except Exception:  # noqa: BLE001 - pinning is best-effort
        return []


def _pinned_request_args(
    url: str, addrs: list[str], headers: dict[str, str] | None
) -> tuple[str, dict[str, str], dict | None]:
    """Rewrite (url, headers, extensions) so httpx CONNECTS to a validated IP while keeping
    the original Host header and TLS SNI. This pins the connection to the exact address we
    just validated, so httpx's own DNS lookup can't be rebound to an internal target between
    our check and the connect (the TOCTOU window). Returns the original url and no extensions
    when there's nothing to pin (addrs empty), so we fall back to a normal by-name connect."""
    if not addrs:
        return url, dict(headers or {}), None
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip = addrs[0]
    # Bracket IPv6 literals in the authority.
    host_in_url = f"[{ip}]" if ":" in ip else ip
    authority = host_in_url
    if parts.port:
        authority = f"{host_in_url}:{parts.port}"
    pinned_url = parts._replace(netloc=authority).geturl()
    new_headers = dict(headers or {})
    # Preserve virtual-hosting + cert validation: Host header drives routing, sni_hostname
    # drives the TLS handshake/cert check against the real name, not the IP literal.
    new_headers["Host"] = host
    extensions = {"sni_hostname": host}
    return pinned_url, new_headers, extensions


def safe_get(
    url: str,
    *,
    settings: Settings | None = None,
    timeout: float = 60.0,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
) -> httpx.Response:
    """Guarded GET: validates the URL, PINS the connection to a validated public IP (so a
    DNS rebind between validation and connect can't redirect us to an internal target),
    disables redirect-following, and caps the body size."""
    settings = settings or get_settings()
    addrs = assert_safe_url(url, settings)
    request_url, req_headers, extensions = _pinned_request_args(url, addrs, headers)
    max_bytes = settings.outbound_max_bytes
    # follow_redirects=False: a 3xx to an internal target is surfaced, never chased.
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        with client.stream(
            "GET", request_url, headers=req_headers, params=params, extensions=extensions
        ) as resp:
            if resp.is_redirect:
                raise OutboundFetchError(
                    f"outbound redirect refused ({resp.status_code}) for {url}"
                )
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise OutboundFetchError(
                        f"outbound response exceeds {max_bytes} bytes for {url}"
                    )
                chunks.append(chunk)
            content = b"".join(chunks)
    # Rebuild a Response carrying the buffered body so callers can use .content/.json().
    return httpx.Response(
        status_code=resp.status_code,
        headers=resp.headers,
        content=content,
        request=resp.request,
    )
