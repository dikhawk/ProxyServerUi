"""Settings modal dialog for configuring application parameters."""
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.domain.app_config import AppConfig


class SettingsDialog(QDialog):
    """Modal dialog allowing users to adjust URLs, timeouts, ports, and country filters."""

    def __init__(
        self,
        current_config: AppConfig,
        available_countries: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ Настройки приложения")
        self.setMinimumWidth(520)

        self._config = current_config
        self._available_countries = available_countries
        self._country_checkboxes: dict[str, QCheckBox] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        # Proxy sources (multiline text)
        self.txt_sources = QPlainTextEdit(self)
        self.txt_sources.setPlaceholderText("https://example.com/proxies.txt\nhttps://another-source.org/list.txt")
        self.txt_sources.setPlainText("\n".join(self._config.proxy_sources))
        self.txt_sources.setMaximumHeight(90)
        form_layout.addRow(QLabel("Ссылки на списки прокси (по 1 в строку):"), self.txt_sources)

        # Local port
        self.spin_port = QSpinBox(self)
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(self._config.local_port)
        form_layout.addRow(QLabel("Порт локального прокси:"), self.spin_port)

        # Preferred countries checkboxes
        countries_widget = QWidget()
        countries_layout = QHBoxLayout(countries_widget)
        countries_layout.setContentsMargins(0, 0, 0, 0)

        # Merge available countries with any already saved preferred countries
        all_countries = sorted(set(self._available_countries) | set(self._config.preferred_countries))
        if all_countries:
            scroll_area = QScrollArea(self)
            scroll_area.setWidgetResizable(True)
            scroll_area.setMaximumHeight(80)

            inner_widget = QWidget()
            inner_layout = QHBoxLayout(inner_widget)
            inner_layout.setContentsMargins(4, 4, 4, 4)

            for country in all_countries:
                cb = QCheckBox(country, self)
                cb.setChecked(country in self._config.preferred_countries)
                inner_layout.addWidget(cb)
                self._country_checkboxes[country] = cb

            inner_layout.addStretch()
            scroll_area.setWidget(inner_widget)
            form_layout.addRow(QLabel("Предпочитаемые страны:"), scroll_area)
        else:
            no_countries_lbl = QLabel("(нет доступных стран в базе)", self)
            no_countries_lbl.setStyleSheet("color: #7f8c8d; font-style: italic;")
            form_layout.addRow(QLabel("Предпочитаемые страны:"), no_countries_lbl)

        # Test URLs
        self.txt_test_urls = QLineEdit(self)
        self.txt_test_urls.setText(", ".join(self._config.test_urls))
        form_layout.addRow(QLabel("Тестовые URL (через запятую):"), self.txt_test_urls)

        # Timeouts layout
        timeouts_widget = QWidget()
        timeouts_layout = QHBoxLayout(timeouts_widget)
        timeouts_layout.setContentsMargins(0, 0, 0, 0)

        self.spin_conn_timeout = QSpinBox(self)
        self.spin_conn_timeout.setRange(100, 60000)
        self.spin_conn_timeout.setSingleStep(500)
        self.spin_conn_timeout.setValue(self._config.connection_timeout_ms)

        self.spin_resp_timeout = QSpinBox(self)
        self.spin_resp_timeout.setRange(100, 60000)
        self.spin_resp_timeout.setSingleStep(500)
        self.spin_resp_timeout.setValue(self._config.response_timeout_ms)

        timeouts_layout.addWidget(QLabel("Conn:"))
        timeouts_layout.addWidget(self.spin_conn_timeout)
        timeouts_layout.addWidget(QLabel("Resp:"))
        timeouts_layout.addWidget(self.spin_resp_timeout)
        form_layout.addRow(QLabel("Таймауты Conn / Resp (мс):"), timeouts_widget)

        # Max dead attempts
        self.spin_max_attempts = QSpinBox(self)
        self.spin_max_attempts.setRange(1, 100)
        self.spin_max_attempts.setValue(self._config.max_dead_attempts)
        form_layout.addRow(QLabel("Лимит сбоев (Max Dead Attempts):"), self.spin_max_attempts)

        root_layout.addLayout(form_layout)

        # Dialog Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save,
            self,
        )
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        root_layout.addWidget(button_box)

    def get_config(self) -> AppConfig:
        """Construct AppConfig from dialog inputs."""
        sources = [
            line.strip()
            for line in self.txt_sources.toPlainText().splitlines()
            if line.strip()
        ]

        preferred = [
            code
            for code, cb in self._country_checkboxes.items()
            if cb.isChecked()
        ]

        test_urls = [
            url.strip()
            for url in self.txt_test_urls.text().split(",")
            if url.strip()
        ]

        return AppConfig(
            proxy_sources=sources,
            local_port=self.spin_port.value(),
            preferred_countries=preferred,
            test_urls=test_urls or self._config.test_urls,
            connection_timeout_ms=self.spin_conn_timeout.value(),
            response_timeout_ms=self.spin_resp_timeout.value(),
            max_dead_attempts=self.spin_max_attempts.value(),
        )
