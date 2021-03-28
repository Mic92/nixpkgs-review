import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
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
    skipped: bool
    path: Optional[str]
    drv_path: Optional[str]
    position: Optional[str]
    log_url: Optional[str] = field(default=None)
    aliases: List[str] = field(default_factory=lambda: [])
    timed_out: bool = field(default=False)
    build_err_msg: Optional[str] = field(default=None)
    _path_verified: Optional[bool] = field(init=False, default=None)

    def was_build(self) -> bool:
        if self.path is None:
            return False

        if self.skipped:
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

    def log(self, tail: int = -1, strip_colors: bool = False) -> Optional[str]:
        def get_log(path: Optional[str]) -> Optional[str]:
            if path is None:
                return None
            system = subprocess.run(
                ["nix", "--experimental-features", "nix-command", "log", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
            )
            stdout = system.stdout
            if tail > 0 and len(stdout) > tail:
                stdout = "This file has been truncated\n" + stdout[-tail:]

            if strip_colors:
                return strip_ansi_colors(stdout)
            return stdout

        if self.drv_path is None:
            return None

        value = get_log(self.drv_path) or get_log(self.path) or ""
        if self.build_err_msg is not None:
            value = "\n".join([value, self.build_err_msg])

        return value

    def log_path(self) -> Optional[str]:
        if self.drv_path is None:
            return None
        base = os.path.basename(self.drv_path)

        # TODO: On non-default configurations of nix, the logs
        # could be stored in a different directory. We lack a
        # robust way to discover this, which will prevent this
        # function from finding the path (currently used only to
        # determine the build time).
        prefix = "/nix/var/log/nix/drvs/"
        candidate_paths = (
            os.path.join(prefix, base[:2], base[2:] + ".bz2"),
            os.path.join(prefix, base[:2], base[2:]),
        )
        for path in candidate_paths:
            if os.path.isfile(path):
                return path
        return None

    def build_time(self) -> Optional[timedelta]:
        log_path = self.log_path()
        if log_path is None:
            return None

        proc = subprocess.run(
            ["stat", "--format", "%W %Y", log_path],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode == 0:
            birthtime, mtime = map(int, proc.stdout.split())
            if birthtime != 0:
                return timedelta(seconds=(mtime - birthtime))
        return None


def nix_shell(
    attrs: List[str],
    cache_directory: Path,
    system: str,
    run: Optional[str] = None,
) -> None:
    shell = cache_directory.joinpath("shell.nix")
    write_shell_expression(shell, attrs, system)
    args = ["nix-shell", str(shell)]
    if run:
        args.extend(["--run", run])
    sh(args, cwd=cache_directory, check=False)


def _nix_eval_filter(json: Dict[str, Any]) -> List[Attr]:
    # workaround https://github.com/NixOS/ofborg/issues/269
    blacklist = set(
        [
            "tests.nixos-functions.nixos-test",
            "tests.nixos-functions.nixosTest-test",
            "tests.writers",
            "appimage-run-tests",
            "tests.trivial",
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
            skipped=False,
            path=props["path"],
            drv_path=props["drvPath"],
            position=props["position"] if props["position"] is not None else None,
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


def nix_eval(
    attrs: Set[str], system: str, cache_directory: Optional[Path] = None
) -> List[Attr]:
    def _eval(attrs: List[str]) -> Dict[str, Any]:
        attr_json = NamedTemporaryFile(mode="w+", delete=False)
        delete = True
        try:
            json.dump(attrs, attr_json)
            eval_script = str(ROOT.joinpath("nix/evalAttrs.nix"))
            attr_json.flush()
            cmd = [
                "nix",
                "--experimental-features",
                "nix-command",
                "eval",
                "--json",
                "--system",
                system,
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

            return json.loads(nix_eval.stdout)
        finally:
            attr_json.close()
            if delete:
                os.unlink(attr_json.name)

    #
    # Split the evaluation into chunks of 4096 attrs at a time.
    # This helps limit the memory usage, which can be a problem.
    #
    start_time = time.time()
    eval_data = {}
    attrlist = sorted(attrs)
    MAX_ATTRS_AT_ONCE = 4096

    for i in range(0, len(attrs), MAX_ATTRS_AT_ONCE):
        chunk = attrlist[i : i + MAX_ATTRS_AT_ONCE]
        eval_data.update(_eval(chunk))

    if cache_directory is not None:
        # This information contains a lot of details about each attr, and may
        # be used by scripts that run inside the nixpkgs-review shell.
        with open(cache_directory.joinpath("changed-attrs.json"), "w") as f:
            json.dump(eval_data, f)

    if time.time() - start_time > 30:
        info(f"Time required for nix eval: {time.time() - start_time:.0f} sec")

    return _nix_eval_filter(eval_data)


def nix_build(
    attr_names: Set[str],
    args: str,
    cache_directory: Path,
    system: str,
) -> List[Attr]:
    if not attr_names:
        info("Nothing to be built.")
        return []

    attrs = nix_eval(attr_names, system=system, cache_directory=cache_directory)
    attrs = pre_build_filter(attrs, cache_directory=cache_directory)
    filtered = []
    for attr in attrs:
        if not (attr.broken or attr.blacklisted or attr.skipped):
            filtered.append(attr.name)

    if len(filtered) == 0:
        return attrs

    build = cache_directory.joinpath("build.nix")
    write_shell_expression(build, filtered, system)

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
        proc = sh(command, stderr=subprocess.PIPE)
        stderr = proc.stderr
    except subprocess.CalledProcessError as e:
        stderr = e.stderr

    # Remove boring 'copying path' lines from stderr
    nix_store = _store_dir()
    stderr = "\n".join(
        line
        for line in stderr.splitlines()
        if not (line.startswith("copying path '") and line.endswith("..."))
    )

    has_failed_dependencies = []
    has_timeout = {}
    for line in stderr.splitlines():
        if "dependencies couldn't be built" in line:
            has_failed_dependencies.append(
                next(item for item in line.split() if nix_store in item)
                .lstrip("'")
                .rstrip(":'")
            )
        if "timed out after" in line:
            drv = next(item for item in line.split() if nix_store in item).strip("'")
            has_timeout[drv] = line

    drv_path_to_attr = {a.drv_path: a for a in attrs}
    for drv_path in has_timeout.keys():
        if drv_path in drv_path_to_attr:
            attr = drv_path_to_attr[drv_path]
            attr.build_err_msg = has_timeout[drv_path]
            attr.timed_out = True

    for drv_path in has_failed_dependencies:
        if drv_path in drv_path_to_attr:
            attr = drv_path_to_attr[drv_path]
            attr.build_err_msg = stderr

            # Without inspecting the build graph, let's just guess
            # that if something failed to build and there were ANY timeouts
            # that it's probably the case that this failure to build
            # was probably caused by the timeout.
            # e.g. https://github.com/NixOS/nixpkgs/pull/114609
            if len(has_timeout) > 0:
                attr.timed_out = True

    return attrs


def pre_build_filter(attrs: List[Attr], cache_directory: Path) -> List[Attr]:
    for cmd in (
        cmd
        for cmd in os.environ.get("NIXPKGS_REVIEW_PRE_BUILD_FILTER", "").split(":")
        if cmd
    ):
        encoded = json.dumps(
            {
                "attrs": [attr.__dict__ for attr in attrs],
            }
        )
        p = sh(
            [cmd],
            input=encoded,
            stdout=subprocess.PIPE,
            stderr=sys.stdout,
            cwd=cache_directory.as_posix(),
        )
        attrs = [Attr(**arg) for arg in json.loads(p.stdout)]
    return attrs


def write_shell_expression(filename: Path, attrs: List[str], system: str) -> None:
    with open(filename, "w+") as f:
        f.write(
            f"""{{ pkgs ? import ./nixpkgs {{ system = \"{system}\"; }} }}:
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
  buildInputs = if builtins.length paths > 50 then [ env ] else paths;
  unpackPhase = ":";
  installPhase = "touch $out";
}
"""
        )


def strip_ansi_colors(s: str) -> str:
    # https://stackoverflow.com/a/14693789/1079728
    # 7-bit C1 ANSI sequences
    ansi_escape = re.compile(
        r"""
        \x1B  # ESC
        (?:   # 7-bit C1 Fe (except CSI)
            [@-Z\\-_]
        |     # or [ for CSI, followed by a control sequence
            \[
            [0-?]*  # Parameter bytes
            [ -/]*  # Intermediate bytes
            [@-~]   # Final byte
        )
    """,
        re.VERBOSE,
    )
    return ansi_escape.sub("", s)


def _store_dir() -> str:
    return subprocess.check_output(
        [
            "nix",
            "--experimental-features",
            "nix-command",
            "eval",
            "--raw",
            "--expr",
            "(builtins.storeDir)",
        ],
        text=True,
    )
