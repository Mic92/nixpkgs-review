import os
from tempfile import NamedTemporaryFile
from typing import Any


class Buildenv:
    def __enter__(self) -> None:
        self.environ = os.environ.copy()

        os.environ["GIT_AUTHOR_NAME"] = "nix-review"
        os.environ["GIT_AUTHOR_EMAIL"] = "nix-review@example.com"
        os.environ["GIT_COMMITTER_NAME"] = "nix-review"
        os.environ["GIT_COMMITTER_EMAIL"] = "nix-review@example.com"

        self.nixpkgs_config = NamedTemporaryFile()
        self.nixpkgs_config.write(b"pkgs: { allowUnfree = true; }")
        self.nixpkgs_config.flush()
        os.environ["NIXPKGS_CONFIG"] = self.nixpkgs_config.name

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        if self.environ is not None:
            os.environ.clear()
            os.environ.update(self.environ)

        if self.nixpkgs_config is not None:
            self.nixpkgs_config.close()
