"""Security helpers: SSRF protection, filename sanitizing, secret redaction."""
from __future__ import annotations
import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

PRIVATE_HINTS = ("localhost", "metadata.google.internal")

_SECRET_PATTERNS = [
    re.compile(r"(?i)(token\s*[:=]\s*)(['\"]?)([A-Za-z0-9._\-]{8,})\2"),
    re.compile(r"(?i)(password\s*[:=]\s*)(['\"]?)([^\s'\"]+)\2"),
]


def sanitize_filename(name: str, default: str = "input.lua") -> str:
    name = Path(name).name.strip() or default
    name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)
    if not name or name in (".", ".."):
        return default
    if "." not in name:
        name += ".lua"
    return name[:100]


def is_safe_http_url(url: str) -> tuple[bool, str]:
    """Validate URL structure (scheme/host). Deep SSRF checks happen at fetch time."""
    try:
        p = urlparse(url.strip())
    except Exception:
        return False, "Malformed URL."
    if p.scheme not in ("http", "https"):
        return False, "Only http(s) URLs are supported."
    if p.scheme == "http":
        return False, "Only HTTPS URLs are accepted."
    if not p.hostname:
        return False, "URL has no host."
    host = p.hostname.lower()
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return False, "URL target is not allowed (internal name)."
    if "@" in (p.netloc or "") and p.password:
        return False, "URLs containing credentials are rejected."
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False, "URL resolves to a private/internal address."
    except ValueError:
        pass  # hostname, resolved + checked at fetch time
    return True, "ok"


async def resolve_host_ips(host: str) -> list[str]:
    loop = __import__("asyncio").get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return list({info[4][0] for info in infos})
    except Exception:
        return []


def ips_are_public(ips: list[str]) -> tuple[bool, str]:
    if not ips:
        return False, "Could not resolve host."
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Unresolvable address: {ip_str}"
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, f"URL resolves to disallowed address {ip_str}."
    return True, "ok"


def redact_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(1) + "***", out)
    # redact query-string secrets in URLs for logs
    out = re.sub(r"(?i)([?&](token|key|auth|secret|password)=)[^&\s]+", r"\1***", out)
    return out


def safe_log_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.hostname or "?"
        return f"{p.scheme}://{host}/... ({len(url)} chars)"
    except Exception:
        return "(unparseable url)"
