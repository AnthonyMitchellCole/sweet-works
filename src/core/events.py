"""Minimal string-keyed pub/sub bus."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


Handler = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def on(self, topic: str, handler: Handler) -> Callable[[], None]:
        self._subs[topic].append(handler)

        def off() -> None:
            if handler in self._subs[topic]:
                self._subs[topic].remove(handler)

        return off

    def emit(self, topic: str, *args: Any, **kwargs: Any) -> None:
        for h in list(self._subs.get(topic, ())):
            h(*args, **kwargs)

    def clear(self) -> None:
        self._subs.clear()
