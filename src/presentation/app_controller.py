"""Application controller mediating between UI, data repositories, and network services."""
import asyncio
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from src.data.config_repository import ConfigRepository
from src.data.proxy_parser import ProxyParser
from src.data.proxy_repository import ProxyRepository
from src.domain.app_config import AppConfig
from src.domain.enums import AppState, LogLevel
from src.domain.proxy_item import ProxyItem
from src.network.local_server import LocalProxyServer
from src.network.proxy_checker import ProxyCheckerService
from src.network.rotation_manager import ProxyRotationManager
from src.network.source_fetcher import ProxySourceFetcher
from src.ui.main_window import MainWindow
from src.ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


class AppController:
    """Controller handling application state, user commands, and background tasks."""

    def __init__(
        self,
        window: MainWindow,
        config_repo: ConfigRepository,
        proxy_repo: ProxyRepository,
    ) -> None:
        self.window = window
        self.config_repo = config_repo
        self.proxy_repo = proxy_repo

        self.config: AppConfig = AppConfig()
        self.state: AppState = AppState.IDLE

        self.rotation_manager: ProxyRotationManager | None = None
        self.local_server: LocalProxyServer | None = None

        self._checker_service: ProxyCheckerService | None = None
        self._check_task: asyncio.Task[Any] | None = None
        self._active_async_tasks: set[asyncio.Task[Any]] = set()

    def initialize(self) -> None:
        """Initialize configurations, load proxy database, and bind UI signals."""
        self.config = self.config_repo.load()
        self.proxy_repo.load()

        # Populate initial UI state
        all_items = self.proxy_repo.get_all()
        self.window.table_model.set_proxies(all_items)
        self.window.table_model.set_max_attempts(self.config.max_dead_attempts)
        self.window.control_panel.update_protocols(self.proxy_repo.get_available_protocols())
        self.window.set_app_state(AppState.IDLE)

        self._log(
            f"Загружена база из {self.proxy_repo.storage_path.name} ({len(all_items)} записей)",
            LogLevel.INFO,
        )

        self._bind_signals()

    def _bind_signals(self) -> None:
        """Connect UI widget signals to controller handler methods."""
        cp = self.window.control_panel
        cp.btn_load_file.clicked.connect(self.on_load_file_clicked)
        cp.btn_refresh.clicked.connect(self.on_refresh_clicked)
        cp.btn_check.clicked.connect(self.on_check_clicked)
        cp.btn_reset_stats.clicked.connect(self.on_reset_stats_clicked)
        cp.btn_clear.clicked.connect(self.on_clear_clicked)
        cp.btn_delete_selected.clicked.connect(self.on_delete_selected_clicked)
        cp.btn_delete_dead.clicked.connect(self.on_delete_dead_clicked)
        cp.btn_settings.clicked.connect(self.on_settings_clicked)

        self.window.btn_toggle_server.clicked.connect(self.on_toggle_server_clicked)

    def _log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Append log to UI log console."""
        self.window.log_console.append_log(message, level)

    def _run_task(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule an asynchronous task and track it."""
        task = asyncio.create_task(coro)
        self._active_async_tasks.add(task)
        task.add_done_callback(self._active_async_tasks.discard)

    # UI Action Handlers

    def on_load_file_clicked(self) -> None:
        """Open system file picker, parse proxy list, and merge into database."""
        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Выберите файл со списком прокси",
            "",
            "Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            new_items = ProxyParser.parse_text(content)
            added_count = self.proxy_repo.add_or_merge(new_items)

            self.window.table_model.set_proxies(self.proxy_repo.get_all())
            self.window.control_panel.update_protocols(self.proxy_repo.get_available_protocols())

            self._log(
                f"Из файла '{Path(file_path).name}' добавлено {added_count} новых прокси "
                f"(всего в базе: {self.proxy_repo.count()})",
                LogLevel.INFO,
            )
        except Exception as exc:
            self._log(f"Ошибка чтения файла '{file_path}': {exc}", LogLevel.ERROR)

    def on_refresh_clicked(self) -> None:
        """Trigger async downloading of proxy sources."""
        if not self.config.proxy_sources:
            self._log("Список источников прокси пуст. Задайте ссылки в Настройках.", LogLevel.ERROR)
            return

        self._log("Начало обновления списков прокси из источников...", LogLevel.INFO)
        self._run_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        fetcher = ProxySourceFetcher(
            log_callback=self._log,
            timeout_seconds=max(2.0, self.config.response_timeout_ms / 1000.0),
        )
        items = await fetcher.fetch_all(self.config.proxy_sources)
        added_count = self.proxy_repo.add_or_merge(items)

        self.window.table_model.set_proxies(self.proxy_repo.get_all())
        self.window.control_panel.update_protocols(self.proxy_repo.get_available_protocols())
        self._log(
            f"Обновление завершено. Добавлено {added_count} новых прокси "
            f"(всего: {self.proxy_repo.count()})",
            LogLevel.INFO,
        )

    def on_check_clicked(self) -> None:
        """Toggle proxy checking: start if idle, stop if currently checking."""
        if self.state == AppState.CHECKING:
            self._stop_check_flow()
            return

        items = self.proxy_repo.get_all()
        if not items:
            self._log("База прокси пуста. Нечего проверять.", LogLevel.INFO)
            return

        self._log(f"Запуск проверки {len(items)} прокси...", LogLevel.INFO)
        self.state = AppState.CHECKING
        self.window.set_app_state(AppState.CHECKING)
        self._check_task = asyncio.create_task(self._async_check(items))
        self._active_async_tasks.add(self._check_task)
        self._check_task.add_done_callback(self._active_async_tasks.discard)

    def _stop_check_flow(self) -> None:
        """Cancel ongoing proxy checking task and service."""
        if self._checker_service:
            self._checker_service.cancel()
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
        self.state = AppState.IDLE
        self.window.set_app_state(AppState.IDLE)
        self._log("Остановка проверки прокси...", LogLevel.INFO)

    async def _async_check(self, items: list[ProxyItem]) -> None:
        try:
            self._checker_service = ProxyCheckerService(
                config=self.config,
                log_callback=self._log,
            )

            def _on_item_done(item: ProxyItem) -> None:
                self.window.table_model.update_proxy(item)

            await self._checker_service.check_all(
                items,
                on_item_completed=_on_item_done,
                single_check=True,
            )
            self.proxy_repo.save()
            self._log("Проверка прокси завершена.", LogLevel.INFO)
        except asyncio.CancelledError:
            self.proxy_repo.save()
            self._log("Проверка прокси остановлена пользователем.", LogLevel.INFO)
        except Exception as exc:
            self._log(f"Ошибка при проверке прокси: {exc}", LogLevel.ERROR)
        finally:
            self._checker_service = None
            self._check_task = None
            self.state = AppState.IDLE
            self.window.set_app_state(AppState.IDLE)

    def on_reset_stats_clicked(self) -> None:
        """Reset failure counts and dead timestamps for all proxies."""
        items = self.proxy_repo.get_all()
        for it in items:
            it.reset_statistics()
        self.proxy_repo.save()
        self.window.table_model.set_proxies(items)
        self._log(
            f"Статистика сбоев сброшена для {len(items)} прокси. Все узлы возвращены в строй.",
            LogLevel.INFO,
        )

    def on_clear_clicked(self) -> None:
        """Clear database after confirmation dialog."""
        reply = QMessageBox.question(
            self.window,
            "Подтверждение очистки",
            "Вы действительно хотите полностью очистить локальную базу прокси?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.proxy_repo.clear_all()
            self.window.table_model.set_proxies([])
            self.window.control_panel.update_protocols([])
            self._log("База прокси полностью очищена.", LogLevel.INFO)

    def on_delete_selected_clicked(self) -> None:
        """Delete user-selected proxies from table and repository."""
        selected = self.window.get_selected_proxies()
        if not selected:
            self._log("Не выбрано ни одного прокси для удаления.", LogLevel.INFO)
            return

        removed = self.proxy_repo.remove_items(selected)
        self.window.table_model.set_proxies(self.proxy_repo.get_all())
        self.window.control_panel.update_protocols(self.proxy_repo.get_available_protocols())
        self._log(
            f"Удалено {removed} прокси вручную (всего в базе: {self.proxy_repo.count()})",
            LogLevel.INFO,
        )

    def on_delete_dead_clicked(self) -> None:
        """Delete all proxies marked as DEAD from database."""
        removed = self.proxy_repo.remove_dead()
        self.window.table_model.set_proxies(self.proxy_repo.get_all())
        self.window.control_panel.update_protocols(self.proxy_repo.get_available_protocols())
        self._log(
            f"Удалено {removed} нерабочих (Dead) прокси (всего в базе: {self.proxy_repo.count()})",
            LogLevel.INFO,
        )

    def on_settings_clicked(self) -> None:
        """Open settings dialog and persist valid changes."""
        dialog = SettingsDialog(
            current_config=self.config,
            available_countries=self.proxy_repo.get_available_countries(),
            parent=self.window,
        )
        if dialog.exec():
            new_config = dialog.get_config()
            valid, err = new_config.validate()
            if not valid:
                QMessageBox.warning(self.window, "Ошибка валидации", err)
                return

            self.config = new_config
            self.config_repo.save(self.config)
            self.window.table_model.set_max_attempts(self.config.max_dead_attempts)
            if self.rotation_manager:
                self.rotation_manager.max_attempts = self.config.max_dead_attempts
            self._log("Настройки успешно сохранены.", LogLevel.INFO)

    def on_toggle_server_clicked(self) -> None:
        """Toggle local proxy server running state."""
        if self.state == AppState.IDLE:
            self._start_server_flow()
        elif self.state == AppState.RUNNING:
            self._stop_server_flow()

    def _on_pool_updated(self, active: int, total: int) -> None:
        """Update active vs total proxies counter in UI."""
        self.window.control_panel.set_active_proxy_count(active, total)

    def _on_proxy_status_changed(self, item: ProxyItem) -> None:
        """Update proxy row in table when its status or fail count changes during server operation."""
        self.window.table_model.update_proxy(item)

    def _start_server_flow(self) -> None:
        """Verify selected protocol and pool, then launch local proxy server."""
        if self.state != AppState.IDLE:
            return

        protocol = self.window.control_panel.get_selected_protocol()
        if not protocol:
            QMessageBox.warning(
                self.window,
                "Предупреждение",
                "Не выбран протокол прокси для запуска! Загрузите прокси в базу.",
            )
            return

        working_pool = self.proxy_repo.get_working_pool(
            protocol=protocol,
            countries=self.config.preferred_countries,
        )
        if not working_pool:
            msg = (
                f"Рабочий пул пуст! Нет живых прокси для протокола '{protocol}'"
                + (f" и стран {self.config.preferred_countries}" if self.config.preferred_countries else "")
                + "."
            )
            QMessageBox.warning(self.window, "Предупреждение", msg)
            self._log(msg, LogLevel.ERROR)
            return

        self.rotation_manager = ProxyRotationManager(
            initial_proxies=working_pool,
            max_attempts=self.config.max_dead_attempts,
        )

        self.local_server = LocalProxyServer(
            config=self.config,
            rotation_manager=self.rotation_manager,
            log_callback=self._log,
            on_pool_exhausted=self._on_pool_exhausted,
            on_pool_updated=self._on_pool_updated,
            on_proxy_status_changed=self._on_proxy_status_changed,
        )

        self._run_task(self._async_start_server())

    async def _async_start_server(self) -> None:
        if self.local_server:
            try:
                await self.local_server.start()
                self.state = AppState.RUNNING
                self.window.set_app_state(AppState.RUNNING)
                self.local_server._notify_pool_updated()
            except Exception as e:
                self._log(f"Не удалось запустить локальный сервер: {e}", LogLevel.ERROR)
                self.local_server = None
                self.state = AppState.IDLE
                self.window.set_app_state(AppState.IDLE)

    def _stop_server_flow(self) -> None:
        """Stop local proxy server and restore IDLE state."""
        self._run_task(self._async_stop_server())

    async def _async_stop_server(self) -> None:
        try:
            if self.local_server:
                await self.local_server.stop()
        except Exception as e:
            self._log(f"Ошибка при остановке сервера: {e}", LogLevel.ERROR)
        finally:
            self.local_server = None
            self.state = AppState.IDLE
            self.window.set_app_state(AppState.IDLE)
            self.proxy_repo.save()

    def _on_pool_exhausted(self) -> None:
        """Callback invoked when all proxies in rotation manager have died."""
        self.local_server = None
        self.state = AppState.IDLE
        self.window.set_app_state(AppState.IDLE)
        self.proxy_repo.save()
