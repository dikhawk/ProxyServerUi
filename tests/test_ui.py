"""Unit tests for UI layer models, widgets, and controller (Stage 5)."""
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.data.config_repository import ConfigRepository
from src.data.proxy_repository import ProxyRepository
from src.domain.app_config import AppConfig
from src.domain.enums import AppState, LogLevel, ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem
from src.presentation.app_controller import AppController
from src.ui.main_window import MainWindow
from src.ui.models.proxy_table_model import ProxyTableModel
from src.ui.models.sort_proxy_model import ProxySortFilterModel
from src.ui.settings_dialog import SettingsDialog
from src.ui.widgets.control_panel import ControlPanelWidget
from src.ui.widgets.log_console import LogConsoleWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Module-level permanent QApplication reference to prevent GC during test runs
_QAPP = QApplication.instance()
if not isinstance(_QAPP, QApplication):
    _QAPP = QApplication(["-platform", "offscreen"])


def _get_qapp() -> QApplication:
    """Return the global offscreen QApplication instance."""
    assert isinstance(_QAPP, QApplication)
    return _QAPP


def test_proxy_table_model():
    """Verify table model rows, columns, display text, and sorting user roles."""
    _get_qapp()

    p1 = ProxyItem(
        protocol=ProxyProtocol.HTTP,
        host="1.1.1.1",
        port=8080,
        location="US",
        status=ProxyStatus.ACTIVE,
        ping=50,
        url_status="HTTP 200",
        added_at="10.10 12:00",
        fail_count=1,
    )
    p2 = ProxyItem(
        protocol=ProxyProtocol.SOCKS5,
        host="2.2.2.2",
        port=1080,
        location="DE",
        status=ProxyStatus.DEAD,
        ping=None,
        url_status="FAIL",
        fail_count=5,
        dead_since="10.10 13:00",
    )

    model = ProxyTableModel([p1, p2], max_attempts=5)
    assert model.rowCount() == 2
    assert model.columnCount() == 9

    # Headers
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Тип"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Адрес"
    assert model.headerData(4, Qt.Orientation.Horizontal) == "Пинг"

    # DisplayRole
    idx_p1_type = model.index(0, 0)
    assert model.data(idx_p1_type, Qt.ItemDataRole.DisplayRole) == "http"

    idx_p1_addr = model.index(0, 1)
    assert model.data(idx_p1_addr, Qt.ItemDataRole.DisplayRole) == "1.1.1.1:8080"

    idx_p1_ping = model.index(0, 4)
    assert model.data(idx_p1_ping, Qt.ItemDataRole.DisplayRole) == "50ms"

    idx_p2_ping = model.index(1, 4)
    assert model.data(idx_p2_ping, Qt.ItemDataRole.DisplayRole) == "-"

    # UserRole for numeric sorting
    assert model.data(idx_p1_ping, Qt.ItemDataRole.UserRole) == 50
    assert model.data(idx_p2_ping, Qt.ItemDataRole.UserRole) == 999999

    idx_p1_fails = model.index(0, 7)
    idx_p2_fails = model.index(1, 7)
    assert model.data(idx_p1_fails, Qt.ItemDataRole.UserRole) == 1
    assert model.data(idx_p2_fails, Qt.ItemDataRole.UserRole) == 5

    # update_proxy
    p1.ping = 40
    model.update_proxy(p1)
    assert model.data(idx_p1_ping, Qt.ItemDataRole.DisplayRole) == "40ms"


def test_sort_filter_model():
    """Verify numeric sorting in ProxySortFilterModel."""
    _get_qapp()

    p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=80, ping=150, fail_count=2)
    p2 = ProxyItem(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=80, ping=45, fail_count=1)

    table_model = ProxyTableModel([p1, p2])
    sort_model = ProxySortFilterModel()
    sort_model.setSourceModel(table_model)

    # Sort ascending by Ping (column 4)
    sort_model.sort(4, Qt.SortOrder.AscendingOrder)
    # First row should now be p2 (ping 45 < 150)
    first_ping_data = sort_model.data(sort_model.index(0, 4), Qt.ItemDataRole.DisplayRole)
    assert first_ping_data == "45ms"

    # Sort descending by Ping (column 4)
    sort_model.sort(4, Qt.SortOrder.DescendingOrder)
    first_ping_desc = sort_model.data(sort_model.index(0, 4), Qt.ItemDataRole.DisplayRole)
    assert first_ping_desc == "150ms"


