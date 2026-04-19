"""Minimal string-keyed pub/sub bus.

Handlers are invoked in subscription order. A handler may unsubscribe
(itself or another) during emission; removals are queued and applied
after the outermost ``emit`` completes, so the dispatch loop itself is
allocation-free (no per-emit ``list(...)`` snapshot).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

Handler = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._emitting: int = 0
        self._pending_removals: list[tuple[str, Handler]] = []

    def on(self, topic: str, handler: Handler) -> Callable[[], None]:
        self._subs[topic].append(handler)

        def off() -> None:
            if self._emitting > 0:
                self._pending_removals.append((topic, handler))
                return
            try:
                self._subs[topic].remove(handler)
            except ValueError:
                pass

        return off

    def emit(self, topic: str, *args: Any, **kwargs: Any) -> None:
        subs = self._subs.get(topic)
        if not subs:
            return
        self._emitting += 1
        try:
            for h in subs:
                h(*args, **kwargs)
        finally:
            self._emitting -= 1
            if self._emitting == 0 and self._pending_removals:
                for t, h in self._pending_removals:
                    try:
                        self._subs[t].remove(h)
                    except ValueError:
                        pass
                self._pending_removals.clear()

    def clear(self) -> None:
        self._subs.clear()
        self._pending_removals.clear()
