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

# In-memory GeoIP cache to avoid repeated network lookups across runs
_GEOIP_CACHE: dict[str, str] = {}


class ProxyCheckerService:
    """Asynchronously validates proxies against test URLs with concurrency limits and cancellation."""

    def __init__(
        self,
        config: AppConfig,
        log_callback: Callable[[str, LogLevel], None] | None = None,
        max_concurrency: int = 50,
    ) -> None:
        self.config = config
        self.log_callback = log_callback
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._is_cancelled = False
        self._running_tasks: set[asyncio.Task[ProxyItem]] = set()

    def cancel(self) -> None:
        """Cancel ongoing check process and all running tasks."""
        self._is_cancelled = True
        for task in list(self._running_tasks):
            task.cancel()

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
        host: str,
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        """
        Query GeoIP service to identify country code for host/proxy.
        Tries proxy connection first if provided, then falls back to direct lookups
        across multiple resilient free GeoIP providers with in-memory caching.
        """
        if host in _GEOIP_CACHE:
            return _GEOIP_CACHE[host]

        # 1. Try through proxy client if provided
        if client is not None:
            try:
                resp = await client.get(
                    "http://ip-api.com/json/?fields=countryCode",
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    code = data.get("countryCode")
                    if isinstance(code, str) and len(code.strip()) == 2:
                        res = code.strip().upper()
                        _GEOIP_CACHE[host] = res
                        return res
            except Exception as e:
                logger.debug("GeoIP query via proxy client failed for %s: %s", host, e)

        # 2. Direct lookup fallback across multiple providers
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as direct_client:
                # Provider 1: api.country.is
                try:
                    resp = await direct_client.get(f"https://api.country.is/{host}")
                    if resp.status_code == 200:
                        code = resp.json().get("country")
                        if isinstance(code, str) and len(code.strip()) == 2:
                            res = code.strip().upper()
                            _GEOIP_CACHE[host] = res
                            return res
                except Exception as e:
                    logger.debug("GeoIP country.is failed for %s: %s", host, e)

                # Provider 2: ipwho.is
                try:
                    resp = await direct_client.get(f"https://ipwho.is/{host}")
                    if resp.status_code == 200:
                        code = resp.json().get("country_code")
                        if isinstance(code, str) and len(code.strip()) == 2:
                            res = code.strip().upper()
                            _GEOIP_CACHE[host] = res
                            return res
                except Exception as e:
                    logger.debug("GeoIP ipwho.is failed for %s: %s", host, e)

                # Provider 3: ip-api.com
                try:
                    resp = await direct_client.get(f"http://ip-api.com/json/{host}?fields=countryCode")
                    if resp.status_code == 200:
                        code = resp.json().get("countryCode")
                        if isinstance(code, str) and len(code.strip()) == 2:
                            res = code.strip().upper()
                            _GEOIP_CACHE[host] = res
                            return res
                except Exception as e:
                    logger.debug("GeoIP ip-api.com failed for %s: %s", host, e)

                # Provider 4: freeipapi.com
                try:
                    resp = await direct_client.get(f"https://freeipapi.com/api/json/{host}")
                    if resp.status_code == 200:
                        code = resp.json().get("countryCode")
                        if isinstance(code, str) and len(code.strip()) == 2:
                            res = code.strip().upper()
                            _GEOIP_CACHE[host] = res
                            return res
                except Exception as e:
                    logger.debug("GeoIP freeipapi.com failed for %s: %s", host, e)
        except Exception as e:
            logger.debug("Direct GeoIP client error for %s: %s", host, e)

        return None

    async def check_item(
        self,
        item: ProxyItem,
        single_check: bool = False,
    ) -> bool:
        """Validate a single proxy item against configured test URL(s)."""
        if self._is_cancelled:
            return False

        async with self.semaphore:
            if self._is_cancelled:
                return False

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
                if single_check:
                    item.mark_dead(self.config.max_dead_attempts, "CONFIG_ERR")
                else:
                    item.register_failure(
                        max_attempts=self.config.max_dead_attempts,
                        url_status="CONFIG_ERR",
                    )
                return False

            pings: list[int] = []
            last_status = "200"
            all_succeeded = True
            test_urls = self.config.test_urls or ["https://google.com/"]

            try:
                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0 (ProxyRotator/1.0)"},
                ) as client:
                    for test_url in test_urls:
                        if self._is_cancelled:
                            return False
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

                    # Always resolve location if unknown
                    location = None
                    if item.location in ("Unknown", "-", "", None):
                        location = await self._fetch_geoip(
                            item.host,
                            client=client if all_succeeded else None,
                        )

                    if all_succeeded:
                        avg_ping = int(sum(pings) / len(pings)) if pings else 1
                        item.register_success(
                            ping_ms=avg_ping,
                            url_status=f"HTTP {last_status}",
                            location=location,
                        )
                        return True
                    else:
                        if location:
                            item.location = location
                        if single_check:
                            item.mark_dead(self.config.max_dead_attempts, "FAIL")
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
                if item.location in ("Unknown", "-", "", None):
                    loc = await self._fetch_geoip(item.host)
                    if loc:
                        item.location = loc

                if single_check:
                    item.mark_dead(self.config.max_dead_attempts, "FAIL")
                else:
                    item.register_failure(
                        max_attempts=self.config.max_dead_attempts,
                        url_status="FAIL",
                    )
                return False

    async def check_all(
        self,
        items: list[ProxyItem],
        on_item_completed: Callable[[ProxyItem], None] | None = None,
        single_check: bool = False,
    ) -> list[ProxyItem]:
        """Check all proxies concurrently and report progress via callback."""
        async def _check_and_notify(item: ProxyItem) -> ProxyItem:
            if not self._is_cancelled:
                await self.check_item(item, single_check=single_check)
                if on_item_completed and not self._is_cancelled:
                    try:
                        on_item_completed(item)
                    except Exception as e:
                        logger.error("Error in on_item_completed callback: %s", e)
            return item

        self._running_tasks = {
            asyncio.create_task(_check_and_notify(it)) for it in items
        }
        for task in self._running_tasks:
            task.add_done_callback(self._running_tasks.discard)

        try:
            results = await asyncio.gather(*self._running_tasks, return_exceptions=True)
            return [it for it in results if isinstance(it, ProxyItem)]
        except asyncio.CancelledError:
            self.cancel()
            raise
