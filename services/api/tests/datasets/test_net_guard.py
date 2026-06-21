"""M-SSRF: the outbound-fetch guard. Validates scheme, host allowlist (gob.mx + nominatim +
RSS feed hosts from the registry), and private/loopback/link-local/metadata-IP rejection."""
import pytest

from citycrawl_api.config import Settings
from citycrawl_api.modules.datasets import net
from citycrawl_api.modules.datasets.net import OutboundFetchError, assert_safe_url


def _settings(**kw):
    kw.setdefault("allowed_origins", "http://localhost:5173")
    return Settings(**kw)


def test_https_required():
    with pytest.raises(OutboundFetchError):
        assert_safe_url("http://datos.cdmx.gob.mx/x", _settings())


def test_gob_mx_suffix_allowed(monkeypatch):
    monkeypatch.setattr(net, "_resolves_to_public", lambda h: True)
    assert_safe_url("https://anything.gob.mx/x", _settings())


def test_registry_feed_hosts_allowed(monkeypatch):
    monkeypatch.setattr(net, "_resolves_to_public", lambda h: True)
    assert_safe_url("https://www.eluniversal.com.mx/rss/metropoli.xml", _settings())
    assert_safe_url("https://www.jornada.com.mx/rss/capital.xml", _settings())


def test_nominatim_host_allowed(monkeypatch):
    monkeypatch.setattr(net, "_resolves_to_public", lambda h: True)
    s = _settings(nominatim_base_url="https://nominatim.example.org")
    assert_safe_url("https://nominatim.example.org/search", s)


def test_non_allowlisted_host_rejected():
    with pytest.raises(OutboundFetchError):
        assert_safe_url("https://evil.example.com/x", _settings())


def test_extra_outbound_hosts_configurable(monkeypatch):
    monkeypatch.setattr(net, "_resolves_to_public", lambda h: True)
    s = _settings(outbound_allowed_hosts="api.partner.example")
    assert_safe_url("https://api.partner.example/x", s)


def test_metadata_ip_rejected_even_if_allowlisted(monkeypatch):
    # An allowlisted name that resolves to a private/metadata IP is still rejected.
    s = _settings(outbound_allowed_hosts="internal.gob.mx")
    monkeypatch.setattr(net, "_resolves_to_public", lambda h: False)
    with pytest.raises(OutboundFetchError):
        assert_safe_url("https://internal.gob.mx/x", s)


@pytest.mark.parametrize("ip,public", [
    ("8.8.8.8", True),
    ("127.0.0.1", False),
    ("10.0.0.1", False),
    ("192.168.1.1", False),
    ("169.254.169.254", False),  # cloud metadata
    ("::1", False),
])
def test_ip_classification(ip, public):
    assert net._is_public_ip(ip) is public


# --- #5: IP pinning (DNS-rebinding TOCTOU) ---------------------------------------------


def test_assert_safe_url_returns_validated_public_ips(monkeypatch):
    # The validated IPs are returned so safe_get can PIN the connection to them.
    monkeypatch.setattr(net, "_resolves_to_public", lambda h: True)
    monkeypatch.setattr(net, "_resolve_public_addrs", lambda h: ["203.0.113.5"])
    addrs = assert_safe_url("https://anything.gob.mx/x", _settings())
    assert addrs == ["203.0.113.5"]


def test_resolve_public_addrs_raises_on_private(monkeypatch):
    # If any resolved address is non-public, resolution raises (no silent pin to internal).
    monkeypatch.setattr(
        net.socket, "getaddrinfo",
        lambda host, port: [(None, None, None, None, ("10.0.0.1", 0))],
    )
    with pytest.raises(OutboundFetchError):
        net._resolve_public_addrs("internal.gob.mx")


def test_pinned_request_args_connects_by_ip_keeps_host_and_sni():
    url, headers, ext = net._pinned_request_args(
        "https://datos.cdmx.gob.mx/path?q=1", ["203.0.113.5"], {"Accept": "*/*"}
    )
    assert "203.0.113.5" in url
    assert "datos.cdmx.gob.mx" not in url  # connect target is the pinned IP, not the name
    assert headers["Host"] == "datos.cdmx.gob.mx"   # virtual-host routing preserved
    assert headers["Accept"] == "*/*"               # caller headers preserved
    assert ext == {"sni_hostname": "datos.cdmx.gob.mx"}  # TLS cert validated vs real name


def test_pinned_request_args_brackets_ipv6():
    url, headers, ext = net._pinned_request_args(
        "https://example.gob.mx/x", ["2606:4700:4700::1111"], None
    )
    assert "[2606:4700:4700::1111]" in url


def test_pinned_request_args_no_addrs_is_passthrough():
    # Empty addrs (e.g. resolver monkeypatched) -> by-name connect, no extensions.
    url, headers, ext = net._pinned_request_args("https://x.gob.mx/y", [], {"A": "b"})
    assert url == "https://x.gob.mx/y"
    assert headers == {"A": "b"}
    assert ext is None
