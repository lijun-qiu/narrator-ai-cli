"""Local workspace paths — temp dirs on same drive as data_dir (avoids WinError 17)."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

from gateway.config import settings


@contextmanager
def work_directory(prefix: str = "work_"):
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=settings.temp_dir) as tmp:
        yield Path(tmp)
