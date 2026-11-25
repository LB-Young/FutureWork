"""Fetch bounded public web text while validating every redirect destination."""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx


class PageText(HTMLParser):
    """Collect visible HTML text and skip scripts or styles."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        elif tag in {"p", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        elif tag in {"p", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


async def public_url(url: str) -> bool:
    """Reject local/private IP addresses and unsafe URL components."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return False
        addresses = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (ValueError, OSError):
        return False


async def fetch_public(url: str, config: dict) -> str:
    """Fetch a public page with bounded bytes, redirects and time."""
    settings = config["tool_runtime"]
    if not isinstance(url, str) or len(url) > settings["max_url_chars"]:
        raise ValueError("invalid URL")
    async with httpx.AsyncClient(timeout=settings["web_timeout_seconds"], follow_redirects=False) as client:
        for _ in range(settings["max_web_redirects"] + 1):
            if not await public_url(url):
                raise ValueError("URL is not a public HTTP(S) address")
            async with client.stream("GET", url, headers={"User-Agent": settings["web_user_agent"]}) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect has no location")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > settings["max_web_bytes"]:
                        raise ValueError("web response exceeds limit")
                    chunks.append(chunk)
                raw = b"".join(chunks).decode("utf-8", errors="replace")
                if "html" in response.headers.get("content-type", "").lower() or "<html" in raw[:500].lower():
                    parser = PageText()
                    parser.feed(raw)
                    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
                return raw.strip()
        raise ValueError("too many redirects")


async def run(args: dict, config: dict) -> str:
    """Return the requested number of public page characters."""
    content = await fetch_public(args["url"], config)
    settings = config["tool_runtime"]
    length = max(1, min(int(args.get("max_length", settings["max_result_chars"])), settings["max_result_chars"]))
    return content[:length] or "(empty page)"
