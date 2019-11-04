import os
import sys
from tempfile import NamedTemporaryFile
from typing import Any, Optional

from .utils import warn


def find_nixpkgs_root() -> Optional[str]:
    prefix = ["."]
    release_nix = ["nixos", "release.nix"]
    while True:
        root_path = os.path.join(*prefix)
        release_nix_path = os.path.join(root_path, *release_nix)
        if os.path.exists(release_nix_path):
            return root_path
        if os.path.abspath(root_path) == "/":
            return None
        prefix.append("..")


class Buildenv:
    def __enter__(self) -> None:
        self.environ = os.environ.copy()
        self.old_cwd = os.getcwd()

        root = find_nixpkgs_root()
        if root is None:
            warn("Has to be executed from nixpkgs repository")
            sys.exit(1)
        else:
            os.chdir(root)

        os.environ["GIT_AUTHOR_NAME"] = "nix-review"
        os.environ["GIT_AUTHOR_EMAIL"] = "nix-review@example.com"
        os.environ["GIT_COMMITTER_NAME"] = "nix-review"
        os.environ["GIT_COMMITTER_EMAIL"] = "nix-review@example.com"

        self.nixpkgs_config = NamedTemporaryFile()
        self.nixpkgs_config.write(b"{ allowUnfree = true; }")
        self.nixpkgs_config.flush()
        os.environ["NIXPKGS_CONFIG"] = self.nixpkgs_config.name

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        if self.old_cwd is not None:
            try:
                os.chdir(self.old_cwd)
            except OSError:  # could be deleted
                pass

        if self.environ is not None:
            os.environ.clear()
            os.environ.update(self.environ)

        if self.nixpkgs_config is not None:
            self.nixpkgs_config.close()
