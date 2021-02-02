import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from sys import platform
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional, Set

from .utils import ROOT, escape_attr, info, sh, warn


@dataclass
class Attr:
    name: str
    exists: bool
    broken: bool
    blacklisted: bool
    path: Optional[str]
    drv_path: Optional[str]
    aliases: List[str] = field(default_factory=lambda: [])
    _path_verified: Optional[bool] = field(init=False, default=None)

    def was_build(self) -> bool:
        if self.path is None:
            return False

        if self._path_verified is not None:
            return self._path_verified

        res = subprocess.run(
            ["nix-store", "--verify-path", self.path], stderr=subprocess.DEVNULL
        )
        self._path_verified = res.returncode == 0
        return self._path_verified

    def is_test(self) -> bool:
        return self.name.startswith("nixosTests")


def nix_shell(attrs: List[str], cache_directory: Path) -> None:
    shell = cache_directory.joinpath("shell.nix")
    write_shell_expression(shell, attrs)
    sh(["nix-shell", str(shell)], cwd=cache_directory, check=False)


def _nix_eval_filter(json: Dict[str, Any]) -> List[Attr]:
    # workaround https://github.com/NixOS/ofborg/issues/269
    blacklist = set(
        [
            "tests.nixos-functions.nixos-test",
            "tests.nixos-functions.nixosTest-test",
            "appimage-run-tests",
        ]
    )
    attr_by_path: Dict[str, Attr] = {}
    broken = []
    for name, props in json.items():
        attr = Attr(
            name=name,
            exists=props["exists"],
            broken=props["broken"],
            blacklisted=name in blacklist,
            path=props["path"],
            drv_path=props["drvPath"],
        )
        if attr.path is not None:
            other = attr_by_path.get(attr.path, None)
            if other is None:
                attr_by_path[attr.path] = attr
            else:
                if len(other.name) > len(attr.name):
                    attr_by_path[attr.path] = attr
                    attr.aliases.append(other.name)
                else:
                    other.aliases.append(attr.name)
        else:
            broken.append(attr)
    return list(attr_by_path.values()) + broken


def nix_eval(attrs: Set[str]) -> List[Attr]:
    attr_json = NamedTemporaryFile(mode="w+", delete=False)
    delete = True
    try:
        json.dump(list(attrs), attr_json)
        eval_script = str(ROOT.joinpath("nix/evalAttrs.nix"))
        attr_json.flush()
        cmd = [
            "nix",
            "--experimental-features",
            "nix-command",
            "eval",
            "--json",
            "--impure",
            "--expr",
            f"(import {eval_script} {attr_json.name})",
        ]

        try:
            nix_eval = subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, text=True
            )
        except subprocess.CalledProcessError:
            warn(
                f"{' '.join(cmd)} failed to run, {attr_json.name} was stored inspection"
            )
            delete = False
            raise

        return _nix_eval_filter(json.loads(nix_eval.stdout))
    finally:
        attr_json.close()
        if delete:
            os.unlink(attr_json.name)


def nix_build(attr_names: Set[str], args: str, cache_directory: Path) -> List[Attr]:
    if not attr_names:
        info("Nothing to be built.")
        return []

    attrs = nix_eval(attr_names)
    filtered = []
    for attr in attrs:
        if not (attr.broken or attr.blacklisted):
            filtered.append(attr.name)

    if len(filtered) == 0:
        return attrs

    build = cache_directory.joinpath("build.nix")
    write_shell_expression(build, filtered)

    command = [
        "nix",
        "--experimental-features",
        "nix-command",
        "build",
        "--no-link",
        "--keep-going",
    ]

    if platform == "linux":
        command += [
            # only matters for single-user nix and trusted users
            "--option",
            "build-use-sandbox",
            "relaxed",
        ]

    command += [
        "-f",
        str(build),
    ] + shlex.split(args)

    try:
        sh(command)
    except subprocess.CalledProcessError:
        pass
    return attrs


def write_shell_expression(filename: Path, attrs: List[str]) -> None:
    with open(filename, "w+") as f:
        f.write(
            """{ pkgs ? import ./nixpkgs {} }:
with pkgs;
let
  paths = [
"""
        )
        f.write("\n".join(f"        {escape_attr(a)}" for a in attrs))
        f.write(
            """
  ];
  env = buildEnv {
    name = "env";
    inherit paths;
    ignoreCollisions = true;
  };
in stdenv.mkDerivation rec {
  name = "review-shell";
  buildInputs = if builtins.length (paths) > 50 then paths else [ env ];
  unpackPhase = ":";
  installPhase = "touch $out";
}
"""
        )
