from tempfile import TemporaryDirectory
from pathlib import Path


class Overlay:
    def __init__(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.path = Path(self.tempdir.name)

    def cleanup(self) -> None:
        self.tempdir.cleanup()