def test_control_panel_state_transitions():
    """Verify ControlPanelWidget button enabling/disabling based on AppState."""
    _get_qapp()
    panel = ControlPanelWidget()

    # Initial IDLE
    panel.set_app_state(AppState.IDLE)
    assert panel.btn_load_file.isEnabled()
    assert panel.btn_refresh.isEnabled()
    assert panel.btn_check.isEnabled()
    assert panel.btn_reset_stats.isEnabled()
    assert panel.btn_clear.isEnabled()
    assert panel.btn_settings.isEnabled()
    assert "Остановлен" in panel.lbl_status.text()

    # Switch to RUNNING
    panel.set_app_state(AppState.RUNNING)
    assert not panel.btn_load_file.isEnabled()
    assert not panel.btn_refresh.isEnabled()
    assert not panel.btn_check.isEnabled()
    assert not panel.btn_reset_stats.isEnabled()
    assert not panel.btn_clear.isEnabled()
    assert not panel.btn_settings.isEnabled()
    assert "Работает" in panel.lbl_status.text()


def test_log_console_widget():
    """Verify LogConsoleWidget appends colorized HTML messages and clears."""
    _get_qapp()
    console = LogConsoleWidget()

    console.append_log("Standard info event", LogLevel.INFO)
    console.append_log("Proxy server started", LogLevel.SUCCESS)
    console.append_log("Connection failed", LogLevel.ERROR)

    html_content = console.text_edit.toHtml()
    assert "Standard info event" in html_content
    assert "#2ecc71" in html_content  # Green color
    assert "#e74c3c" in html_content  # Red color

    console.clear_logs()
    assert console.text_edit.toPlainText().strip() == ""


def test_settings_dialog():
    """Verify SettingsDialog loads config values into inputs and retrieves AppConfig."""
    _get_qapp()

    config = AppConfig(
        proxy_sources=["https://src1.txt", "https://src2.txt"],
        local_port=8888,
        preferred_countries=["US", "DE"],
        test_urls=["https://test1.org", "https://test2.org"],
        connection_timeout_ms=2500,
        response_timeout_ms=4500,
        max_dead_attempts=7,
    )

    dialog = SettingsDialog(
        current_config=config,
        available_countries=["US", "DE", "FR"],
    )

    # Verify populated inputs
    assert dialog.spin_port.value() == 8888
    assert dialog.spin_conn_timeout.value() == 2500
    assert dialog.spin_resp_timeout.value() == 4500
    assert dialog.spin_max_attempts.value() == 7
    assert "src1.txt" in dialog.txt_sources.toPlainText()

    # Get updated config
    updated = dialog.get_config()
    assert updated.local_port == 8888
    assert updated.max_dead_attempts == 7
    assert "US" in updated.preferred_countries
    assert "DE" in updated.preferred_countries


def test_app_controller_initialization(tmp_path: Path):
    """Verify AppController initializes repositories and binds to MainWindow."""
    _get_qapp()

    cfg_file = tmp_path / "config.json"
    csv_file = tmp_path / "proxies.csv"

    config_repo = ConfigRepository(cfg_file)
    proxy_repo = ProxyRepository(csv_file)

    p1 = ProxyItem(protocol=ProxyProtocol.HTTP, host="1.2.3.4", port=8080)
    proxy_repo.add_or_merge([p1])

    window = MainWindow()
    controller = AppController(
        window=window,
        config_repo=config_repo,
        proxy_repo=proxy_repo,
    )
    controller.initialize()

    # Table model should be populated with 1 proxy
    assert window.table_model.rowCount() == 1
    # Status should be IDLE
    assert controller.state == AppState.IDLE
    # Protocols combo should have 'http'
    assert window.control_panel.combo_protocol.count() == 1
    assert window.control_panel.get_selected_protocol() == "http"
