"""Single-owner Arduino transport for motor commands and encoder telemetry."""
from __future__ import annotations

import re
import threading
import time
from typing import Optional, Tuple


ENCODER_PATTERN = re.compile(r"^ENC\s+L=(-?\d+)\s+R=(-?\d+)\s*$")


class ArduinoSerialManager:
    """Own the Arduino serial port for the lifetime of the application.

    The manager is also an ``EncoderSource``: ``ArrivalDetector`` calls
    ``read()`` to retrieve the latest encoder pair without touching serial.
    """

    VALID_COMMANDS = {"F", "B", "L", "R", "S"}

    def __init__(self, port: str, baudrate: int = 115200, reconnect_seconds: float = 2.0) -> None:
        self.port = port
        self.baudrate = baudrate
        self.reconnect_seconds = reconnect_seconds
        self._serial = None
        self._latest_ticks: Optional[Tuple[int, int]] = None
        self._ticks_lock = threading.Lock()
        self._write_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.connected = threading.Event()

    @staticmethod
    def parse_encoder_line(line: str) -> Optional[Tuple[int, int]]:
        match = ENCODER_PATTERN.match(line.strip())
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader_loop, name="arduino-serial", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self.send_motor_command("S", 0)
        self._disconnect()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def read(self) -> Optional[Tuple[int, int]]:
        with self._ticks_lock:
            return self._latest_ticks

    def send_motor_command(self, command: str, speed: int) -> bool:
        command = command.upper()
        if command not in self.VALID_COMMANDS:
            raise ValueError(f"Unsupported motor command: {command}")
        speed = 0 if command == "S" else max(0, min(255, int(speed)))
        payload = f"CMD {command} {speed}\n".encode("ascii")
        with self._write_lock:
            serial_connection = self._serial
            if serial_connection is None:
                return False
            try:
                serial_connection.write(payload)
                serial_connection.flush()
                return True
            except Exception as exc:
                print(f"Arduino write failed: {exc}")
                self._disconnect()
                return False

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            if self._serial is None and not self._connect():
                self._stop.wait(self.reconnect_seconds)
                continue
            try:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="ignore").strip()
                ticks = self.parse_encoder_line(line)
                if ticks is not None:
                    with self._ticks_lock:
                        self._latest_ticks = ticks
            except Exception as exc:
                if not self._stop.is_set():
                    print(f"Arduino disconnected: {exc}; reconnecting…")
                self._disconnect()

    def _connect(self) -> bool:
        try:
            import serial  # type: ignore
            connection = serial.Serial(self.port, self.baudrate, timeout=0.2, write_timeout=0.5)
            with self._write_lock:
                self._serial = connection
            self.connected.set()
            print(f"Arduino connected on {self.port} at {self.baudrate} baud")
            # An Uno resets when serial opens. Let its bootloader finish.
            if self._stop.wait(2.0):
                return False
            connection.reset_input_buffer()
            return True
        except Exception as exc:
            print(f"Arduino unavailable on {self.port}: {exc}")
            self._disconnect()
            return False

    def _disconnect(self) -> None:
        with self._write_lock:
            connection, self._serial = self._serial, None
        self.connected.clear()
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
