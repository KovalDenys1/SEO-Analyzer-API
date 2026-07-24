import asyncio
import copy
import time
from collections import OrderedDict
from collections.abc import Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class AsyncTTLCache(Generic[K, V]):
    """Small bounded process-local cache with deterministic LRU eviction."""

    def __init__(self, maxsize: int, ttl_seconds: float) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: K) -> V | None:
        if self._ttl <= 0:
            return None
        now = time.monotonic()
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            created_at, value = item
            if now - created_at >= self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return copy.deepcopy(value)

    async def set(self, key: K, value: V) -> None:
        if self._ttl <= 0:
            return
        async with self._lock:
            self._data[key] = (time.monotonic(), copy.deepcopy(value))
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    async def size(self) -> int:
        async with self._lock:
            return len(self._data)
