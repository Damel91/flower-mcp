"""Flow-owned structured logging.

The manager API and handler-lifecycle pattern are adapted from
``CodingCastle/src/core/logger.py`` (`LoggerManager.setup`, `get_logger`,
`close_session_logger` and `timed_op`). Flow keeps its own implementation and
does not import CodingCastle at runtime.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import re
import sys
import threading
import time

from flow_of_work_mcp.config import LoggingConfig


class LoggerManager:
    _instance: "LoggerManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.RLock()
        self._base_logger: logging.Logger | None = None
        self._logs_path: Path | None = None
        self._level = logging.INFO
        self._formatter = self._build_formatter()

    def setup(self, config: LoggingConfig) -> None:
        with self._lock:
            self.close()
            self._level = getattr(logging, config.level.upper(), logging.INFO)
            self._formatter = self._build_formatter()
            self._logs_path = config.logs_path
            self._logs_path.mkdir(parents=True, exist_ok=True)
            base = logging.getLogger("flow_of_work_mcp")
            base.setLevel(self._level)
            base.propagate = False
            if config.enable_console:
                # MCP stdio owns stdout. Operational logs must never corrupt
                # the JSON-RPC transport stream.
                console = logging.StreamHandler(sys.stderr)
                console.setLevel(self._level)
                console.setFormatter(self._formatter)
                base.addHandler(console)
            if not base.handlers:
                base.addHandler(logging.NullHandler())
            self._base_logger = base

    def _auto_init(self) -> None:
        if self._base_logger is not None:
            return
        base = logging.getLogger("flow_of_work_mcp")
        base.setLevel(self._level)
        base.propagate = False
        if not base.handlers:
            base.addHandler(logging.NullHandler())
        self._base_logger = base

    @staticmethod
    def _build_formatter() -> logging.Formatter:
        return logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s -> %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    @staticmethod
    def _sanitize(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", value)

    def get_logger(self, component: str | None = None, session_id: str | None = None) -> logging.Logger:
        with self._lock:
            self._auto_init()
            name = "flow_of_work_mcp"
            if component:
                name += f".{self._sanitize(component)}"
            if session_id:
                name += f".{self._sanitize(session_id)}"
            logger = logging.getLogger(name)
            logger.setLevel(self._level)
            if not session_id:
                logger.propagate = logger is not self._base_logger
                return logger
            logger.propagate = True
            if self._logs_path is not None and not any(
                getattr(handler, "_flow_managed", False) for handler in logger.handlers
            ):
                file_path = self._logs_path / f"{self._sanitize(session_id)}.log"
                handler = logging.FileHandler(file_path, encoding="utf-8")
                handler.setLevel(self._level)
                handler.setFormatter(self._formatter)
                handler._flow_managed = True  # type: ignore[attr-defined]
                logger.addHandler(handler)
            return logger

    def close_session_logger(self, session_id: str) -> None:
        suffix = f".{self._sanitize(session_id)}"
        with self._lock:
            for name, candidate in list(logging.Logger.manager.loggerDict.items()):
                if isinstance(candidate, logging.Logger) and name.endswith(suffix):
                    self._close_handlers(candidate, managed_only=True)

    def close(self) -> None:
        with self._lock:
            for name, candidate in list(logging.Logger.manager.loggerDict.items()):
                if isinstance(candidate, logging.Logger) and (
                    name == "flow_of_work_mcp" or name.startswith("flow_of_work_mcp.")
                ):
                    self._close_handlers(candidate, managed_only=False)
            self._base_logger = None

    @staticmethod
    def _close_handlers(logger: logging.Logger, *, managed_only: bool) -> None:
        for handler in logger.handlers[:]:
            if managed_only and not getattr(handler, "_flow_managed", False):
                continue
            try:
                handler.close()
            finally:
                logger.removeHandler(handler)


def get_logger(component: str | None = None, session_id: str | None = None) -> logging.Logger:
    return LoggerManager().get_logger(component, session_id)


def log_bootstrap_error(message: str) -> None:
    """Emit a safe stderr record when config is invalid before logger setup."""

    logger = logging.getLogger("flow_of_work_mcp.bootstrap")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(LoggerManager._build_formatter())
    logger.addHandler(handler)
    try:
        logger.error("configuration rejected: %s", message)
    finally:
        logger.removeHandler(handler)
        handler.close()


@contextmanager
def timed_op(logger: logging.Logger, operation: str, session_id: str = ""):
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        prefix = f"[{session_id}] " if session_id else ""
        logger.debug("%s%s completed in %dms", prefix, operation, elapsed_ms)
