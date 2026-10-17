"""Unit tests for LocalProxyServer with failover and request tunneling (Stage 4)."""
import asyncio
import socket

from src.domain.app_config import AppConfig
from src.domain.enums import LogLevel, ProxyProtocol
from src.domain.proxy_item import ProxyItem
from src.network.local_server import LocalProxyServer
from src.network.rotation_manager import ProxyRotationManager


def _get_free_port() -> int:
    """Find a random available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_server_start_and_stop():
    """Verify local server starts, binds to port, logs startup, and stops cleanly."""

    async def _run() -> None:
        port = _get_free_port()
        config = AppConfig(local_port=port, connection_timeout_ms=500)
        mgr = ProxyRotationManager([])

        logs: list[tuple[str, LogLevel]] = []

        def log_cb(msg: str, level: LogLevel) -> None:
            logs.append((msg, level))

        server = LocalProxyServer(
            config=config,
            rotation_manager=mgr,
            log_callback=log_cb,
        )

        assert not server.is_running
        await server.start()
        assert server.is_running

        # Verify green success message in log
        assert any("Локальный прокси запущен" in msg for msg, lvl in logs if lvl == LogLevel.SUCCESS)

        # Stop server
        await server.stop()
        assert not server.is_running

    asyncio.run(_run())


def test_server_failover_and_pool_exhaustion():
    """
    Verify server attempts connection to first proxy, fails over to second proxy,
    and automatically stops when all proxies become dead, returning 502 to client.
    """

    async def _run() -> None:
        port = _get_free_port()
        config = AppConfig(
            local_port=port,
            connection_timeout_ms=100,
            max_dead_attempts=1,
        )

        # Two unreachable upstream proxies
        p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59981)
        p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59982)

        mgr = ProxyRotationManager([p1, p2], max_attempts=1)

        logs: list[tuple[str, LogLevel]] = []
        exhausted_called = False

        def log_cb(msg: str, level: LogLevel) -> None:
            logs.append((msg, level))

        def on_exhausted() -> None:
            nonlocal exhausted_called
            exhausted_called = True

        server = LocalProxyServer(
            config=config,
            rotation_manager=mgr,
            log_callback=log_cb,
            on_pool_exhausted=on_exhausted,
        )

        await server.start()

        try:
            # Client connects and sends HTTP request
            client_reader, client_writer = await asyncio.open_connection("127.0.0.1", port)
            req = b"GET http://example.com/test HTTP/1.1\r\nHost: example.com\r\n\r\n"
            client_writer.write(req)
            await client_writer.drain()

            # Read response (should get 502 Bad Gateway)
            resp = await client_reader.read(4096)
            client_writer.close()
            await client_writer.wait_closed()

            assert b"502 Bad Gateway" in resp or b"All proxies are dead" in resp

            # Verify pool is empty and all proxies died
            assert mgr.is_empty()
            assert p1.fail_count == 1
            assert p2.fail_count == 1

            # Verify callbacks and red error logs
            assert exhausted_called
            assert any("Все прокси мертвы" in msg for msg, lvl in logs if lvl == LogLevel.ERROR)
            assert any("Ошибка обращения к" in msg for msg, lvl in logs if lvl == LogLevel.ERROR)

        finally:
            await server.stop()

    asyncio.run(_run())
