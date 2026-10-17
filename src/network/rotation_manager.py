"""Proxy rotation manager managing active proxy queue and failover."""
import contextlib
import logging
from collections import deque

from src.domain.enums import ProxyStatus
from src.domain.proxy_item import ProxyItem

logger = logging.getLogger(__name__)


class ProxyRotationManager:
    """Manages working queue of active proxies with round-robin rotation and failover."""

    def __init__(
        self,
        initial_proxies: list[ProxyItem] | None = None,
        max_attempts: int = 5,
    ) -> None:
        self.max_attempts = max_attempts
        self._queue: deque[ProxyItem] = deque()
        if initial_proxies:
            self.reset_pool(initial_proxies)

    def reset_pool(self, items: list[ProxyItem]) -> None:
        """Reset and repopulate working queue with healthy proxies."""
        self._queue.clear()
        for item in items:
            if item.status != ProxyStatus.DEAD:
                self._queue.append(item)

    def get_current_proxy(self) -> ProxyItem | None:
        """Return the current active proxy at the head of the queue without removing it."""
        if not self._queue:
            return None
        return self._queue[0]

    def rotate(self) -> ProxyItem | None:
        """Move the current front proxy to the back of the queue (round-robin)."""
        if len(self._queue) > 1:
            self._queue.rotate(-1)
        return self.get_current_proxy()

    def report_failure(self, proxy: ProxyItem) -> bool:
        """
        Record failure for proxy.
        If max_attempts reached, proxy becomes DEAD and is removed from the queue (returns True).
        Otherwise, moves proxy to the end of the queue for later retry (returns False).
        """
        is_dead = proxy.register_failure(self.max_attempts)

        if is_dead or proxy.status == ProxyStatus.DEAD:
            with contextlib.suppress(ValueError):
                self._queue.remove(proxy)
            return True

        # Move failed proxy to the end of the queue
        with contextlib.suppress(ValueError):
            self._queue.remove(proxy)
            self._queue.append(proxy)
        return False

    def report_success(self, proxy: ProxyItem, rotate_next: bool = False) -> None:
        """Record successful operation for proxy, optionally rotating to the next proxy."""
        if rotate_next and len(self._queue) > 1:
            self._queue.rotate(-1)

    def is_empty(self) -> bool:
        """Check if active queue is empty."""
        return len(self._queue) == 0

    def active_count(self) -> int:
        """Return number of currently active proxies in queue."""
        return len(self._queue)

    def get_all(self) -> list[ProxyItem]:
        """Return a snapshot of current proxies in queue."""
        return list(self._queue)
