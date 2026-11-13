"""Process-level plumbing: single-instance lock and secret-redacting logs."""
from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..config.settings import ENV_PREFIX


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """An exclusive lock file holding the owner's PID; a dead owner's lock is taken over."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._owner_alive():
                    raise AlreadyRunning(f"another run holds {self.path}") from None
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {datetime.now(UTC).isoformat()}")
            self._held = True
            return self
        raise AlreadyRunning(f"could not take {self.path}")

    def __exit__(self, *exc):
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def _owner_alive(self) -> bool:
        try:
            pid = int(self.path.read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return False
        return _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


_KEY_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{16,})"),
    re.compile(r"(AIza[0-9A-Za-z_\-]{20,})"),
    re.compile(r"((?:api[_-]?key|token|authorization)[\"']?\s*[:=]\s*[\"']?(?:Bearer\s+)?)([^\s\"'&]+)", re.I),
]


def redact(text: str) -> str:
    """``text`` with API keys and the values of secret env vars masked."""
    for name, value in os.environ.items():
        if value and len(value) >= 8 and (name.endswith(("_KEY", "_TOKEN", "_SECRET")) or name.startswith(ENV_PREFIX)
                                          and "KEY" in name):
            text = text.replace(value, "***")
    for pattern in _KEY_PATTERNS:
        if pattern.groups == 2:
            text = pattern.sub(lambda m: m.group(1) + "***", text)
        else:
            text = pattern.sub("***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging(logs_dir: str, verbose: bool = False) -> Path:
    """Log to logs/independent_agent.log (rotating) and stderr, with secrets masked."""
    path = Path(logs_dir) / "independent_agent.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, "_independent_agent", False):
            root.removeHandler(handler)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    for handler in (file_handler, console):
        handler.setFormatter(fmt)
        handler.addFilter(RedactingFilter())
        handler._independent_agent = True
        root.addHandler(handler)
    for noisy in ("yfinance", "urllib3", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path
