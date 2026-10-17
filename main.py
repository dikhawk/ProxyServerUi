"""Entry point for Proxy Local Rotator & Checker application."""
import asyncio
import sys

import qasync
from PyQt6.QtWidgets import QApplication

from src.data.config_repository import ConfigRepository
from src.data.proxy_repository import ProxyRepository
from src.presentation.app_controller import AppController
from src.ui.main_window import MainWindow


def main() -> None:
    """Initialize application components, DI, qasync event loop and run main window."""
    app = QApplication(sys.argv)
    app.setApplicationName("Proxy Rotator & Checker")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    config_repo = ConfigRepository()
    proxy_repo = ProxyRepository()

    window = MainWindow()
    controller = AppController(
        window=window,
        config_repo=config_repo,
        proxy_repo=proxy_repo,
    )
    controller.initialize()

    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
