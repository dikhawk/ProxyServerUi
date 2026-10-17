"""Tests for new features: proxy deletion, server stop/start, counter updates, checking and GeoIP."""
import asyncio
import os
import socket
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtWidgets import QApplication

from src.data.config_repository import ConfigRepository
from src.data.proxy_repository import ProxyRepository
from src.domain.app_config import AppConfig
from src.domain.enums import AppState, ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem
from src.network.proxy_checker import _GEOIP_CACHE, ProxyCheckerService
from src.presentation.app_controller import AppController
from src.ui.main_window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_QAPP = QApplication.instance()
if not isinstance(_QAPP, QApplication):
    _QAPP = QApplication(["-platform", "offscreen"])


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_manual_delete_selected_proxy(tmp_path: Path):
    """Verify manual deletion of selected proxies from table and repository."""
    cfg_file = tmp_path / "config.json"
    csv_file = tmp_path / "proxies.csv"

    config_repo = ConfigRepository(cfg_file)
    proxy_repo = ProxyRepository(csv_file)

    p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)
    p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=8080)
    proxy_repo.add_or_merge([p1, p2])

    window = MainWindow()
    controller = AppController(window, config_repo, proxy_repo)
    controller.initialize()

    assert window.table_model.rowCount() == 2

    # Select first row
    selection_model = window.table_view.selectionModel()
    assert selection_model is not None
    first_row_idx = window.sort_proxy_model.index(0, 0)
    selection_model.select(first_row_idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    selected = window.get_selected_proxies()
    assert len(selected) == 1
    assert selected[0].host == "1.1.1.1"

    # Delete selected
    controller.on_delete_selected_clicked()

    assert proxy_repo.count() == 1
    assert window.table_model.rowCount() == 1
    assert proxy_repo.get_all()[0].host == "2.2.2.2"


def test_delete_dead_proxies(tmp_path: Path):
    """Verify deleting only DEAD proxies from repository and table."""
    cfg_file = tmp_path / "config.json"
    csv_file = tmp_path / "proxies.csv"

    config_repo = ConfigRepository(cfg_file)
    proxy_repo = ProxyRepository(csv_file)

    p_alive = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=80, status=ProxyStatus.ACTIVE)
    p_dead1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=80, status=ProxyStatus.DEAD)
    p_dead2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="3.3.3.3", port=80, status=ProxyStatus.DEAD)
    p_untested = ProxyItem(protocol=ProxyProtocol.HTTP, host="4.4.4.4", port=80, status=ProxyStatus.UNTESTED)

    proxy_repo.add_or_merge([p_alive, p_dead1, p_dead2, p_untested])

    window = MainWindow()
    controller = AppController(window, config_repo, proxy_repo)
    controller.initialize()

    assert window.table_model.rowCount() == 4

    # Click delete dead
    controller.on_delete_dead_clicked()

    assert proxy_repo.count() == 2
    assert window.table_model.rowCount() == 2
    remaining_hosts = {p.host for p in proxy_repo.get_all()}
    assert remaining_hosts == {"1.1.1.1", "4.4.4.4"}


def test_max_dead_attempts_display_update(tmp_path: Path):
    """Verify that updating failure limit updates table model display."""
    cfg_file = tmp_path / "config.json"
    csv_file = tmp_path / "proxies.csv"

    config_repo = ConfigRepository(cfg_file)
    config = AppConfig(max_dead_attempts=5)
    config_repo.save(config)

    proxy_repo = ProxyRepository(csv_file)
    p = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=80, fail_count=2)
    proxy_repo.add_or_merge([p])

    window = MainWindow()
    controller = AppController(window, config_repo, proxy_repo)
    controller.initialize()

    # Initial display check: 2/5
    col_idx = window.table_model.index(0, 7)
    assert window.table_model.data(col_idx, Qt.ItemDataRole.DisplayRole) == "2/5"

    # Now change config max_dead_attempts to 10
    new_cfg = AppConfig(max_dead_attempts=10)
    controller.config = new_cfg
    controller.config_repo.save(new_cfg)
    window.table_model.set_max_attempts(new_cfg.max_dead_attempts)

    # Display check: now 2/10
    assert window.table_model.data(col_idx, Qt.ItemDataRole.DisplayRole) == "2/10"


