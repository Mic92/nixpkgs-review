import os
import shutil
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Union

from .overlay import Overlay
from .utils import sh, warn


class DisableKeyboardInterrupt:
    def __enter__(self) -> None:
        self.signal_received = False

        def handler(_sig: Any, _frame: Any) -> None:
            warn("Ignore Ctrl-C: Cleanup in progress... Don't be so impatient, human!")

        self.old_handler = signal.signal(signal.SIGINT, handler)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        signal.signal(signal.SIGINT, self.old_handler)


def create_cache_directory(name: str) -> Union[Path, "TemporaryDirectory[str]"]:
    xdg_cache_raw = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_raw is not None:
        xdg_cache = Path(xdg_cache_raw)
    else:
        home = os.environ.get("HOME", None)
        if home is None:
            # we are in a temporary directory
            return TemporaryDirectory()
        else:
            xdg_cache = Path(home).joinpath(".cache")

    counter = 0
    while True:
        try:
            final_name = name if counter == 0 else f"{name}-{counter}"
            cache_home = xdg_cache.joinpath("nixpkgs-review", final_name)
            cache_home.mkdir(parents=True)
            return cache_home
        except FileExistsError:
            counter += 1


class Builddir:
    def __init__(self, name: str) -> None:
        self.environ = os.environ.copy()
        self.directory = create_cache_directory(name)
        if isinstance(self.directory, TemporaryDirectory):
            self.path = Path(self.directory.name)
        else:
            self.path = self.directory

        self.overlay = Overlay()

        self.worktree_dir = self.path.joinpath("nixpkgs")
        self.worktree_dir.mkdir()
        nix_path = [
            f"nixpkgs={self.worktree_dir}",
            f"nixpkgs-overlays={self.overlay.path}",
        ]
        # we don't actually use this, but its handy for users who want to try out things with the current nixpkgs version.
        os.environ["NIX_PATH"] = ":".join(nix_path)
        self.nix_path = " ".join(nix_path)

        self.nix_path = (
            f"nixpkgs={self.worktree_dir} nixpkgs-overlays={self.overlay.path}"
        )

    def __enter__(self) -> "Builddir":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        os.environ.clear()
        os.environ.update(self.environ)

        with DisableKeyboardInterrupt():
            shutil.rmtree(self.worktree_dir)
            sh(["git", "worktree", "prune"])

        self.overlay.cleanup()
