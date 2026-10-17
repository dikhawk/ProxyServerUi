"""Unit tests for network layer components in Stage 3."""
import asyncio

import httpx

from src.domain.app_config import AppConfig
from src.domain.enums import LogLevel, ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem
from src.network.proxy_checker import ProxyCheckerService
from src.network.rotation_manager import ProxyRotationManager
from src.network.source_fetcher import ProxySourceFetcher


def test_rotation_manager_round_robin():
    """Verify round-robin rotation of proxies in queue."""
    p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=80)
    p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=80)
    p3 = ProxyItem(protocol=ProxyProtocol.HTTP, host="3.3.3.3", port=80)

    mgr = ProxyRotationManager([p1, p2, p3], max_attempts=3)
    assert mgr.active_count() == 3
    assert not mgr.is_empty()

    # Initial head is p1
    assert mgr.get_current_proxy() == p1

    # Rotate moves p1 to back, p2 becomes head
    next_p = mgr.rotate()
    assert next_p == p2
    assert mgr.get_current_proxy() == p2

    mgr.rotate()
    assert mgr.get_current_proxy() == p3


def test_rotation_manager_failures_and_death():
    """Verify report_failure rotates alive proxies and expels dead ones."""
    p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=80)
    p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=80)

    mgr = ProxyRotationManager([p1, p2], max_attempts=2)

    # 1st failure for p1: not dead, rotated to back
    is_dead = mgr.report_failure(p1)
    assert not is_dead
    assert p1.fail_count == 1
    assert mgr.active_count() == 2
    # p2 is now front
    assert mgr.get_current_proxy() == p2

    # 2nd failure for p1 (limit is 2): p1 dies, removed from queue
    is_dead = mgr.report_failure(p1)
    assert is_dead
    assert p1.status == ProxyStatus.DEAD
    assert mgr.active_count() == 1
    assert mgr.get_current_proxy() == p2

    # Kill p2 as well
    mgr.report_failure(p2)
    mgr.report_failure(p2)
    assert p2.status == ProxyStatus.DEAD
    assert mgr.is_empty()
    assert mgr.get_current_proxy() is None


def test_source_fetcher_success_and_error():
    """Verify ProxySourceFetcher parses items on 200 and handles failures gracefully."""

    async def _run() -> None:
        logs: list[tuple[str, LogLevel]] = []

        def mock_log(msg: str, level: LogLevel) -> None:
            logs.append((msg, level))

        fetcher = ProxySourceFetcher(log_callback=mock_log)

        def mock_transport(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "good.txt" in url_str:
                return httpx.Response(200, text="1.1.1.1:8080\nsocks5://2.2.2.2:1080\n")
            if "error.txt" in url_str:
                return httpx.Response(500, text="Internal Server Error")
            return httpx.Response(404, text="Not Found")

        transport = httpx.MockTransport(mock_transport)
        async with httpx.AsyncClient(transport=transport) as client:
            # Good source
            items = await fetcher.fetch_source(client, "https://example.com/good.txt")
            assert len(items) == 2
            assert items[0].unique_key == "http://1.1.1.1:8080"
            assert items[1].unique_key == "socks5://2.2.2.2:1080"

            # Error source
            err_items = await fetcher.fetch_source(client, "https://example.com/error.txt")
            assert len(err_items) == 0

        # Ensure log callback was invoked with info and error
        assert any("200" in msg for msg, lvl in logs if lvl == LogLevel.INFO)
        assert any("500" in msg for msg, lvl in logs if lvl == LogLevel.ERROR)

    asyncio.run(_run())


def test_proxy_checker_connection_failure():
    """Verify ProxyCheckerService handles unreachable proxies and reports failures."""

    async def _run() -> None:
        logs: list[tuple[str, LogLevel]] = []

        def mock_log(msg: str, level: LogLevel) -> None:
            logs.append((msg, level))

        config = AppConfig(
            connection_timeout_ms=100,
            response_timeout_ms=100,
            max_dead_attempts=2,
            test_urls=["http://127.0.0.1:54321/test"],
        )
        checker = ProxyCheckerService(config=config, log_callback=mock_log)

        # Use closed local port as dead proxy
        dead_proxy = ProxyItem(
            protocol=ProxyProtocol.HTTP,
            host="127.0.0.1",
            port=59999,
        )

        success = await checker.check_item(dead_proxy)
        assert not success
        assert dead_proxy.fail_count == 1
        assert dead_proxy.url_status == "FAIL"

        # Red error logged
        assert any("Ошибка" in msg for msg, lvl in logs if lvl == LogLevel.ERROR)

    asyncio.run(_run())


def test_proxy_checker_check_all():
    """Verify check_all runs on multiple proxies and calls on_item_completed."""

    async def _run() -> None:
        config = AppConfig(
            connection_timeout_ms=50,
            response_timeout_ms=50,
            max_dead_attempts=2,
            test_urls=["http://127.0.0.1:54321/test"],
        )
        checker = ProxyCheckerService(config=config)

        p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59991)
        p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59992)

        completed: list[ProxyItem] = []

        def on_done(item: ProxyItem) -> None:
            completed.append(item)

        results = await checker.check_all([p1, p2], on_item_completed=on_done)
        assert len(results) == 2
        assert len(completed) == 2
        assert p1.fail_count == 1
        assert p2.fail_count == 1

    asyncio.run(_run())
