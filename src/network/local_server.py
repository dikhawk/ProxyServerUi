"""Local proxy server with transparent failover and detailed request logging."""
import asyncio
import contextlib
import logging
from collections.abc import Callable
from urllib.parse import urlsplit

import python_socks
from python_socks.async_.asyncio import Proxy

from src.domain.app_config import AppConfig
from src.domain.enums import LogLevel
from src.domain.proxy_item import ProxyItem
from src.network.rotation_manager import ProxyRotationManager

logger = logging.getLogger(__name__)


class LocalProxyServer:
    """
    Asynchronous local proxy server listening on 127.0.0.1:local_port.
    Handles HTTP and CONNECT requests, routing them through upstream proxies
    managed by ProxyRotationManager with seamless real-time failover.
    """

    def __init__(
        self,
        config: AppConfig,
        rotation_manager: ProxyRotationManager,
        log_callback: Callable[[str, LogLevel], None] | None = None,
        on_pool_exhausted: Callable[[], None] | None = None,
        on_pool_updated: Callable[[int, int], None] | None = None,
        on_proxy_status_changed: Callable[[ProxyItem], None] | None = None,
    ) -> None:
        self.config = config
        self.rotation_manager = rotation_manager
        self.log_callback = log_callback
        self.on_pool_exhausted = on_pool_exhausted
        self.on_pool_updated = on_pool_updated
        self.on_proxy_status_changed = on_proxy_status_changed
        self.total_proxies = rotation_manager.active_count()
        self.is_running = False
        self._server: asyncio.Server | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()

    def _log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Deliver log message to UI callback and standard logger."""
        if self.log_callback:
            try:
                self.log_callback(message, level)
            except Exception as e:
                logger.error("Error in server log callback: %s", e)
        if level == LogLevel.ERROR:
            logger.error(message)
        else:
            logger.info(message)

    def _format_error(self, exc: Exception) -> str:
        """Map exception to a concise descriptive error string."""
        if isinstance(exc, python_socks.ProxyTimeoutError | asyncio.TimeoutError | TimeoutError):
            return f"Connection Timeout ({self.config.connection_timeout_ms} ms)"
        if isinstance(exc, python_socks.ProxyConnectionError | ConnectionRefusedError):
            return "Connection Refused"
        if isinstance(exc, ConnectionResetError):
            return "Connection Reset"
        if isinstance(exc, python_socks.ProxyError):
            return "ProxyError"
        return type(exc).__name__

    def _notify_pool_updated(self) -> None:
        """Notify listener of current alive vs initial proxy count."""
        if self.on_pool_updated:
            with contextlib.suppress(Exception):
                self.on_pool_updated(self.rotation_manager.active_count(), self.total_proxies)

    async def start(self) -> None:
        """Start listening on 127.0.0.1:local_port."""
        if self.is_running:
            return

        self.total_proxies = self.rotation_manager.active_count()
        self._server = await asyncio.start_server(
            self._handle_client_connection,
            host="127.0.0.1",
            port=self.config.local_port,
        )
        self.is_running = True
        self._notify_pool_updated()
        self._log(
            f"Локальный прокси запущен: http://127.0.0.1:{self.config.local_port}",
            LogLevel.SUCCESS,
        )

    async def stop(self) -> None:
        """Stop local server and close client connections."""
        self.is_running = False

        for task in list(self._active_tasks):
            task.cancel()
        self._active_tasks.clear()

        if self._server:
            if hasattr(self._server, "close_clients"):
                with contextlib.suppress(Exception):
                    self._server.close_clients()
            if hasattr(self._server, "abort_clients"):
                with contextlib.suppress(Exception):
                    self._server.abort_clients()
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), timeout=0.5)
            self._server = None

        self._log("Локальный прокси-сервер остановлен.", LogLevel.INFO)

    def _handle_client_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Spawn independent task for each incoming client connection."""
        task = asyncio.create_task(self._process_client(reader, writer))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def _process_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        """Process an individual client connection."""
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            # Read request line and headers
            header_data = bytearray()
            while True:
                line = await client_reader.readline()
                if not line:
                    break
                header_data.extend(line)
                if line == b"\r\n" or line == b"\n":
                    break

            if not header_data:
                self._safe_close_writer(client_writer)
                return

            header_text = header_data.decode("utf-8", errors="replace")
            lines = header_text.splitlines()
            if not lines:
                self._safe_close_writer(client_writer)
                return

            first_line = lines[0]
            parts = first_line.split(" ")
            if len(parts) < 2:
                self._safe_close_writer(client_writer)
                return

            method = parts[0].upper()
            raw_target = parts[1]
            http_version = parts[2] if len(parts) > 2 else "HTTP/1.1"

            # Parse headers for Host
            headers: dict[str, str] = {}
            for h in lines[1:]:
                if ":" in h:
                    k, v = h.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            dest_host: str
            dest_port: int
            target_display: str

            if method == "CONNECT":
                # HTTPS Tunnel: target is host:port
                target_display = raw_target
                if ":" in raw_target:
                    host_part, port_str = raw_target.split(":", 1)
                    dest_host = host_part
                    try:
                        dest_port = int(port_str)
                    except ValueError:
                        dest_port = 443
                else:
                    dest_host = raw_target
                    dest_port = 443
            else:
                # HTTP request
                target_display = raw_target
                if raw_target.startswith(("http://", "https://")):
                    parsed = urlsplit(raw_target)
                    dest_host = parsed.hostname or "127.0.0.1"
                    dest_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                elif "host" in headers:
                    host_hdr = headers["host"]
                    if ":" in host_hdr:
                        h_part, p_part = host_hdr.split(":", 1)
                        dest_host = h_part
                        try:
                            dest_port = int(p_part)
                        except ValueError:
                            dest_port = 80
                    else:
                        dest_host = host_hdr
                        dest_port = 80
                else:
                    dest_host = "127.0.0.1"
                    dest_port = 80

            # Failover loop to establish connection to upstream
            upstream_reader: asyncio.StreamReader | None = None
            upstream_writer: asyncio.StreamWriter | None = None

            while self.is_running:
                current_proxy = self.rotation_manager.get_current_proxy()
                if not current_proxy:
                    self._handle_exhausted_pool(client_writer)
                    return

                try:
                    proxy_url = current_proxy.upstream_url
                    async_proxy = Proxy.from_url(proxy_url)
                    timeout_sec = max(0.5, self.config.connection_timeout_ms / 1000.0)

                    upstream_sock = await asyncio.wait_for(
                        async_proxy.connect(
                            dest_host=dest_host,
                            dest_port=dest_port,
                            timeout=timeout_sec,
                        ),
                        timeout=timeout_sec,
                    )
                    (
                        upstream_reader,
                        upstream_writer,
                    ) = await asyncio.open_connection(sock=upstream_sock)
                    break
                except Exception as exc:
                    reason = self._format_error(exc)
                    is_dead = self.rotation_manager.report_failure(current_proxy)
                    dead_note = " -> Dead" if is_dead else ""
                    if self.on_proxy_status_changed:
                        with contextlib.suppress(Exception):
                            self.on_proxy_status_changed(current_proxy)
                    if is_dead:
                        self._notify_pool_updated()

                    self._log(
                        f"Ошибка обращения к {target_display} через {current_proxy.host}:{current_proxy.port} | "
                        f"Причина: {reason}. Сбои: {current_proxy.fail_count}/{self.config.max_dead_attempts}{dead_note}",
                        LogLevel.ERROR,
                    )

                    if self.rotation_manager.is_empty():
                        self._handle_exhausted_pool(client_writer)
                        return

            if upstream_reader is None or upstream_writer is None:
                self._safe_close_writer(client_writer)
                return

            current_proxy = self.rotation_manager.get_current_proxy()
            proxy_repr = (
                f"{current_proxy.host}:{current_proxy.port}"
                if current_proxy
                else "unknown"
            )

            if method == "CONNECT":
                # Log established HTTPS tunnel
                self._log(
                    f"Туннель -> {dest_host}:{dest_port} через {proxy_repr} | "
                    f"Статус: 200 Connection Established",
                    LogLevel.INFO,
                )
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
            else:
                # Forward HTTP request headers
                # Rewrite target to relative path if absolute URL was sent
                if raw_target.startswith(("http://", "https://")):
                    parsed = urlsplit(raw_target)
                    path = parsed.path or "/"
                    if parsed.query:
                        path += f"?{parsed.query}"
                    rewritten_first_line = f"{method} {path} {http_version}\r\n"
                    req_bytes = rewritten_first_line.encode("utf-8") + header_data[len(first_line.encode("utf-8")) + 2 :]
                else:
                    req_bytes = bytes(header_data)

                upstream_writer.write(req_bytes)
                await upstream_writer.drain()

                # Read first line of response for logging
                status_line = await upstream_reader.readline()
                status_text = status_line.decode("utf-8", errors="replace").strip()
                status_code = "200"
                if " " in status_text:
                    parts = status_text.split(" ", 2)
                    if len(parts) >= 2:
                        status_code = parts[1]

                self._log(
                    f"Запрос -> {target_display} через {proxy_repr} | Ответ: HTTP {status_code}",
                    LogLevel.INFO,
                )
                client_writer.write(status_line)
                await client_writer.drain()

            # Bidirectional pipe
            await self._pipe_streams(
                client_reader,
                client_writer,
                upstream_reader,
                upstream_writer,
            )

        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug("Exception processing client connection: %s", exc)
        finally:
            self._safe_close_writer(client_writer)
            if upstream_writer is not None:
                self._safe_close_writer(upstream_writer)

    def _handle_exhausted_pool(self, client_writer: asyncio.StreamWriter) -> None:
        """Handle scenario when all proxies in rotation manager are dead."""
        self._log(
            "Все прокси мертвы. Локальный прокси-сервер остановлен.",
            LogLevel.ERROR,
        )
        if self.on_pool_exhausted:
            try:
                self.on_pool_exhausted()
            except Exception as e:
                logger.error("Error invoking on_pool_exhausted: %s", e)

        # Trigger auto-stop
        asyncio.create_task(self.stop())

        with contextlib.suppress(Exception):
            client_writer.write(
                b"HTTP/1.1 502 Bad Gateway\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 22\r\n\r\n"
                b"All proxies are dead\r\n"
            )
            # Safe async drain if possible
        self._safe_close_writer(client_writer)

    async def _pipe_streams(
        self,
        r1: asyncio.StreamReader,
        w1: asyncio.StreamWriter,
        r2: asyncio.StreamReader,
        w2: asyncio.StreamWriter,
    ) -> None:
        """Tunnel data between client and upstream in both directions."""
        async def _forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            finally:
                self._safe_close_writer(writer)

        await asyncio.gather(
            _forward(r1, w2),
            _forward(r2, w1),
            return_exceptions=True,
        )

    def _safe_close_writer(self, writer: asyncio.StreamWriter) -> None:
        """Safely close an asyncio stream writer."""
        with contextlib.suppress(Exception):
            writer.close()
