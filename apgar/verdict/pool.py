from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


class EvaluatorPool:
    def __init__(self, max_workers: int) -> None:
        self._max_workers = max(1, max_workers)
        self._executor: ProcessPoolExecutor | None = None

    def _pool(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
        return self._executor

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool(), fn, *args)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


class InlinePool:
    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        return fn(*args)

    def close(self) -> None:
        return None
