from __future__ import annotations

from datetime import datetime

from apgar.assembly.assembler import Assembler


class AssemblyJob:
    def __init__(self, assembler: Assembler) -> None:
        self._assembler = assembler

    async def run(self, now: datetime) -> None:
        await self._assembler.run_once(now, skip_source="demo")
