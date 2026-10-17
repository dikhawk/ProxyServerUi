"""Unit tests for the domain layer (Stage 1)."""
from src.domain.app_config import AppConfig
from src.domain.enums import AppState, LogLevel, ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem


def test_enums_values():
    """Verify that all enum values match specification."""
    assert ProxyProtocol.HTTP.value == "http"
    assert ProxyProtocol.HTTPS.value == "https"
    assert ProxyProtocol.SOCKS4.value == "socks4"
    assert ProxyProtocol.SOCKS5.value == "socks5"

    assert ProxyStatus.ACTIVE.value == "Active"
    assert ProxyStatus.DEAD.value == "Dead"
    assert ProxyStatus.CHECKING.value == "Checking"
    assert ProxyStatus.UNTESTED.value == "Untested"

    assert LogLevel.INFO.value == "info"
    assert LogLevel.SUCCESS.value == "success"
    assert LogLevel.ERROR.value == "error"

    assert AppState.IDLE.value == "Idle"
    assert AppState.RUNNING.value == "Running"


def test_proxy_item_keys_and_urls():
    """Verify unique_key and upstream_url generation with and without auth."""
    item_no_auth = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="192.168.1.1",
        port=8080,
    )
    assert item_no_auth.unique_key == "http://192.168.1.1:8080"
    assert item_no_auth.upstream_url == "http://192.168.1.1:8080"

    item_auth = ProxyItem(
        protocol=ProxyProtocol.SOCKS5,
        host="10.0.0.1",
        port=1080,
        username="user1",
        password="test_password",  # noqa: S106
    )
    assert item_auth.unique_key == "socks5://10.0.0.1:1080"
    assert item_auth.upstream_url == "socks5://user1:test_password@10.0.0.1:1080"


def test_proxy_item_failure_and_dead_transition():
    """
    Verify that 5 consecutive failures set status to DEAD,
    and reset_statistics returns status to ACTIVE with 0 failures.
    """
    item = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="127.0.0.1",
        port=8888,
    )
    assert item.status == ProxyStatus.UNTESTED
    assert item.fail_count == 0
    assert item.dead_since == ""

    # 1st failure: sets dead_since, returns False
    is_dead = item.register_failure(max_attempts=5)
    assert not is_dead
    assert item.fail_count == 1
    assert item.dead_since != ""
    assert item.status == ProxyStatus.UNTESTED
    first_dead_since = item.dead_since

    # 2nd to 4th failures: fail_count increments, dead_since preserved
    for expected_count in range(2, 5):
        is_dead = item.register_failure(max_attempts=5)
        assert not is_dead
        assert item.fail_count == expected_count
        assert item.dead_since == first_dead_since
        assert item.status == ProxyStatus.UNTESTED

    # 5th failure: limit reached, transitions to DEAD and returns True
    is_dead = item.register_failure(max_attempts=5)
    assert is_dead
    assert item.fail_count == 5
    assert item.status == ProxyStatus.DEAD

    # Reset statistics: fail_count and dead_since cleared, status -> ACTIVE
    item.reset_statistics()
    assert item.fail_count == 0
    assert item.dead_since == ""
    assert item.status == ProxyStatus.ACTIVE


def test_proxy_item_register_success():
    """Verify that register_success updates ping, location, and resets failure tracking."""
    item = ProxyItem(
        protocol=ProxyProtocol.SOCKS4,
        host="1.2.3.4",
        port=1080,
    )
    item.register_failure(max_attempts=3)
    assert item.fail_count == 1
    assert item.dead_since != ""

    item.register_success(ping_ms=120, url_status="HTTP 200", location="DE")
    assert item.fail_count == 0
    assert item.dead_since == ""
    assert item.status == ProxyStatus.ACTIVE
    assert item.ping == 120
    assert item.url_status == "HTTP 200"
    assert item.location == "DE"


def test_app_config_validation():
    """Verify AppConfig validation logic."""
    valid_config = AppConfig(
        proxy_sources=["https://example.com/proxies.txt"],
        local_port=8080,
        preferred_countries=["US", "DE"],
        test_urls=["https://gemini.google.com/app", "https://httpbin.org/ip"],
        connection_timeout_ms=3000,
        response_timeout_ms=5000,
        max_dead_attempts=5,
    )
    ok, err = valid_config.validate()
    assert ok
    assert err == ""

    # Invalid port
    bad_port = AppConfig(local_port=0)
    ok, err = bad_port.validate()
    assert not ok
    assert "port" in err.lower()

    # Invalid timeout
    bad_timeout = AppConfig(connection_timeout_ms=0)
    ok, err = bad_timeout.validate()
    assert not ok
    assert "timeout" in err.lower()

    # Invalid max attempts
    bad_attempts = AppConfig(max_dead_attempts=0)
    ok, err = bad_attempts.validate()
    assert not ok
    assert "attempts" in err.lower()

    # Empty test URLs
    empty_urls = AppConfig(test_urls=[])
    ok, err = empty_urls.validate()
    assert not ok
    assert "test url" in err.lower()

    # Invalid URL scheme
    bad_scheme = AppConfig(test_urls=["ftp://invalid-scheme.com"])
    ok, err = bad_scheme.validate()
    assert not ok
    assert "scheme" in err.lower()


def test_app_config_serialization():
    """Verify AppConfig to_dict and from_dict methods."""
    config = AppConfig(
        local_port=9090,
        max_dead_attempts=10,
        preferred_countries=["FR"],
    )
    data = config.to_dict()
    assert isinstance(data, dict)
    assert data["local_port"] == 9090
    assert data["max_dead_attempts"] == 10
    assert data["preferred_countries"] == ["FR"]

    loaded = AppConfig.from_dict(data)
    assert loaded.local_port == 9090
    assert loaded.max_dead_attempts == 10
    assert loaded.preferred_countries == ["FR"]
