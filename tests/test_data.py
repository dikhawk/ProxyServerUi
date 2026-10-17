"""Unit tests for the data layer (Stage 2)."""
from pathlib import Path

from src.data.config_repository import ConfigRepository
from src.data.proxy_parser import ProxyParser
from src.data.proxy_repository import ProxyRepository
from src.domain.enums import ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem


def test_proxy_parser_ip_port():
    """Verify parsing of simple IP:Port strings."""
    item = ProxyParser.parse_line("192.168.1.100:8080")
    assert item is not None
    assert item.protocol == ProxyProtocol.HTTP
    assert item.host == "192.168.1.100"
    assert item.port == 8080
    assert item.username is None
    assert item.password is None

    # Custom default protocol
    item_socks = ProxyParser.parse_line("10.0.0.1:1080", default_protocol=ProxyProtocol.SOCKS5)
    assert item_socks is not None
    assert item_socks.protocol == ProxyProtocol.SOCKS5
    assert item_socks.port == 1080


def test_proxy_parser_ip_port_user_pass():
    """Verify parsing of IP:Port:User:Pass format."""
    item = ProxyParser.parse_line("172.16.0.5:3128:testuser:testpass")
    assert item is not None
    assert item.protocol == ProxyProtocol.HTTP
    assert item.host == "172.16.0.5"
    assert item.port == 3128
    assert item.username == "testuser"
    assert item.password == "testpass"  # noqa: S105


def test_proxy_parser_url_formats():
    """Verify parsing of URL schemes with and without credentials."""
    item1 = ProxyParser.parse_line("socks5://1.2.3.4:1080")
    assert item1 is not None
    assert item1.protocol == ProxyProtocol.SOCKS5
    assert item1.host == "1.2.3.4"
    assert item1.port == 1080

    item2 = ProxyParser.parse_line("https://usr:pwd@8.8.8.8:8443")
    assert item2 is not None
    assert item2.protocol == ProxyProtocol.HTTPS
    assert item2.host == "8.8.8.8"
    assert item2.port == 8443
    assert item2.username == "usr"
    assert item2.password == "pwd"  # noqa: S105

    item3 = ProxyParser.parse_line("myuser:mypass@10.0.0.2:8000")
    assert item3 is not None
    assert item3.protocol == ProxyProtocol.HTTP
    assert item3.host == "10.0.0.2"
    assert item3.port == 8000
    assert item3.username == "myuser"
    assert item3.password == "mypass"  # noqa: S105


def test_proxy_parser_invalid_and_comments():
    """Verify parser ignores comments/empty lines and rejects invalid entries."""
    assert ProxyParser.parse_line("") is None
    assert ProxyParser.parse_line("   ") is None
    assert ProxyParser.parse_line("# comment line") is None
    assert ProxyParser.parse_line("not-a-proxy") is None
    assert ProxyParser.parse_line("1.2.3.4:999999") is None  # invalid port
    assert ProxyParser.parse_line("1.2.3.4:0") is None  # invalid port
    assert ProxyParser.parse_line("ftp://1.2.3.4:21") is None  # unsupported scheme


def test_proxy_parser_multiline_text():
    """Verify bulk parsing of multiline text."""
    raw_data = """
    # Proxy list source
    192.168.1.1:8080
    socks5://admin:pwd@10.0.0.1:1080

    invalid_line_here
    socks4://10.0.0.2:1080
    """
    items = ProxyParser.parse_text(raw_data)
    assert len(items) == 3
    assert items[0].unique_key == "http://192.168.1.1:8080"
    assert items[1].unique_key == "socks5://10.0.0.1:1080"
    assert items[2].unique_key == "socks4://10.0.0.2:1080"


def test_config_repository(tmp_path: Path):
    """Verify ConfigRepository loads, creates default, and persists changes."""
    cfg_file = tmp_path / "config.json"
    repo = ConfigRepository(cfg_file)

    # 1. Non-existent file -> creates default
    cfg = repo.load()
    assert cfg_file.exists()
    assert cfg.local_port == 8080

    # 2. Modify and save
    cfg.local_port = 9090
    cfg.preferred_countries = ["DE", "US"]
    repo.save(cfg)

    # 3. Reload
    reloaded = repo.load()
    assert reloaded.local_port == 9090
    assert reloaded.preferred_countries == ["DE", "US"]

    # 4. Corrupted file -> falls back to default
    cfg_file.write_text("{invalid json", encoding="utf-8")
    fallback = repo.load()
    assert fallback.local_port == 8080


