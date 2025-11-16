from __future__ import annotations

import os
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Self

from .overlay import Overlay
from .utils import warn

if TYPE_CHECKING:
    import types


class DisableKeyboardInterrupt:
    def __enter__(self) -> None:
        self.signal_received = False

        def handler(_sig: int, _frame: types.FrameType | None) -> None:
            warn("Ignore Ctrl-C: Cleanup in progress... Don't be so impatient, human!")

        self.old_handler = signal.signal(signal.SIGINT, handler)

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: types.TracebackType | None,
    ) -> None:
        signal.signal(signal.SIGINT, self.old_handler)


def create_cache_directory(name: str) -> Path | TemporaryDirectory[str]:
    if app_cache_dir := os.environ.get("NIXPKGS_REVIEW_CACHE_DIR"):
        xdg_cache = Path(app_cache_dir)
    elif xdg_cache_raw := os.environ.get("XDG_CACHE_HOME"):
        xdg_cache = Path(xdg_cache_raw)
    elif home := os.environ.get("HOME"):
        xdg_cache = Path(home) / ".cache"
    else:
        # we are in a temporary directory
        return TemporaryDirectory()

    # There is no guarantee that environment variables are set to absolute paths.
    xdg_cache = xdg_cache.absolute()

    for counter in range(1000):  # Prevent infinite loop
        final_name = name if counter == 0 else f"{name}-{counter}"
        cache_home = xdg_cache / "nixpkgs-review" / final_name
        try:
            cache_home.mkdir(parents=True)
        except FileExistsError:
            continue
        else:
            return cache_home
    msg = f"Could not create cache directory after 1000 attempts: {name}"
    raise RuntimeError(msg)


class Builddir:
    def __init__(self, name: str) -> None:
        self.environ = os.environ.copy()
        self.directory = create_cache_directory(name)
        self._temp_directory: TemporaryDirectory[str] | None = None
        if isinstance(self.directory, TemporaryDirectory):
            self._temp_directory = self.directory
            self.path = Path(self.directory.name)
        else:
            self.path = self.directory

        self.overlay = Overlay()

        self.clone_dir = self.path / "nixpkgs"
        self.clone_dir.mkdir()
        self._nix_path_parts = [
            f"nixpkgs={self.clone_dir}",
            f"nixpkgs-overlays={self.overlay.path}",
        ]
        self.nix_path = " ".join(self._nix_path_parts)

    def __enter__(self) -> Self:
        # we don't actually use this, but its handy for users who want to try out things with the current nixpkgs version.
        os.environ["NIX_PATH"] = ":".join(self._nix_path_parts)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        os.environ.clear()
        os.environ.update(self.environ)

        self.overlay.cleanup()

        # Clean up the temporary directory if we created one
        if self._temp_directory is not None:
            self._temp_directory.cleanup()
