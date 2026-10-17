"""Application configuration domain model."""
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class AppConfig:
    """Application configuration and validation logic."""

    proxy_sources: list[str] = field(default_factory=list)
    local_port: int = 8080
    preferred_countries: list[str] = field(default_factory=list)
    test_urls: list[str] = field(
        default_factory=lambda: [
            "https://gemini.google.com/app",
            "https://httpbin.org/ip",
        ]
    )
    connection_timeout_ms: int = 3000
    response_timeout_ms: int = 5000
    max_dead_attempts: int = 5

    def validate(self) -> tuple[bool, str]:
        """
        Validate configuration parameters.
        Returns (True, "") on success, or (False, error_message) on failure.
        """
        if not (1 <= self.local_port <= 65535):
            return False, f"Local port must be between 1 and 65535 (got {self.local_port})"

        if self.connection_timeout_ms <= 0:
            return (
                False,
                f"Connection timeout must be positive (got {self.connection_timeout_ms} ms)",
            )

        if self.response_timeout_ms <= 0:
            return (
                False,
                f"Response timeout must be positive (got {self.response_timeout_ms} ms)",
            )

        if self.max_dead_attempts < 1:
            return (
                False,
                f"Max dead attempts must be >= 1 (got {self.max_dead_attempts})",
            )

        if not self.test_urls:
            return False, "At least one test URL must be specified"

        for url in self.test_urls:
            trimmed = url.strip()
            if not trimmed:
                return False, "Test URL cannot be empty"
            parsed = urlparse(trimmed)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return (
                    False,
                    f"Invalid test URL '{url}': must include http/https scheme and a valid domain",
                )

        return True, ""

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Instantiate config from dictionary with fallback defaults."""

        def _safe_int(val: Any, default: int) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        return cls(
            proxy_sources=list(data.get("proxy_sources", [])),
            local_port=_safe_int(data.get("local_port"), 8080),
            preferred_countries=list(data.get("preferred_countries", [])),
            test_urls=list(
                data.get(
                    "test_urls",
                    [
                        "https://gemini.google.com/app",
                        "https://httpbin.org/ip",
                    ],
                )
            ),
            connection_timeout_ms=_safe_int(data.get("connection_timeout_ms"), 3000),
            response_timeout_ms=_safe_int(data.get("response_timeout_ms"), 5000),
            max_dead_attempts=_safe_int(data.get("max_dead_attempts"), 5),
        )
