"""Arrival detection independent of Arduino and UI details."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Protocol, Tuple


class EncoderSource(Protocol):
    def read(self) -> Optional[Tuple[int, int]]: ...


class SimulatedEncoderSource:
    """Moves for ``moving_seconds``, then holds still for demo testing."""

    def __init__(self, moving_seconds: float = 3.0) -> None:
        self.started = time.monotonic()
        self.moving_seconds = moving_seconds
        self.ticks = 0

    def restart(self) -> None:
        self.started = time.monotonic()
        self.ticks = 0

    def read(self) -> Tuple[int, int]:
        if time.monotonic() - self.started < self.moving_seconds:
            self.ticks += 12
        return self.ticks, self.ticks


class ArrivalDetector:
    """Detect movement followed by stable encoder readings.

    Requiring observed movement prevents a false arrival immediately after a
    moving phase begins. Manual arrival remains available through ``trigger``.
    """

    def __init__(
        self,
        source: Optional[EncoderSource],
        stable_seconds: float = 4.0,
        noise_threshold: int = 2,
        poll_seconds: float = 0.15,
    ) -> None:
        self.source = source
        self.stable_seconds = stable_seconds
        self.noise_threshold = noise_threshold
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[str], None]] = None
        self._lock = threading.Lock()
        self._active = False
        self._generation = 0

    def start(self, callback: Callable[[str], None]) -> None:
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._active = True
            self._callback = callback
        self._stop.clear()
        if self.source is not None:
            restart = getattr(self.source, "restart", None)
            if restart:
                restart()
            self._thread = threading.Thread(target=self._monitor, args=(generation,), daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._generation += 1
            self._active = False
            self._callback = None

    def trigger(self, reason: str = "manual") -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            callback = self._callback
            self._callback = None
        self._stop.set()
        if callback:
            callback(reason)

    def _monitor(self, generation: int) -> None:
        previous: Optional[Tuple[int, int]] = None
        stable_since: Optional[float] = None
        movement_seen = False
        while not self._stop.wait(self.poll_seconds):
            with self._lock:
                if generation != self._generation or not self._active:
                    return
            current = self.source.read() if self.source else None
            if current is None:
                continue
            if previous is None:
                previous = current
                continue
            changed = any(abs(a - b) > self.noise_threshold for a, b in zip(current, previous))
            now = time.monotonic()
            if changed:
                movement_seen = True
                stable_since = now
                previous = current
            elif movement_seen:
                stable_since = stable_since or now
                if now - stable_since >= self.stable_seconds:
                    with self._lock:
                        current_generation = self._generation
                    if generation == current_generation:
                        self.trigger("encoder")
                    return
