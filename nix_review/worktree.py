import os
import shutil
import signal
from tempfile import NamedTemporaryFile
from typing import Any, Optional

from .utils import sh


class DisableKeyboardInterrupt:
    def __enter__(self) -> None:
        self.signal_received = False

        def handler(_sig: Any, _frame: Any) -> None:
            print("Ignore Ctlr-C: Cleanup in progress... Don't be so impatient human!")

        self.old_handler = signal.signal(signal.SIGINT, handler)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        signal.signal(signal.SIGINT, self.old_handler)


class Worktree:
    def __init__(self, name: str) -> None:
        worktree_dir = os.path.join("./.review", name)
        try:
            os.makedirs(worktree_dir)
        except FileExistsError:
            print(
                f"{worktree_dir} already exists. Is a different review already running?"
            )
            raise
        self.worktree_dir: Optional[str] = worktree_dir
        self.nixpkgs_config = NamedTemporaryFile()
        self.nixpkgs_config.write(b"pkgs: { allowUnfree = true; }")
        self.nixpkgs_config.flush()

        self.environ = os.environ.copy()
        os.environ["NIXPKGS_CONFIG"] = self.nixpkgs_config.name
        os.environ["NIX_PATH"] = f"nixpkgs={os.path.realpath(worktree_dir)}"
        os.environ["GIT_AUTHOR_NAME"] = "nix-review"
        os.environ["GIT_AUTHOR_EMAIL"] = "nix-review@example.com"
        os.environ["GIT_COMMITTER_NAME"] = "nix-review"
        os.environ["GIT_COMMITTER_EMAIL"] = "nix-review@example.com"

    def __enter__(self) -> str:
        assert self.worktree_dir is not None
        return self.worktree_dir

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.nixpkgs_config is not None:
            self.nixpkgs_config.close()

        if self.environ is not None:
            os.environ.update(self.environ)

        if self.worktree_dir is None:
            return

        with DisableKeyboardInterrupt():
            shutil.rmtree(self.worktree_dir)
            sh(["git", "worktree", "prune"])
            os.environ.clear()
