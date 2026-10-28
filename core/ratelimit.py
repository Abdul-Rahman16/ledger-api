import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from core.config import settings
from core.security import Identity, get_identity

WINDOW_SECONDS = 60


class SlidingWindowLimiter:
    """In-memory sliding window. Per process, which is fine for one free-tier instance."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            cutoff = now - window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(hits[0] + window_seconds - now) + 1)
                return False, retry_after
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def rate_limit(scope: str, limit_setting: str):
    """Dependency factory. limit_setting is the name of a Settings attribute."""

    def dependency(request: Request, identity: Identity = Depends(get_identity)) -> None:
        limit = getattr(settings, limit_setting)
        if identity.user_id:
            key = f"{scope}:user:{identity.user_id}"
        else:
            host = request.client.host if request.client else "unknown"
            key = f"{scope}:ip:{host}"

        allowed, retry_after = limiter.hit(key, limit, WINDOW_SECONDS)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency