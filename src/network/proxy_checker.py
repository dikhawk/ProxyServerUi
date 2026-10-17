"""Service for checking proxy connectivity, response times, and GeoIP."""
import asyncio
import logging
import time
from collections.abc import Callable

import httpx
from httpx_socks import AsyncProxyTransport, ProxyError

from src.domain.app_config import AppConfig
from src.domain.enums import LogLevel, ProxyStatus
from src.domain.proxy_item import ProxyItem

logger = logging.getLogger(__name__)


class ProxyCheckerService:
    """Asynchronously validates proxies against test URLs with concurrency limits."""

    def __init__(
        self,
        config: AppConfig,
        log_callback: Callable[[str, LogLevel], None] | None = None,
        max_concurrency: int = 50,
    ) -> None:
        self.config = config
        self.log_callback = log_callback
        self.semaphore = asyncio.Semaphore(max_concurrency)

    def _log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Deliver log message to UI callback and logging system."""
        if self.log_callback:
            try:
                self.log_callback(message, level)
            except Exception as e:
                logger.error("Error in log callback: %s", e)
        if level == LogLevel.ERROR:
            logger.error(message)
        else:
            logger.info(message)

    def _format_exception_reason(self, exc: Exception) -> str:
        """Map exception to a concise descriptive reason."""
        if isinstance(exc, httpx.TimeoutException):
            return "Timeout"
        if isinstance(exc, ProxyError):
            return "ProxyError"
        if isinstance(exc, httpx.ConnectError):
            return "ConnectionError"
        return type(exc).__name__

    async def _fetch_geoip(
        self,
        client: httpx.AsyncClient,
    ) -> str | None:
        """Query GeoIP service through proxy to identify country code."""
        try:
            resp = await client.get(
                "http://ip-api.com/json/?fields=countryCode",
                timeout=4.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                code = data.get("countryCode")
                if isinstance(code, str) and code.strip():
                    return code.strip().upper()
        except Exception:
            return None
        return None

    async def check_item(self, item: ProxyItem) -> bool:
        """Validate a single proxy item against all configured test URLs."""
        async with self.semaphore:
            item.status = ProxyStatus.CHECKING

            connect_sec = max(0.1, self.config.connection_timeout_ms / 1000.0)
            response_sec = max(0.1, self.config.response_timeout_ms / 1000.0)
            timeout = httpx.Timeout(
                connect=connect_sec,
                read=response_sec,
                write=response_sec,
                pool=connect_sec,
            )

            try:
                transport = AsyncProxyTransport.from_url(item.upstream_url)
            except Exception as exc:
                reason = f"Invalid Proxy URL: {exc}"
                self._log(
                    f"[Чекер] Ошибка {item.host}:{item.port} | Причина: {reason}",
                    LogLevel.ERROR,
                )
                item.register_failure(
                    max_attempts=self.config.max_dead_attempts,
                    url_status="CONFIG_ERR",
                )
                return False

            pings: list[int] = []
            last_status = "200"
            all_succeeded = True

            try:
                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0 (ProxyRotator/1.0)"},
                ) as client:
                    for test_url in self.config.test_urls:
                        t0 = time.perf_counter()
                        try:
                            response = await client.get(test_url)
                            ping_ms = max(1, int((time.perf_counter() - t0) * 1000))
                            if 200 <= response.status_code < 400:
                                pings.append(ping_ms)
                                last_status = str(response.status_code)
                                self._log(
                                    f"[Чекер] Прокси {item.host}:{item.port} -> {test_url} | "
                                    f"Статус: {response.status_code} ({ping_ms} мс)",
                                    LogLevel.INFO,
                                )
                            else:
                                all_succeeded = False
                                self._log(
                                    f"[Чекер] Ошибка {item.host}:{item.port} -> {test_url} | "
                                    f"Причина: HTTP {response.status_code}",
                                    LogLevel.ERROR,
                                )
                                break
                        except Exception as exc:
                            all_succeeded = False
                            reason = self._format_exception_reason(exc)
                            self._log(
                                f"[Чекер] Ошибка {item.host}:{item.port} -> {test_url} | "
                                f"Причина: {reason}",
                                LogLevel.ERROR,
                            )
                            break

                    if all_succeeded:
                        # Determine country if currently Unknown
                        location = None
                        if item.location in ("Unknown", "-", "", None):
                            location = await self._fetch_geoip(client)

                        avg_ping = int(sum(pings) / len(pings)) if pings else 1
                        item.register_success(
                            ping_ms=avg_ping,
                            url_status=f"HTTP {last_status}",
                            location=location,
                        )
                        return True
                    else:
                        item.register_failure(
                            max_attempts=self.config.max_dead_attempts,
                            url_status="FAIL",
                        )
                        return False

            except Exception as exc:
                reason = self._format_exception_reason(exc)
                self._log(
                    f"[Чекер] Ошибка {item.host}:{item.port} | Причина: {reason}",
                    LogLevel.ERROR,
                )
                item.register_failure(
                    max_attempts=self.config.max_dead_attempts,
                    url_status="FAIL",
                )
                return False

    async def check_all(
        self,
        items: list[ProxyItem],
        on_item_completed: Callable[[ProxyItem], None] | None = None,
    ) -> list[ProxyItem]:
        """Check all proxies concurrently and report progress via callback."""
        async def _check_and_notify(item: ProxyItem) -> ProxyItem:
            await self.check_item(item)
            if on_item_completed:
                try:
                    on_item_completed(item)
                except Exception as e:
                    logger.error("Error in on_item_completed callback: %s", e)
            return item

        tasks = [_check_and_notify(it) for it in items]
        return await asyncio.gather(*tasks)