@pytest.mark.anyio
async def test_server_start_stop_and_realtime_counter(tmp_path: Path):
    """Verify server starts, updates status label with active count, and cleanly stops."""
    port = _get_free_port()
    cfg_file = tmp_path / "config.json"
    csv_file = tmp_path / "proxies.csv"

    config_repo = ConfigRepository(cfg_file)
    config = AppConfig(local_port=port, max_dead_attempts=2)
    config_repo.save(config)

    proxy_repo = ProxyRepository(csv_file)
    p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59111)
    p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59112)
    proxy_repo.add_or_merge([p1, p2])

    window = MainWindow()
    controller = AppController(window, config_repo, proxy_repo)
    controller.initialize()

    # Start server
    controller.on_toggle_server_clicked()
    await asyncio.sleep(0.1)

    assert controller.state == AppState.RUNNING
    assert "активно: 2/2" in window.control_panel.lbl_status.text()
    assert "Остановить" in window.btn_toggle_server.text()

    # Simulate failure of p1 reaching dead threshold
    assert controller.local_server is not None
    assert controller.rotation_manager is not None
    controller.rotation_manager.report_failure(p1)
    controller.rotation_manager.report_failure(p1)
    assert p1.status == ProxyStatus.DEAD
    controller.local_server._notify_pool_updated()

    # Real-time counter should update to 1/2
    assert "активно: 1/2" in window.control_panel.lbl_status.text()

    # Stop server
    controller.on_toggle_server_clicked()
    await asyncio.sleep(0.1)

    assert controller.state == AppState.IDLE
    assert controller.local_server is None
    assert "Остановлен" in window.control_panel.lbl_status.text()
    assert "Запустить" in window.btn_toggle_server.text()


@pytest.mark.anyio
async def test_single_check_success_and_failure():
    """Verify single-run check marks proxies ACTIVE on success and DEAD on failure."""
    config = AppConfig(
        connection_timeout_ms=100,
        response_timeout_ms=100,
        max_dead_attempts=3,
        test_urls=["http://127.0.0.1:54321/test"],
    )
    checker = ProxyCheckerService(config=config)

    # Failed proxy
    dead_proxy = ProxyItem(protocol=ProxyProtocol.HTTP, host="127.0.0.1", port=59999)
    res_fail = await checker.check_item(dead_proxy, single_check=True)
    assert not res_fail
    assert dead_proxy.status == ProxyStatus.DEAD
    assert dead_proxy.fail_count == 3
    assert dead_proxy.url_status == "FAIL"

    # Successful proxy mocked
    good_proxy = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.2.3.4", port=8080)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, text="OK")

        res_ok = await checker.check_item(good_proxy, single_check=True)
        assert res_ok
        assert good_proxy.status == ProxyStatus.ACTIVE
        assert good_proxy.fail_count == 0
        assert good_proxy.url_status == "HTTP 200"


@pytest.mark.anyio
async def test_stop_check_process(tmp_path: Path):
    """Verify stopping an active check transitions state back to IDLE cleanly."""
    cfg_file = tmp_path / "config.json"
    csv_file = tmp_path / "proxies.csv"

    config_repo = ConfigRepository(cfg_file)
    proxy_repo = ProxyRepository(csv_file)
    for i in range(5):
        proxy_repo.add_or_merge([ProxyItem(protocol=ProxyProtocol.HTTP, host=f"10.0.0.{i}", port=8080)])

    window = MainWindow()
    controller = AppController(window, config_repo, proxy_repo)
    controller.initialize()

    # Start check
    controller.on_check_clicked()
    assert controller.state == AppState.CHECKING
    assert window.control_panel.btn_check.text() == "⏹️ Стоп"

    # Stop check
    controller.on_check_clicked()
    await asyncio.sleep(0.05)

    assert controller.state == AppState.IDLE
    assert window.control_panel.btn_check.text() == "⚡ Проверить"


@pytest.mark.anyio
async def test_geoip_resolution_and_caching():
    """Verify GeoIP country resolution and in-memory caching."""
    _GEOIP_CACHE.clear()
    config = AppConfig()
    checker = ProxyCheckerService(config=config)

    # Fake direct client responses
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json={"country": "DE"})

        country = await checker._fetch_geoip("88.99.100.101")
        assert country == "DE"
        assert _GEOIP_CACHE.get("88.99.100.101") == "DE"

        # Subsequent call should return cached value without network request
        mock_get.reset_mock()
        cached_country = await checker._fetch_geoip("88.99.100.101")
        assert cached_country == "DE"
        mock_get.assert_not_called()
