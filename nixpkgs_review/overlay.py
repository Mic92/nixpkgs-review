from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory


class Overlay:
    def __init__(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.path = Path(self.tempdir.name)

    def cleanup(self) -> None:
        self.tempdir.cleanup()