def test_proxy_repository_csv_crud(tmp_path: Path):
    """Verify CSV load, save, and field round-trip."""
    csv_file = tmp_path / "proxies.csv"
    repo = ProxyRepository(csv_file)
    repo.load()
    assert repo.count() == 0

    item1 = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="192.168.1.1",
        port=8080,
        username="u1",
        password="p1",  # noqa: S106
        location="US",
        status=ProxyStatus.ACTIVE,
        ping=45,
        url_status="HTTP 200",
        added_at="12.10 10:00",
        fail_count=1,
        dead_since="12.10 09:00",
    )
    item2 = ProxyItem(
        protocol=ProxyProtocol.SOCKS5,
        host="10.0.0.2",
        port=1080,
        location="DE",
        status=ProxyStatus.UNTESTED,
    )

    added = repo.add_or_merge([item1, item2])
    assert added == 2
    assert repo.count() == 2

    # Verify reloading from CSV
    repo2 = ProxyRepository(csv_file)
    repo2.load()
    assert repo2.count() == 2

    loaded_item1 = repo2.get_by_key("http://192.168.1.1:8080")
    assert loaded_item1 is not None
    assert loaded_item1.username == "u1"
    assert loaded_item1.password == "p1"  # noqa: S105
    assert loaded_item1.location == "US"
    assert loaded_item1.status == ProxyStatus.ACTIVE
    assert loaded_item1.ping == 45
    assert loaded_item1.url_status == "HTTP 200"
    assert loaded_item1.added_at == "12.10 10:00"
    assert loaded_item1.fail_count == 1
    assert loaded_item1.dead_since == "12.10 09:00"


def test_proxy_repository_deduplication(tmp_path: Path):
    """Verify deduplication preserves existing statistics and doesn't overwrite."""
    csv_file = tmp_path / "proxies.csv"
    repo = ProxyRepository(csv_file)

    original_item = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="1.1.1.1",
        port=80,
        status=ProxyStatus.ACTIVE,
        ping=35,
        location="NL",
        fail_count=2,
    )
    repo.add_or_merge([original_item])

    duplicate_candidate = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="1.1.1.1",
        port=80,
        status=ProxyStatus.UNTESTED,
        ping=None,
        location="Unknown",
        fail_count=0,
    )
    new_candidate = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="2.2.2.2",
        port=80,
    )

    added = repo.add_or_merge([duplicate_candidate, new_candidate])
    assert added == 1
    assert repo.count() == 2

    existing = repo.get_by_key("http://1.1.1.1:80")
    assert existing is not None
    assert existing.status == ProxyStatus.ACTIVE
    assert existing.ping == 35
    assert existing.location == "NL"
    assert existing.fail_count == 2


def test_proxy_repository_clear_all(tmp_path: Path):
    """Verify clear_all empties repository and resets CSV to headers."""
    csv_file = tmp_path / "proxies.csv"
    repo = ProxyRepository(csv_file)
    item = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=80)
    repo.add_or_merge([item])
    assert repo.count() == 1

    repo.clear_all()
    assert repo.count() == 0

    # Verify CSV file has only header line
    lines = csv_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "protocol,host,port" in lines[0]


def test_proxy_repository_protocols_countries_and_pool(tmp_path: Path):
    """Verify available protocols, countries, and working pool filtering."""
    csv_file = tmp_path / "proxies.csv"
    repo = ProxyRepository(csv_file)

    p1 = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="1.1.1.1",
        port=80,
        location="US",
        status=ProxyStatus.ACTIVE,
    )
    p2 = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="2.2.2.2",
        port=80,
        location="DE",
        status=ProxyStatus.UNTESTED,
    )
    p3 = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="3.3.3.3",
        port=80,
        location="DE",
        status=ProxyStatus.DEAD,  # Dead should NOT be in working pool
    )
    p4 = ProxyItem(
        protocol=ProxyProtocol.SOCKS5,
        host="4.4.4.4",
        port=1080,
        location="US",
        status=ProxyStatus.ACTIVE,
    )

    repo.add_or_merge([p1, p2, p3, p4])

    # Protocols
    protocols = repo.get_available_protocols()
    assert protocols == ["http", "socks5"]

    # Countries
    countries = repo.get_available_countries()
    assert countries == ["DE", "US"]

    # Working pool for HTTP with no country filter -> p1, p2 (p3 is Dead)
    pool_all = repo.get_working_pool(protocol="http", countries=[])
    assert len(pool_all) == 2
    assert {p.host for p in pool_all} == {"1.1.1.1", "2.2.2.2"}

    # Working pool for HTTP filtered by DE -> only p2
    pool_de = repo.get_working_pool(protocol="http", countries=["DE"])
    assert len(pool_de) == 1
    assert pool_de[0].host == "2.2.2.2"

    # Working pool for SOCKS5 -> only p4
    pool_socks5 = repo.get_working_pool(protocol="socks5", countries=[])
    assert len(pool_socks5) == 1
    assert pool_socks5[0].host == "4.4.4.4"
