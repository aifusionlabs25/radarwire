from __future__ import annotations
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin
import ipaddress, socket
TRACKING_KEYS={"fbclid","gclid","msclkid","mc_cid","mc_eid","igshid","utm_source","utm_medium","utm_campaign","utm_term","utm_content"}
def canonicalize_url(url: str) -> str:
    p=urlsplit(url.strip()); scheme=p.scheme.lower() or "https"; host=(p.hostname or "").lower().rstrip('.')
    if not host: raise ValueError("URL missing host")
    port=f":{p.port}" if p.port and not ((scheme=="https" and p.port==443) or (scheme=="http" and p.port==80)) else ""
    path=p.path or "/"; qs=[(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True) if not (k.lower().startswith("utm_") or k.lower() in TRACKING_KEYS)]
    return urlunsplit((scheme, host+port, path, urlencode(qs, doseq=True), ""))
def same_allowed(url: str, domains: list[str], paths: list[str]) -> bool:
    p=urlsplit(url); host=(p.hostname or "").lower(); domains=[d.lower() for d in domains]
    return host in domains and p.scheme in {"http","https"} and any((p.path or "/").startswith(path) for path in paths)
def validate_public_http_url(url: str, domains: list[str], paths: list[str], resolve_dns: bool=False) -> str:
    c=canonicalize_url(url)
    if not same_allowed(c, domains, paths): raise ValueError(f"URL outside configured scope: {c}")
    if resolve_dns:
        host=urlsplit(c).hostname or ""
        for info in socket.getaddrinfo(host, None):
            ip=ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved: raise ValueError(f"Host resolves to non-public address: {host}")
    return c
def safe_join(base: str, href: str, domains: list[str], paths: list[str]) -> str|None:
    if not href or href.startswith(("mailto:","javascript:","tel:")): return None
    try: return validate_public_http_url(urljoin(base, href), domains, paths)
    except Exception: return None
