import asyncio
import json
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class MagpieError(RuntimeError):
    pass


class MagpieClient:
    def __init__(self, base_url: str = "http://127.0.0.1:3425") -> None:
        parsed = urlsplit(base_url)
        try:
            parsed.port
        except ValueError as error:
            raise ValueError('Magpie 地址中的端口无效') from error
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.fragment or parsed.query
                or parsed.username is not None or parsed.password is not None):
            raise ValueError('Magpie 地址必须为有效的 http:// 或 https:// 地址')
        self._base_url = base_url.rstrip("/") + "/"

    async def get(self, path: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._get_sync, path)

    async def health(self) -> Dict[str, Any]:
        payload = await self.get("/")
        if payload.get("name") != "magpie":
            raise MagpieError("the configured endpoint is not Magpie")
        return payload

    def _get_sync(self, path: str) -> Dict[str, Any]:
        url = urljoin(self._base_url, path.lstrip("/"))
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except (HTTPError, URLError, OSError, ValueError) as error:
            raise MagpieError(f"failed to read {url}: {error}") from error
        if not isinstance(payload, dict):
            raise MagpieError(f"unexpected response from {url}")
        return payload
