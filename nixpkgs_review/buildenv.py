import os
import sys
from pathlib import Path
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
    def __init__(self, allow_aliases: bool, extra_nixpkgs_config: str) -> None:
        if not (
            extra_nixpkgs_config.startswith("{") and extra_nixpkgs_config.endswith("}")
        ):
            raise RuntimeError(
                "--extra-nixpkgs-config must start with `{` and end with `}`"
            )

        self.nixpkgs_config = NamedTemporaryFile(suffix=".nix")
        self.nixpkgs_config.write(
            str.encode(
                f"""{{
  allowUnfree = true;
  allowBroken = true;
  {"allowAliases = false;" if not allow_aliases else ""}
  checkMeta = true;
  ## TODO: also build packages marked as insecure
  # allowInsecurePredicate = x: true;
}} // {extra_nixpkgs_config}
"""
            )
        )
        self.nixpkgs_config.flush()

    def __enter__(self) -> Path:
        self.environ = os.environ.copy()
        self.old_cwd = os.getcwd()

        root = find_nixpkgs_root()
        if root is None:
            warn("Has to be executed from nixpkgs repository")
            sys.exit(1)
        else:
            os.chdir(root)

        os.environ["NIXPKGS_CONFIG"] = self.nixpkgs_config.name
        return Path(self.nixpkgs_config.name)

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
