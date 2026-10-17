"""Proxy item domain model."""
from dataclasses import dataclass, field
from datetime import datetime

from src.domain.enums import ProxyProtocol, ProxyStatus


@dataclass
class ProxyItem:
    """Domain entity representing a single proxy node and its state."""

    protocol: ProxyProtocol
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    location: str = "Unknown"
    status: ProxyStatus = ProxyStatus.UNTESTED
    ping: int | None = None
    url_status: str = "-"
    added_at: str = field(default_factory=lambda: datetime.now().strftime("%d.%m %H:%M"))
    fail_count: int = 0
    dead_since: str = ""

    @property
    def unique_key(self) -> str:
        """Returns unique identifier in format: protocol://host:port."""
        return f"{self.protocol.value}://{self.host}:{self.port}"

    @property
    def upstream_url(self) -> str:
        """Returns upstream URL with authentication if present."""
        if self.username and self.password:
            return f"{self.protocol.value}://{self.username}:{self.password}@{self.host}:{self.port}"
        if self.username:
            return f"{self.protocol.value}://{self.username}@{self.host}:{self.port}"
        return f"{self.protocol.value}://{self.host}:{self.port}"

    def register_success(
        self, ping_ms: int, url_status: str, location: str | None = None
    ) -> None:
        """Register successful check: resets fail stats and marks active."""
        self.fail_count = 0
        self.dead_since = ""
        self.status = ProxyStatus.ACTIVE
        self.ping = ping_ms
        self.url_status = url_status
        if location and location.strip():
            self.location = location.strip()

    def register_failure(self, max_attempts: int, url_status: str = "FAIL") -> bool:
        """
        Register failure: increments fail_count.
        If fail_count reaches 1, records dead_since timestamp.
        If fail_count reaches max_attempts, sets DEAD status and returns True.
        """
        self.fail_count += 1
        self.url_status = url_status
        if self.fail_count == 1 and not self.dead_since:
            self.dead_since = datetime.now().strftime("%d.%m %H:%M")

        if self.fail_count >= max_attempts:
            self.status = ProxyStatus.DEAD
            return True
        return False

    def mark_dead(self, max_attempts: int, reason: str = "FAIL") -> None:
        """Mark proxy as DEAD with max fail count, dead_since timestamp and url status."""
        self.status = ProxyStatus.DEAD
        self.fail_count = max_attempts
        self.url_status = reason
        self.ping = None
        if not self.dead_since:
            self.dead_since = datetime.now().strftime("%d.%m %H:%M")

    def reset_statistics(self) -> None:
        """Reset failures, clear dead_since, and return to ACTIVE status."""
        self.fail_count = 0
        self.dead_since = ""
        self.status = ProxyStatus.ACTIVE
