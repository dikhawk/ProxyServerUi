"""Log console widget displaying colorized real-time events."""
from datetime import datetime
from types import MappingProxyType

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from src.domain.enums import LogLevel


class LogConsoleWidget(QWidget):
    """Text console for displaying timestamped, colorized application logs."""

    COLOR_MAP = MappingProxyType({
        LogLevel.INFO: "#ecf0f1",
        LogLevel.SUCCESS: "#2ecc71",
        LogLevel.ERROR: "#e74c3c",
    })

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            """
            QTextEdit {
                background-color: #1e1e1e;
                color: #ecf0f1;
                font-family: 'JetBrains Mono', 'Fira Code', 'Monospace', monospace;
                font-size: 12px;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px;
            }
            """
        )
        layout.addWidget(self.text_edit)

    def append_log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Append a new formatted log line with timestamp and level color."""
        now_str = datetime.now().strftime("%H:%M:%S")
        color = self.COLOR_MAP.get(level, "#ecf0f1")

        # Escape HTML entities in message
        escaped_message = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        html_line = (
            f"<div style='margin-bottom: 2px;'>"
            f"<span style='color: #7f8c8d;'>[{now_str}]</span> "
            f"<span style='color: {color};'>{escaped_message}</span>"
            f"</div>"
        )

        self.text_edit.append(html_line)

        # Autoscroll to bottom
        scrollbar = self.text_edit.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

    def clear_logs(self) -> None:
        """Clear the console output."""
        self.text_edit.clear()
