import asyncio
from contextlib import asynccontextmanager


class ChatActivityMonitor:
    """Track interactive chat traffic so background work can yield to it."""

    def __init__(self) -> None:
        self._active = 0
        self._activity_version = 0
        self._condition = asyncio.Condition()

    @property
    def active(self) -> int:
        return self._active

    async def begin(self) -> None:
        async with self._condition:
            self._active += 1
            self._activity_version += 1
            self._condition.notify_all()

    async def end(self) -> None:
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._activity_version += 1
            self._condition.notify_all()

    @asynccontextmanager
    async def request(self):
        await self.begin()
        try:
            yield
        finally:
            await self.end()

    async def wait_for_idle(self, quiet_seconds: float) -> None:
        """
        Wait until no chat is active and Jace then remains continuously idle
        for ``quiet_seconds``. Any chat activity during the quiet window starts
        the window again.
        """
        quiet_seconds = max(0.0, float(quiet_seconds))

        while True:
            async with self._condition:
                while self._active > 0:
                    await self._condition.wait()
                version_before_wait = self._activity_version

            if quiet_seconds <= 0:
                return

            await asyncio.sleep(quiet_seconds)

            async with self._condition:
                if self._active == 0 and self._activity_version == version_before_wait:
                    return


chat_activity = ChatActivityMonitor()
