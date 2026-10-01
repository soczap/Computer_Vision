"""In-process pub/sub bridging camera threads and the asyncio world.

Perception runs in threads; agents and WebSockets live on the event loop.
`publish_threadsafe` is the only door from a thread into the loop.
Subscribers get bounded queues: a slow consumer drops its own messages
instead of stalling the publisher.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger("vigil.bus")


class Bus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None
        self.dropped = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, *topics: str, maxsize: int = 500) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        for t in topics:
            self._subs[t].add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        for subs in self._subs.values():
            subs.discard(q)

    def publish(self, topic: str, payload: Any) -> None:
        """Call from the event loop."""
        msg = {"topic": topic, "data": payload}
        targets = set(self._subs.get(topic, ())) | set(self._subs.get("*", ()))
        prefix = topic.split(".", 1)[0] + ".*"
        targets |= set(self._subs.get(prefix, ()))
        for q in targets:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                self.dropped += 1

    def publish_threadsafe(self, topic: str, payload: Any) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self.publish, topic, payload)


bus = Bus()
