"""Main window application view layout."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.domain.enums import AppState
from src.ui.models.proxy_table_model import ProxyTableModel
from src.ui.models.sort_proxy_model import ProxySortFilterModel
from src.ui.widgets.control_panel import ControlPanelWidget
from src.ui.widgets.log_console import LogConsoleWidget


class MainWindow(QMainWindow):
    """Main application window composing controls, proxy table, and logs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Proxy Local Rotator & Checker")
        self.resize(1050, 700)

        # Models
        self.table_model = ProxyTableModel()
        self.sort_proxy_model = ProxySortFilterModel()
        self.sort_proxy_model.setSourceModel(self.table_model)
        self.sort_proxy_model.setDynamicSortFilter(True)

        self._setup_ui()

    def _setup_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # 1. Top control panel
        self.control_panel = ControlPanelWidget(self)
        root_layout.addWidget(self.control_panel)

        # Splitter between table and log console
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        # 2. Table view
        self.table_view = QTableView(self)
        self.table_view.setModel(self.sort_proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setAlternatingRowColors(True)
        h_header = self.table_view.horizontalHeader()
        if h_header is not None:
            h_header.setStretchLastSection(True)
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            h_header.setDefaultSectionSize(100)

        v_header = self.table_view.verticalHeader()
        if v_header is not None:
            v_header.setVisible(False)
        splitter.addWidget(self.table_view)

        # 3. Log console section
        log_container = QWidget(self)
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 4, 0, 0)
        log_layout.setSpacing(4)

        lbl_logs = QLabel("Логи работы:", self)
        lbl_logs.setStyleSheet("font-weight: bold; color: #7f8c8d;")
        log_layout.addWidget(lbl_logs)

        self.log_console = LogConsoleWidget(self)
        log_layout.addWidget(self.log_console)

        splitter.addWidget(log_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)

        # 4. Big primary toggle server button
        self.btn_toggle_server = QPushButton("🟢 Запустить локальный прокси", self)
        self.btn_toggle_server.setStyleSheet(
            """
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            """
        )
        root_layout.addWidget(self.btn_toggle_server)

    def set_app_state(self, state: AppState) -> None:
        """Update UI controls and main button appearance based on state."""
        self.control_panel.set_app_state(state)

        if state == AppState.RUNNING:
            self.btn_toggle_server.setText("🔴 Остановить локальный прокси")
            self.btn_toggle_server.setStyleSheet(
                """
                QPushButton {
                    background-color: #c0392b;
                    color: white;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 10px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #e74c3c;
                }
                """
            )
        else:
            self.btn_toggle_server.setText("🟢 Запустить локальный прокси")
            self.btn_toggle_server.setStyleSheet(
                """
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 10px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #2ecc71;
                }
                """
            )
