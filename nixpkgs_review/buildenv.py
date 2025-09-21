from __future__ import annotations

import contextlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from .utils import die

if TYPE_CHECKING:
    import types


def find_nixpkgs_root() -> Path | None:
    root_path = Path()
    while True:
        if (root_path / "nixos" / "release.nix").exists():
            return root_path
        if root_path == root_path.parent:
            return None
        root_path = root_path.parent


class Buildenv:
    def __init__(self, allow_aliases: bool, extra_nixpkgs_config: str) -> None:
        if not (
            extra_nixpkgs_config.startswith("{") and extra_nixpkgs_config.endswith("}")
        ):
            msg = "--extra-nixpkgs-config must start with `{` and end with `}`"
            raise RuntimeError(msg)

        self.nixpkgs_config = NamedTemporaryFile(suffix=".nix")  # noqa: SIM115
        aliases_config = "allowAliases = false;" if not allow_aliases else ""
        config_content = f"""{{
  allowUnfree = true;
  allowBroken = true;
  {aliases_config}
  checkMeta = true;
  ## TODO: also build packages marked as insecure
  # allowInsecurePredicate = x: true;
}} // {extra_nixpkgs_config}
"""
        self.nixpkgs_config.write(config_content.encode())
        self.nixpkgs_config.flush()

    def __enter__(self) -> Path:
        self.environ = os.environ.copy()
        self.old_cwd = Path.cwd()

        if (root := find_nixpkgs_root()) is None:
            die("Has to be executed from nixpkgs repository")
        os.chdir(root)

        os.environ["NIXPKGS_CONFIG"] = self.nixpkgs_config.name
        return Path(self.nixpkgs_config.name)

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: types.TracebackType | None,
    ) -> None:
        if self.old_cwd is not None:
            with contextlib.suppress(OSError):
                os.chdir(self.old_cwd)

        if self.environ is not None:
            os.environ.clear()
            os.environ.update(self.environ)

        if self.nixpkgs_config is not None:
            self.nixpkgs_config.close()
