"""Control panel widget containing top management buttons and status indicator."""
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from src.domain.enums import AppState


class ControlPanelWidget(QWidget):
    """Toolbar control panel containing actions, protocol dropdown, and status."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.btn_load_file = QPushButton("📁 Загрузить файл", self)
        self.btn_load_file.setToolTip("Загрузить список прокси из локального .txt файла")

        self.btn_refresh = QPushButton("🔄 Обновить", self)
        self.btn_refresh.setToolTip("Скачать свежие списки прокси из URL источников")

        self.btn_check = QPushButton("⚡ Проверить", self)
        self.btn_check.setToolTip("Проверить доступность и замерить пинг всех прокси")

        self.btn_reset_stats = QPushButton("🧹 Сброс ст.", self)
        self.btn_reset_stats.setToolTip("Сбросить счетчики ошибок (fail_count) и вернуть прокси в строй")

        self.btn_clear = QPushButton("🗑️ Очистить", self)
        self.btn_clear.setToolTip("Полностью очистить локальную базу прокси")

        layout.addWidget(self.btn_load_file)
        layout.addWidget(self.btn_refresh)
        layout.addWidget(self.btn_check)
        layout.addWidget(self.btn_reset_stats)
        layout.addWidget(self.btn_clear)

        # Protocol selector
        self.lbl_protocol = QLabel("Тип:", self)
        self.combo_protocol = QComboBox(self)
        self.combo_protocol.setMinimumWidth(90)
        layout.addWidget(self.lbl_protocol)
        layout.addWidget(self.combo_protocol)

        # Settings button
        self.btn_settings = QPushButton("⚙️ Настройки", self)
        self.btn_settings.setToolTip("Открыть параметры приложения")
        layout.addWidget(self.btn_settings)

        layout.addStretch()

        # Status indicator
        self.lbl_status = QLabel("🔴 Остановлен", self)
        self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 13px; padding-left: 8px;")
        layout.addWidget(self.lbl_status)

    def set_app_state(self, state: AppState) -> None:
        """Toggle UI controls availability based on application running state."""
        is_idle = state == AppState.IDLE

        self.btn_load_file.setEnabled(is_idle)
        self.btn_refresh.setEnabled(is_idle)
        self.btn_check.setEnabled(is_idle)
        self.btn_reset_stats.setEnabled(is_idle)
        self.btn_clear.setEnabled(is_idle)
        self.combo_protocol.setEnabled(is_idle)
        self.btn_settings.setEnabled(is_idle)

        if is_idle:
            self.lbl_status.setText("🔴 Остановлен")
            self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 13px; padding-left: 8px;")
        else:
            self.lbl_status.setText("🟢 Работает")
            self.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold; font-size: 13px; padding-left: 8px;")

    def update_protocols(self, protocols: list[str]) -> None:
        """Update available protocols in dropdown preserving current selection if present."""
        current = self.combo_protocol.currentText()
        self.combo_protocol.blockSignals(True)
        self.combo_protocol.clear()

        for proto in protocols:
            self.combo_protocol.addItem(proto)

        # Restore previous selection if possible
        idx = self.combo_protocol.findText(current)
        if idx >= 0:
            self.combo_protocol.setCurrentIndex(idx)
        elif self.combo_protocol.count() > 0:
            self.combo_protocol.setCurrentIndex(0)

        self.combo_protocol.blockSignals(False)

    def get_selected_protocol(self) -> str:
        """Return currently selected protocol string."""
        return self.combo_protocol.currentText().strip()
