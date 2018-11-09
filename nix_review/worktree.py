import os
import shutil
import signal
from typing import Any, Optional

from .utils import sh, warn


class DisableKeyboardInterrupt:
    def __enter__(self) -> None:
        self.signal_received = False

        def handler(_sig: Any, _frame: Any) -> None:
            warn("Ignore Ctlr-C: Cleanup in progress... Don't be so impatient human!")

        self.old_handler = signal.signal(signal.SIGINT, handler)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        signal.signal(signal.SIGINT, self.old_handler)


class Worktree:
    def __init__(self, name: str) -> None:
        self.environ = os.environ.copy()
        worktree_dir = os.path.join("./.review", name)
        try:
            os.makedirs(worktree_dir)
        except FileExistsError:
            warn(
                f"{worktree_dir} already exists. Is a different review already running?"
            )
            raise

        self.worktree_dir = worktree_dir

        os.environ["NIX_PATH"] = f"nixpkgs={os.path.realpath(self.worktree_dir)}"

    def __enter__(self) -> str:
        return self.worktree_dir

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        os.environ.clear()
        os.environ.update(self.environ)

        with DisableKeyboardInterrupt():
            shutil.rmtree(self.worktree_dir)
            sh(["git", "worktree", "prune"])
