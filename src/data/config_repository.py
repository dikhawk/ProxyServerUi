"""Repository for application configuration persistence."""
import json
import logging
from pathlib import Path

from src.domain.app_config import AppConfig

logger = logging.getLogger(__name__)


class ConfigRepository:
    """Manages loading and saving application configuration in config.json."""

    def __init__(self, config_path: str | Path = "config.json") -> None:
        self.config_path = Path(config_path)

    def load(self) -> AppConfig:
        """
        Load AppConfig from JSON file.
        If the file does not exist or is corrupted, creates and saves default config.
        """
        if not self.config_path.exists():
            default_config = AppConfig()
            self.save(default_config)
            return default_config

        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Config root must be a JSON object")
            return AppConfig.from_dict(data)
        except Exception as e:
            logger.warning(
                "Failed to parse config file %s: %s. Reverting to default.",
                self.config_path,
                e,
            )
            default_config = AppConfig()
            self.save(default_config)
            return default_config

    def save(self, config: AppConfig) -> None:
        """Save AppConfig to JSON file with formatting."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error("Failed to save config to %s: %s", self.config_path, e)
            raise
