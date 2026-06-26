"""Non-blocking SSH-terminal keyboard driving."""
from __future__ import annotations

import os
import select
import sys
import threading
import time
from typing import Callable, Optional, Protocol


class MotorCommandSink(Protocol):
    def send_motor_command(self, command: str, speed: int) -> bool: ...


class KeyboardDriver:
    COMMANDS = {"w": "F", "s": "B", "a": "L", "d": "R", " ": "S"}

    def __init__(self, sink: MotorCommandSink, on_emergency: Callable[[], None], speed: int = 120,
                 turn_speed: int = 100) -> None:
        self.sink = sink
        self.on_emergency = on_emergency
        self.speed = max(0, min(255, speed))
        self.turn_speed = max(0, min(255, turn_speed))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_command = ("S", 0)
        self._last_refresh = 0.0

    def start(self) -> bool:
        if not sys.stdin.isatty():
            print("Keyboard drive disabled: SSH standard input is not a TTY.")
            return False
        print("Keyboard drive: W forward, S backward, A left, D right, Space stop, Q emergency")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="keyboard-drive", daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        self._active_command = ("S", 0)
        self.sink.send_motor_command("S", 0)

    def _run(self) -> None:
        if os.name == "nt":
            self._run_windows()
        else:
            self._run_posix()

    def _handle(self, key: str) -> None:
        key = key.lower()
        if key == "q":
            self._active_command = ("S", 0)
            self.sink.send_motor_command("S", 0)
            self._stop.set()
            self.on_emergency()
            return
        command = self.COMMANDS.get(key)
        if command:
            speed = 0 if command == "S" else self.turn_speed if command in {"L", "R"} else self.speed
            self._active_command = (command, speed)
            sent = self.sink.send_motor_command(command, speed)
            print(f"Drive: {command} {speed}" + ("" if sent else " (Arduino unavailable)"))

    def _refresh_active_command(self) -> None:
        command, speed = self._active_command
        now = time.monotonic()
        if command != "S" and now - self._last_refresh >= 0.25:
            self.sink.send_motor_command(command, speed)
            self._last_refresh = now

    def _run_windows(self) -> None:
        import msvcrt
        while not self._stop.wait(0.05):
            if msvcrt.kbhit():
                self._handle(msvcrt.getwch())
            self._refresh_active_command()

    def _run_posix(self) -> None:
        import termios
        import tty
        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._stop.is_set():
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if ready:
                    self._handle(sys.stdin.read(1))
                self._refresh_active_command()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)
