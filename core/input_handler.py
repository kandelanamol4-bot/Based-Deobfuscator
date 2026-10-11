"""Input handling: URL download (SSRF-safe), attachment bytes, raw code."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from .security import (
    is_safe_http_url, resolve_host_ips, ips_are_public, sanitize_filename,
)

ALLOWED_EXTENSIONS = {".lua", ".luau", ".txt"}
HTML_HINTS = ("<!doctype html", "<html", "<head", "<body", "<script src=")


@dataclass
class SourceInput:
    data: bytes
    filename: str
    origin: str  # "url" | "attachment" | "raw"


def sniff_text(data: bytes, max_bytes: int) -> tuple[str | None, str]:
    if not data:
        return None, "Empty input."
    if len(data) > max_bytes:
        return None, f"Input exceeds limit ({len(data)} > {max_bytes} bytes)."
    if b"\x00" in data[:8192]:
        return None, "Binary content detected; only Lua/Luau text is accepted."
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    if text is None:
        return None, "Could not decode input as text."
    stripped = text.strip()
    if not stripped:
        return None, "Empty input."
    low = stripped[:2000].lower()
    if any(h in low for h in HTML_HINTS):
        return None, "URL returned an HTML page, not Lua source."
    return text, "ok"


def validate_extension(filename: str) -> tuple[bool, str]:
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_EXTENSIONS:
        return True, "ok"
    return False, f"Unsupported extension '{ext}'. Use .lua, .luau or .txt."


def validate_raw_code(code: str, max_chars: int, max_bytes: int) -> tuple[str | None, str]:
    if not code or not code.strip():
        return None, "Empty input."
    if len(code) > max_chars:
        return None, (
            f"Pasted code is {len(code)} chars (limit {max_chars}). "
            "Upload a file or use a URL instead."
        )
    data = code.encode("utf-8", errors="replace")
    return sniff_text(data, max_bytes)


async def download_url(
    url: str,
    max_bytes: int,
    connect_timeout: float = 10.0,
    total_timeout: float = 30.0,
    max_redirects: int = 3,
) -> tuple[bytes | None, str, str]:
    """Return (data, filename, error). SSRF-safe: validates each hop."""
    ok, msg = is_safe_http_url(url)
    if not ok:
        return None, "", msg
    timeout = aiohttp.ClientTimeout(connect=connect_timeout, total=total_timeout)
    current = url
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(max_redirects + 1):
            ok, msg = is_safe_http_url(current)
            if not ok:
                return None, "", f"Redirect blocked: {msg}"
            host = urlparse(current).hostname or ""
            ips = await resolve_host_ips(host)
            good, why = ips_are_public(ips)
            if not good:
                return None, "", f"Blocked unsafe destination: {why}"
            try:
                async with session.get(current, allow_redirects=False, max_line_size=65536) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("Location")
                        if not loc:
                            return None, "", "Redirect without Location."
                        from urllib.parse import urljoin
                        current = urljoin(current, loc)
                        continue
                    if resp.status != 200:
                        return None, "", f"Download failed (HTTP {resp.status})."
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if "text/html" in ctype:
                        return None, "", "URL returned an HTML page, not Lua source."
                    clen = resp.headers.get("Content-Length")
                    if clen and clen.isdigit() and int(clen) > max_bytes:
                        return None, "", f"File too large ({clen} bytes)."
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > max_bytes:
                            return None, "", "File exceeds download-size limit."
                        chunks.append(chunk)
                    data = b"".join(chunks)
            except asyncio.TimeoutError:
                return None, "", "Download timed out."
            except aiohttp.ClientError as e:
                return None, "", f"Download error: {type(e).__name__}."
            path = urlparse(current).path or "/source.lua"
            fname = sanitize_filename(path.rsplit("/", 1)[-1] or "source.lua")
            if not fname.endswith((".lua", ".luau", ".txt")):
                fname += ".lua"
            return data, fname, "ok"
    return None, "", "Too many redirects."
