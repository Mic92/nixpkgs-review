import json
import multiprocessing
import shlex
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List, Optional, Set

from .utils import ROOT, info, sh


class Attr:
    def __init__(
        self,
        name: str,
        exists: bool,
        broken: bool,
        blacklisted: bool,
        path: Optional[str],
    ) -> None:
        self.name = name
        self.exists = exists
        self.broken = broken
        self.blacklisted = blacklisted
        self.path = path
        self._path_verified: Optional[bool] = None

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
    if len(attrs) == 0:
        info("No packages were successfully build, skip nix-shell")
    else:
        shell = cache_directory.joinpath("shell.nix")
        write_shell_expression(shell, attrs)
        sh(["nix-shell", str(shell)], cwd=cache_directory)


def nix_eval(attrs: Set[str]) -> List[Attr]:
    """
    Filter broken or non-existing attributes.
    """
    with NamedTemporaryFile(mode="w+") as attr_json:
        json.dump(list(attrs), attr_json)
        eval_script = str(ROOT.joinpath("nix/evalAttrs.nix"))
        attr_json.flush()
        cmd = ["nix", "eval", "--json", f"(import {eval_script} {attr_json.name})"]
        # workaround https://github.com/NixOS/ofborg/issues/269
        blacklist = set(
            ["tests.nixos-functions.nixos-test", "tests.nixos-functions.nixosTest-test"]
        )

        results = []
        nix_eval = subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
        for name, props in json.loads(nix_eval.stdout).items():
            attr = Attr(
                name=name,
                exists=props["exists"],
                broken=props["broken"],
                blacklisted=name in blacklist,
                path=props["path"],
            )
            results.append(attr)
        return results


def nix_build(attr_names: Set[str], args: str, cache_directory: Path) -> List[Attr]:
    if not attr_names:
        info("Nothing changed")
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
        "build",
        "--keep-going",
        # only matters for single-user nix and trusted users
        "--max-jobs",
        str(multiprocessing.cpu_count()),
        "--option",
        "build-use-sandbox",
        "true",
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
            """with import <nixpkgs> {};
stdenv.mkDerivation {
  name = "env";
  buildInputs = [
"""
        )
        f.write("\n".join(f"    {a}" for a in attrs))
        f.write(
            """
  ];
  unpackPhase = ":";
  installPhase = "touch $out";
}
"""
        )
