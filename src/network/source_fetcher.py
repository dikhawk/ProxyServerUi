"""Service for fetching proxy lists from remote URLs."""
import asyncio
import logging
from collections.abc import Callable

import httpx

from src.data.proxy_parser import ProxyParser
from src.domain.enums import LogLevel, ProxyProtocol
from src.domain.proxy_item import ProxyItem

logger = logging.getLogger(__name__)


class ProxySourceFetcher:
    """Asynchronously fetches raw proxy lists from configured URLs and parses them."""

    def __init__(
        self,
        log_callback: Callable[[str, LogLevel], None] | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.log_callback = log_callback
        self.timeout_seconds = timeout_seconds

    def _log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Forward message to UI log callback and standard logger."""
        if self.log_callback:
            try:
                self.log_callback(message, level)
            except Exception as e:
                logger.error("Error invoking log callback: %s", e)
        if level == LogLevel.ERROR:
            logger.error(message)
        else:
            logger.info(message)

    async def fetch_source(
        self,
        client: httpx.AsyncClient,
        url: str,
        default_protocol: ProxyProtocol = ProxyProtocol.HTTP,
    ) -> list[ProxyItem]:
        """Fetch and parse proxies from a single URL."""
        trimmed_url = url.strip()
        if not trimmed_url:
            return []

        try:
            response = await client.get(trimmed_url)
            if response.status_code == 200:
                self._log(
                    f"Загрузка источника {trimmed_url} | HTTP {response.status_code}",
                    LogLevel.INFO,
                )
                items = ProxyParser.parse_text(response.text, default_protocol)
                self._log(
                    f"Источник {trimmed_url}: получено {len(items)} прокси",
                    LogLevel.INFO,
                )
                return items
            self._log(
                f"Ошибка загрузки источника {trimmed_url} | Причина: HTTP {response.status_code}",
                LogLevel.ERROR,
            )
            return []
        except httpx.TimeoutException:
            self._log(
                f"Ошибка загрузки источника {trimmed_url} | Причина: Connection Timeout",
                LogLevel.ERROR,
            )
            return []
        except httpx.RequestError as exc:
            self._log(
                f"Ошибка загрузки источника {trimmed_url} | Причина: {type(exc).__name__}",
                LogLevel.ERROR,
            )
            return []
        except Exception as exc:
            self._log(
                f"Ошибка загрузки источника {trimmed_url} | Причина: {exc}",
                LogLevel.ERROR,
            )
            return []

    async def fetch_all(
        self,
        sources: list[str],
        default_protocol: ProxyProtocol = ProxyProtocol.HTTP,
    ) -> list[ProxyItem]:
        """Fetch from all URLs concurrently and return combined proxy items."""
        valid_sources = [s.strip() for s in sources if s.strip()]
        if not valid_sources:
            return []

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (ProxyRotator/1.0)"},
        ) as client:
            tasks = [
                self.fetch_source(client, src, default_protocol)
                for src in valid_sources
            ]
            results = await asyncio.gather(*tasks, return_exceptions=False)

        combined: list[ProxyItem] = []
        for items in results:
            combined.extend(items)
        return combined
