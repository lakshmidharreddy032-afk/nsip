"""Real-time queue updates. In-process fan-out for one replica; Redis pub/sub bridges replicas."""
from __future__ import annotations

import asyncio
import json
import threading

from app.core.config import get_settings


class Broadcaster:
    def __init__(self) -> None:
        self._subs: set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()
        self._lock = threading.Lock()
        self._redis = None
        url = get_settings().redis_url
        if url:
            try:  # pragma: no cover - requires redis
                import redis

                self._redis = redis.Redis.from_url(url)
            except Exception:  # noqa: BLE001
                self._redis = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subs.add((q, asyncio.get_running_loop()))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = {s for s in self._subs if s[0] is not q}

    def publish(self, event: str, data: dict) -> None:
        msg = {"event": event, "data": data}
        if self._redis is not None:  # pragma: no cover
            try:
                self._redis.publish("nsip-events", json.dumps(msg, default=str))
            except Exception:  # noqa: BLE001,S110
                pass
        self.local_publish(msg)

    def local_publish(self, msg: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q, loop in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, msg)
            except (RuntimeError, asyncio.QueueFull):
                pass


broadcaster = Broadcaster()
