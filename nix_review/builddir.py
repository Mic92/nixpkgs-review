import os
import shutil
import signal
from typing import Any, Union
from pathlib import Path
from tempfile import TemporaryDirectory

from .utils import sh, warn


class DisableKeyboardInterrupt:
    def __enter__(self) -> None:
        self.signal_received = False

        def handler(_sig: Any, _frame: Any) -> None:
            warn("Ignore Ctlr-C: Cleanup in progress... Don't be so impatient human!")

        self.old_handler = signal.signal(signal.SIGINT, handler)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        signal.signal(signal.SIGINT, self.old_handler)


def create_cache_directory(name: str) -> Union[Path, TemporaryDirectory]:
    xdg_cache_raw = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_raw is not None:
        xdg_cache = Path(xdg_cache_raw)
    home = os.environ.get("HOME", None)
    if home is None:
        # we are in a temporary directory
        return TemporaryDirectory()
    else:
        xdg_cache = Path(home).joinpath(".cache")
    cache_home = xdg_cache.joinpath("nix-review", name)
    cache_home.mkdir(parents=True, exist_ok=True)
    return cache_home


class Builddir:
    def __init__(self, name: str) -> None:
        self.environ = os.environ.copy()
        self.directory = create_cache_directory(name)
        if isinstance(self.directory, TemporaryDirectory):
            self.path = Path(self.directory.name)
        else:
            self.path = self.directory

        self.worktree_dir = self.path.joinpath("nixpkgs")

        try:
            os.makedirs(self.worktree_dir)
        except FileExistsError:
            warn(
                f"{self.worktree_dir} already exists. Is a different review already running?"
            )
            raise

        self.worktree_dir = self.worktree_dir

        os.environ["NIX_PATH"] = self.nixpkgs_path()

    def nixpkgs_path(self) -> str:
        return f"nixpkgs={self.worktree_dir}"

    def __enter__(self) -> "Builddir":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        os.environ.clear()
        os.environ.update(self.environ)

        with DisableKeyboardInterrupt():
            shutil.rmtree(self.worktree_dir)
            sh(["git", "worktree", "prune"])
