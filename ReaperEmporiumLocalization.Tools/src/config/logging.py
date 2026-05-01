from __future__ import annotations

import datetime as _dt
import sys

from loguru import logger as _logger
from tqdm.auto import tqdm

from .configuration import settings
from .paths import paths


def _tqdm_sink(message) -> None:
    text = str(message).rstrip("\n")
    if not text:
        return
    try:
        tqdm.write(text)
    except Exception:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

paths.ensure_base_dirs()

_logger.remove()
_logger.add(_tqdm_sink, format=settings.project.log_format, colorize=True, level=settings.project.log_level)
_logger.add(
    paths.logs / f"{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
    level="INFO",
    encoding="utf-8",
)

logger = _logger


__all__ = ["logger"]
