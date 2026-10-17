"""Proxy parser for raw strings in various formats."""
from urllib.parse import unquote, urlsplit

from src.domain.enums import ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem


class ProxyParser:
    """Parses raw proxy strings into ProxyItem domain objects."""

    @staticmethod
    def parse_line(
        raw_line: str,
        default_protocol: ProxyProtocol = ProxyProtocol.HTTP,
    ) -> ProxyItem | None:
        """
        Parse a single proxy string into a ProxyItem.

        Supported formats:
        - IP:Port
        - IP:Port:User:Pass
        - protocol://IP:Port
        - protocol://User:Pass@IP:Port
        - User:Pass@IP:Port
        """
        line = raw_line.strip()
        if not line or line.startswith("#"):
            return None

        # Format with explicit protocol: protocol://...
        if "://" in line:
            return ProxyParser._parse_url_format(line)

        # Format without scheme: User:Pass@IP:Port
        if "@" in line:
            auth_part, host_port_part = line.split("@", 1)
            creds = auth_part.split(":", 1)
            username = creds[0] if creds else None
            password = creds[1] if len(creds) > 1 else None
            return ProxyParser._parse_host_port(
                host_port_part,
                default_protocol,
                username=username,
                password=password,
            )

        # Colon-separated: IP:Port or IP:Port:User:Pass
        parts = line.split(":")
        if len(parts) == 2:
            return ProxyParser._parse_host_port(line, default_protocol)
        if len(parts) == 4:
            host, port_str, username, password = parts
            try:
                port = int(port_str)
            except ValueError:
                return None
            if not (1 <= port <= 65535) or not host.strip():
                return None
            return ProxyItem(
                protocol=default_protocol,
                host=host.strip(),
                port=port,
                username=username.strip() or None,
                password=password.strip() or None,
                status=ProxyStatus.UNTESTED,
            )

        return None

    @staticmethod
    def _parse_url_format(raw_url: str) -> ProxyItem | None:
        """Parse URL formatted string like socks5://user:pass@host:port."""
        try:
            parsed = urlsplit(raw_url)
        except ValueError:
            return None

        scheme = (parsed.scheme or "").lower()
        try:
            protocol = ProxyProtocol(scheme)
        except ValueError:
            return None

        host = parsed.hostname
        port = parsed.port
        if not host or not port or not (1 <= port <= 65535):
            return None

        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None

        return ProxyItem(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            status=ProxyStatus.UNTESTED,
        )

    @staticmethod
    def _parse_host_port(
        host_port: str,
        protocol: ProxyProtocol,
        username: str | None = None,
        password: str | None = None,
    ) -> ProxyItem | None:
        """Parse host:port substring."""
        parts = host_port.strip().split(":")
        if len(parts) != 2:
            return None
        host, port_str = parts[0].strip(), parts[1].strip()
        try:
            port = int(port_str)
        except ValueError:
            return None

        if not (1 <= port <= 65535) or not host:
            return None

        return ProxyItem(
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
            status=ProxyStatus.UNTESTED,
        )

    @classmethod
    def parse_text(
        cls,
        text: str,
        default_protocol: ProxyProtocol = ProxyProtocol.HTTP,
    ) -> list[ProxyItem]:
        """Parse multiline text containing proxy entries."""
        items: list[ProxyItem] = []
        for line in text.splitlines():
            item = cls.parse_line(line, default_protocol)
            if item is not None:
                items.append(item)
        return items
