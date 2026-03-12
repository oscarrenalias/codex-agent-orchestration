from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[38;5;39m"
GREEN = "\033[38;5;42m"
YELLOW = "\033[38;5;220m"
RED = "\033[38;5;196m"
MAGENTA = "\033[38;5;171m"
CYAN = "\033[38;5;81m"


class Spinner(AbstractContextManager["Spinner"]):
    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, console: "ConsoleReporter", label: str) -> None:
        self.console = console
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Spinner":
        if self.console.is_tty:
            self._thread = threading.Thread(target=self._render, daemon=True)
            self._thread.start()
        else:
            self.console.info(self.label)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.fail(str(exc))
        return None

    def _render(self) -> None:
        index = 0
        while not self._stop.is_set():
            frame = self.FRAMES[index % len(self.FRAMES)]
            text = f"\r{CYAN}{frame}{RESET} {self.label}"
            sys.stdout.write(text)
            sys.stdout.flush()
            time.sleep(0.1)
            index += 1

    def _finish(self, icon: str, color: str, message: str) -> None:
        if self.console.is_tty:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=0.5)
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
        self.console.emit(f"{color}{icon}{RESET} {message}")

    def success(self, message: str | None = None) -> None:
        self._finish("✓", GREEN, message or self.label)

    def fail(self, message: str | None = None) -> None:
        self._finish("✗", RED, message or self.label)

    def warn(self, message: str | None = None) -> None:
        self._finish("!", YELLOW, message or self.label)


@dataclass
class ConsoleReporter:
    stream: Any = sys.stdout

    @property
    def is_tty(self) -> bool:
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def emit(self, message: str = "") -> None:
        self.stream.write(f"{message}\n")
        self.stream.flush()

    def section(self, title: str) -> None:
        self.emit(f"{BOLD}{MAGENTA}{title}{RESET}")

    def info(self, message: str) -> None:
        self.emit(f"{BLUE}•{RESET} {message}")

    def success(self, message: str) -> None:
        self.emit(f"{GREEN}✓{RESET} {message}")

    def warn(self, message: str) -> None:
        self.emit(f"{YELLOW}!{RESET} {message}")

    def error(self, message: str) -> None:
        self.emit(f"{RED}✗{RESET} {message}")

    def detail(self, message: str) -> None:
        self.emit(f"{DIM}  {message}{RESET}")

    def spin(self, label: str) -> Spinner:
        return Spinner(self, label)

    def dump_json(self, payload: Any) -> None:
        self.emit(json.dumps(payload, indent=2))
