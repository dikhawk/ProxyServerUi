"""Enums for the domain layer."""
from enum import Enum


class ProxyProtocol(str, Enum):
    """Supported proxy protocols."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"


class ProxyStatus(str, Enum):
    """Proxy health/activity status."""
    ACTIVE = "Active"
    DEAD = "Dead"
    CHECKING = "Checking"
    UNTESTED = "Untested"


class LogLevel(str, Enum):
    """Log level for message coloring in the UI console."""
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"


class AppState(str, Enum):
    """Application running state."""
    IDLE = "Idle"
    RUNNING = "Running"
