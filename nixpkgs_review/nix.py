import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from sys import platform
from tempfile import NamedTemporaryFile
from typing import Any

from .allow import AllowedFeatures
from .errors import NixpkgsReviewError
from .utils import ROOT, escape_attr, info, sh, warn


@dataclass
class Attr:
    name: str
    exists: bool
    broken: bool
    blacklisted: bool
    path: str | None
    drv_path: str | None
    aliases: list[str] = field(default_factory=lambda: [])
    _path_verified: bool | None = field(init=False, default=None)

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


def nix_shell(
    attrs: list[str],
    cache_directory: Path,
    system: str,
    build_graph: str,
    nix_path: str,
    nixpkgs_config: Path,
    nixpkgs_overlay: Path,
    run: str | None = None,
    hook: str | None = None,
    sandbox: bool = False,
) -> None:
    nix_shell = f"{shutil.which(build_graph)}-shell"
    if not nix_shell:
        raise RuntimeError(f"{build_graph} not found in PATH")

    shell = cache_directory.joinpath("shell.nix")
    write_shell_expression(shell, attrs, system, nixpkgs_config)
    if sandbox:
        args = _nix_shell_sandbox(
            nix_shell, shell, nix_path, nixpkgs_config, nixpkgs_overlay
        )
    else:
        args = [nix_shell, str(shell), "--nix-path", nix_path]
    if run:
        args.extend(["--run", run])
    sh(args, cwd=cache_directory)


def _nix_shell_sandbox(
    nix_shell: str,
    shell: Path,
    nix_path: str,
    nixpkgs_config: Path,
    nixpkgs_overlay: Path,
) -> list[str]:
    if platform != "linux":
        raise RuntimeError("Sandbox mode is only available on Linux platforms.")

    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError(
            "bwrap not found in PATH. Install it to use '--sandbox' flag."
        )

    warn("Using sandbox mode. Some things may break!")

    def bind(
        path: Path | str,
        ro: bool = True,
        dev: bool = False,
        try_: bool = False,
    ) -> list[str]:
        if dev:
            prefix = "--dev-"
        elif ro:
            prefix = "--ro-"
        else:
            prefix = "--"

        suffix = "-try" if try_ else ""

        return [prefix + "bind" + suffix, str(path), str(path)]

    def tmpfs(path: Path | str, dir: bool = True) -> list[str]:
        dir_cmd = []
        if dir:
            dir_cmd = ["--dir", str(path)]

        return [*dir_cmd, "--tmpfs", str(path)]

    nixpkgs_review_pr = shell.parent
    home = Path.home()
    current_dir = Path().absolute()
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", home.joinpath(".config")))
    nixpkgs_config_dir = xdg_config_home.joinpath("nixpkgs")
    xauthority = Path(os.environ.get("XAUTHORITY", home.joinpath(".Xauthority")))
    hub_config = xdg_config_home.joinpath("hub")
    gh_config = xdg_config_home.joinpath("gh")

    uid = os.environ.get("UID", "1000")

    bwrap_args = [
        "--die-with-parent",
        "--unshare-cgroup",
        "--unshare-ipc",
        "--unshare-uts",
        # / and cia.
        *bind("/"),
        *bind("/dev", dev=True),
        *tmpfs("/tmp"),
        # Required for evaluation
        *bind(nixpkgs_config),
        *bind(nixpkgs_overlay),
        # /run (also cover sockets for wayland/pulseaudio and pipewires)
        *bind(Path("/run/user").joinpath(uid), dev=True, try_=True),
        # HOME
        *tmpfs(home),
        *bind(current_dir, ro=False),
        *bind(nixpkgs_review_pr, ro=False),
        *bind(nixpkgs_config_dir, try_=True),
        # For X11 applications
        *bind("/tmp/.X11-unix", try_=True),
        *bind(xauthority, try_=True),
        # GitHub
        *bind(hub_config, try_=True),
        *bind(gh_config, try_=True),
    ]
    return [bwrap, *bwrap_args, "--", nix_shell, str(shell), "--nix-path", nix_path]


def _nix_eval_filter(json: dict[str, Any]) -> list[Attr]:
    # workaround https://github.com/NixOS/ofborg/issues/269
    blacklist = set(
        [
            "appimage-run-tests",
            "darwin.builder",
            "nixos-install-tools",
            "tests.nixos-functions.nixos-test",
            "tests.nixos-functions.nixosTest-test",
            "tests.php.overrideAttrs-preserves-enabled-extensions",
            "tests.php.withExtensions-enables-previously-disabled-extensions",
            "tests.trivial",
            "tests.writers",
        ]
    )
    attr_by_path: dict[str, Attr] = {}
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


def nix_eval(
    attrs: set[str],
    system: str,
    allow: AllowedFeatures,
    nix_path: str,
) -> list[Attr]:
    attr_json = NamedTemporaryFile(mode="w+", delete=False)
    delete = True
    try:
        json.dump(list(attrs), attr_json)
        eval_script = str(ROOT.joinpath("nix/evalAttrs.nix"))
        attr_json.flush()
        cmd = [
            "nix",
            "--extra-experimental-features",
            "nix-command" if allow.url_literals else "nix-command no-url-literals",
            "--system",
            system,
            "eval",
            "--nix-path",
            nix_path,
            "--json",
            "--impure",
            "--allow-import-from-derivation"
            if allow.ifd
            else "--no-allow-import-from-derivation",
            "--expr",
            f"(import {eval_script} {{ attr-json = {attr_json.name}; }})",
        ]

        nix_eval = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
        if nix_eval.returncode != 0:
            delete = False
            raise NixpkgsReviewError(
                f"{' '.join(cmd)} failed to run, {attr_json.name} was stored inspection"
            )

        return _nix_eval_filter(json.loads(nix_eval.stdout))
    finally:
        attr_json.close()
        if delete:
            os.unlink(attr_json.name)


def nix_build(
    attr_names: set[str],
    args: str,
    cache_directory: Path,
    system: str,
    allow: AllowedFeatures,
    build_graph: str,
    nix_path: str,
    nixpkgs_config: Path,
) -> list[Attr]:
    if not attr_names:
        info("Nothing to be built.")
        return []

    attrs = nix_eval(attr_names, system, allow, nix_path)
    filtered = []
    for attr in attrs:
        if not (attr.broken or attr.blacklisted):
            filtered.append(attr.name)

    if len(filtered) == 0:
        return attrs

    build = cache_directory.joinpath("build.nix")
    write_shell_expression(build, filtered, system, nixpkgs_config)

    command = [
        build_graph,
        "build",
        "--nix-path",
        nix_path,
        "--extra-experimental-features",
        "nix-command" if allow.url_literals else "nix-command no-url-literals",
        "--no-link",
        "--keep-going",
        "--allow-import-from-derivation"
        if allow.ifd
        else "--no-allow-import-from-derivation",
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

    sh(command)
    return attrs


def write_shell_expression(
    filename: Path, attrs: list[str], system: str, nixpkgs_config: Path
) -> None:
    with open(filename, "w+") as f:
        f.write(
            f"""{{ pkgs ? import ./nixpkgs {{ system = \"{system}\"; config = import {nixpkgs_config}; }} }}:
with pkgs;
let
  paths = [
"""
        )
        f.write("\n".join(f"    {escape_attr(a)}" for a in attrs))
        f.write(
            """
  ];
  env = buildEnv {
    name = "env";
    inherit paths;
    ignoreCollisions = true;
  };
in (import ./nixpkgs { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  packages = if builtins.length paths > 50 then [ env ] else paths;
}
"""
        )
