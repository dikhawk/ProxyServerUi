"""Proxy repository for storing and managing proxy nodes."""
import csv
import logging
from pathlib import Path

from src.domain.enums import ProxyProtocol, ProxyStatus
from src.domain.proxy_item import ProxyItem

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "protocol",
    "host",
    "port",
    "username",
    "password",
    "location",
    "status",
    "ping",
    "url_status",
    "added_at",
    "fail_count",
    "dead_since",
]


class ProxyRepository:
    """In-memory dictionary storage backed by local CSV file."""

    def __init__(self, storage_path: str | Path = "proxies_database.csv") -> None:
        self.storage_path = Path(storage_path)
        self._items: dict[str, ProxyItem] = {}

    def load(self) -> None:
        """Load proxies from CSV database into memory."""
        self._items.clear()
        if not self.storage_path.exists():
            self._write_empty_csv()
            return

        try:
            with open(self.storage_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        protocol = ProxyProtocol(row["protocol"].strip().lower())
                        port = int(row["port"].strip())
                        status = ProxyStatus(row.get("status", "Untested").strip())

                        ping_raw = row.get("ping", "").strip()
                        ping = int(ping_raw) if ping_raw.isdigit() else None

                        fail_raw = row.get("fail_count", "").strip()
                        fail_count = int(fail_raw) if fail_raw.isdigit() else 0

                        item = ProxyItem(
                            protocol=protocol,
                            host=row["host"].strip(),
                            port=port,
                            username=row.get("username", "").strip() or None,
                            password=row.get("password", "").strip() or None,
                            location=row.get("location", "Unknown").strip() or "Unknown",
                            status=status,
                            ping=ping,
                            url_status=row.get("url_status", "-").strip() or "-",
                            added_at=row.get("added_at", "").strip(),
                            fail_count=fail_count,
                            dead_since=row.get("dead_since", "").strip(),
                        )
                        self._items[item.unique_key] = item
                    except (KeyError, ValueError) as err:
                        logger.warning("Skipping malformed row in CSV: %s (%s)", row, err)
        except OSError as e:
            logger.error("Failed to read proxy CSV database %s: %s", self.storage_path, e)

    def save(self) -> None:
        """Persist in-memory proxy collection to CSV database."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()
                for item in self._items.values():
                    writer.writerow(
                        {
                            "protocol": item.protocol.value,
                            "host": item.host,
                            "port": item.port,
                            "username": item.username or "",
                            "password": item.password or "",
                            "location": item.location,
                            "status": item.status.value,
                            "ping": str(item.ping) if item.ping is not None else "",
                            "url_status": item.url_status,
                            "added_at": item.added_at,
                            "fail_count": item.fail_count,
                            "dead_since": item.dead_since,
                        }
                    )
        except OSError as e:
            logger.error("Failed to save proxy CSV database %s: %s", self.storage_path, e)
            raise

    def _write_empty_csv(self) -> None:
        """Create an empty CSV file with only headers."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()
        except OSError as e:
            logger.error("Failed to initialize empty CSV %s: %s", self.storage_path, e)
            raise

    def add_or_merge(self, new_items: list[ProxyItem]) -> int:
        """
        Merge new items with deduplication.
        Existing items with the same unique_key are NOT overwritten,
        preserving their statistics, ping, and added timestamp.
        Returns the number of newly added items.
        """
        added_count = 0
        for item in new_items:
            key = item.unique_key
            if key not in self._items:
                self._items[key] = item
                added_count += 1

        if added_count > 0:
            self.save()
        return added_count

    def clear_all(self) -> None:
        """Clear all in-memory items and truncate CSV file to headers only."""
        self._items.clear()
        self._write_empty_csv()

    def remove_by_keys(self, keys: list[str]) -> int:
        """Remove proxies by unique keys. Returns number of removed items."""
        removed = 0
        for key in keys:
            if key in self._items:
                del self._items[key]
                removed += 1
        if removed > 0:
            self.save()
        return removed

    def remove_items(self, items: list[ProxyItem]) -> int:
        """Remove proxies by item instances. Returns number of removed items."""
        keys = [item.unique_key for item in items]
        return self.remove_by_keys(keys)

    def remove_dead(self) -> int:
        """Remove all proxies with DEAD status. Returns number of removed items."""
        dead_keys = [
            key for key, item in self._items.items()
            if item.status == ProxyStatus.DEAD
        ]
        return self.remove_by_keys(dead_keys)

    def get_all(self) -> list[ProxyItem]:
        """Return all proxies in repository."""
        return list(self._items.values())

    def get_by_key(self, unique_key: str) -> ProxyItem | None:
        """Find proxy by its unique key."""
        return self._items.get(unique_key)

    def count(self) -> int:
        """Return total number of proxies."""
        return len(self._items)

    def get_available_protocols(self) -> list[str]:
        """Return unique sorted list of protocols currently in repository."""
        protocols = {item.protocol.value for item in self._items.values()}
        return sorted(protocols)

    def get_available_countries(self) -> list[str]:
        """Return unique sorted list of country codes (excluding Unknown/-)."""
        countries = {
            item.location.strip().upper()
            for item in self._items.values()
            if item.location and item.location.strip().upper() not in ("UNKNOWN", "-", "")
        }
        return sorted(countries)

    def get_working_pool(
        self,
        protocol: str,
        countries: list[str],
    ) -> list[ProxyItem]:
        """
        Return proxies with Active or Untested status filtered by protocol and countries.
        If countries is empty, proxies from any country are included.
        """
        target_protocol = protocol.strip().lower()
        allowed_countries = {c.strip().upper() for c in countries if c.strip()}

        pool: list[ProxyItem] = []
        for item in self._items.values():
            if item.status not in (ProxyStatus.ACTIVE, ProxyStatus.UNTESTED):
                continue
            if item.protocol.value.lower() != target_protocol:
                continue
            if allowed_countries and item.location.strip().upper() not in allowed_countries:
                continue
            pool.append(item)

        return pool
