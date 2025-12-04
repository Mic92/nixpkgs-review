from __future__ import annotations

import concurrent.futures
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from sys import platform
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Final, Required, TypedDict, cast

from .errors import NixpkgsReviewError
from .utils import ROOT, System, info, sh, warn

if TYPE_CHECKING:
    from .allow import AllowedFeatures


@dataclass
class Attr:
    name: str
    exists: bool
    broken: bool
    blacklisted: bool
    path: Path | None
    drv_path: str | None
    aliases: list[str] = field(default_factory=list)
    _path_verified: bool | None = field(init=False, default=None)

    def was_build(self) -> bool:
        if self.path is None:
            return False

        if self._path_verified is not None:
            return self._path_verified

        res = subprocess.run(
            [
                "nix",
                "--extra-experimental-features",
                "nix-command",
                "store",
                "verify",
                "--no-contents",
                "--no-trust",
                self.path,
            ],
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._path_verified = res.returncode == 0
        return self._path_verified

    def is_test(self) -> bool:
        return self.name.startswith("nixosTests")


REVIEW_SHELL: Final[str] = str(ROOT.joinpath("nix/review-shell.nix"))


def nix_shell(
    attrs_per_system: dict[System, list[str]],
    cache_directory: Path,
    local_system: str,
    build_graph: str,
    nix_path: str,
    nixpkgs_wrapper: Path,
    nixpkgs_overlay: Path,
    run: str | None = None,
    *,
    sandbox: bool = False,
) -> None:
    nix_shell = shutil.which(build_graph + "-shell")
    if not nix_shell:
        msg = f"{build_graph} not found in PATH"
        raise RuntimeError(msg)

    shell_file_args = build_shell_file_args(
        cache_dir=cache_directory,
        attrs_per_system=attrs_per_system,
        local_system=local_system,
    )
    if sandbox:
        args = _nix_shell_sandbox(
            nix_shell,
            shell_file_args,
            cache_directory,
            nix_path,
            nixpkgs_wrapper,
            nixpkgs_overlay,
        )
    else:
        args = [nix_shell, *shell_file_args, "--nix-path", nix_path, REVIEW_SHELL]
    if run:
        args.extend(["--run", run])
    sh(args, cwd=cache_directory)


def _nix_shell_sandbox(
    nix_shell: str,
    shell_file_args: list[str],
    cache_directory: Path,
    nix_path: str,
    nixpkgs_wrapper: Path,
    nixpkgs_overlay: Path,
) -> list[str]:
    if platform != "linux":
        msg = "Sandbox mode is only available on Linux platforms."
        raise RuntimeError(msg)

    bwrap = shutil.which("bwrap")
    if not bwrap:
        msg = "bwrap not found in PATH. Install it to use '--sandbox' flag."
        raise RuntimeError(msg)

    warn("Using sandbox mode. Some things may break!")

    def bind(
        path: Path | str,
        *,
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

    def tmpfs(path: Path | str, *, is_dir: bool = True) -> list[str]:
        dir_cmd = []
        if is_dir:
            dir_cmd = ["--dir", str(path)]

        return [*dir_cmd, "--tmpfs", str(path)]

    nixpkgs_review_pr = cache_directory
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
        *tmpfs("/tmp"),  # noqa: S108
        # Required for evaluation
        *bind(nixpkgs_wrapper),
        *bind(nixpkgs_overlay),
        # /run (also cover sockets for wayland/pulseaudio and pipewires)
        *bind(Path("/run/user").joinpath(uid), dev=True, try_=True),
        # HOME
        *tmpfs(home),
        *bind(current_dir, ro=False),
        *bind(nixpkgs_review_pr, ro=False),
        *bind(nixpkgs_config_dir, try_=True),
        # For X11 applications
        *bind("/tmp/.X11-unix", try_=True),  # noqa: S108
        *bind(xauthority, try_=True),
        # GitHub
        *bind(hub_config, try_=True),
        *bind(gh_config, try_=True),
    ]
    return [
        bwrap,
        *bwrap_args,
        "--",
        nix_shell,
        *shell_file_args,
        "--nix-path",
        nix_path,
        REVIEW_SHELL,
    ]


class NixEvalProps(TypedDict):
    path: str | None
    exists: Required[bool]
    broken: Required[bool]
    drvPath: Required[str]


NixEvalResult = dict[str, NixEvalProps]


def _nix_eval_filter(json: NixEvalResult) -> list[Attr]:
    # workaround https://github.com/NixOS/ofborg/issues/269
    blacklist = {
        "appimage-run-tests",
        "darwin.builder",
        "nixos-install-tools",
        "tests.nixos-functions.nixos-test",
        "tests.nixos-functions.nixosTest-test",
        "tests.php.overrideAttrs-preserves-enabled-extensions",
        "tests.php.withExtensions-enables-previously-disabled-extensions",
        "tests.pkg-config.defaultPkgConfigPackages.tests-combined",
        "tests.trivial",
        "tests.writers",
    }
    attr_by_path: dict[Path, Attr] = {}
    broken = []
    for name, props in json.items():
        path_str = props.get("path")
        path = Path(path_str) if path_str is not None else None

        attr = Attr(
            name=name,
            exists=props["exists"],
            broken=props["broken"],
            blacklisted=name in blacklist,
            path=path,
            drv_path=props["drvPath"],
        )
        if attr.path is not None:
            if (other := attr_by_path.get(attr.path)) is None:
                attr_by_path[attr.path] = attr
            elif len(other.name) > len(attr.name):
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
    attr_json = NamedTemporaryFile(mode="w+", delete=False)  # noqa: SIM115
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

        nix_eval = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
        if nix_eval.returncode != 0:
            delete = False
            msg = (
                f"{' '.join(cmd)} failed to run, {attr_json.name} was stored inspection"
            )
            raise NixpkgsReviewError(msg)

        eval_result = json.loads(nix_eval.stdout)
        if not isinstance(eval_result, dict):
            msg = f"Expected eval result to be a dict, got {type(eval_result)}"
            raise TypeError(msg)
        return _nix_eval_filter(cast("NixEvalResult", eval_result))
    finally:
        attr_json.close()
        if delete:
            Path(attr_json.name).unlink()


def multi_system_eval(
    attr_names_per_system: dict[System, set[str]],
    allow: AllowedFeatures,
    nix_path: str,
    n_threads: int,
) -> dict[System, list[Attr]]:
    results: dict[System, list[Attr]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        future_to_system = {
            executor.submit(
                nix_eval,
                attrs=attrs,
                system=system,
                allow=allow,
                nix_path=nix_path,
            ): system
            for system, attrs in attr_names_per_system.items()
        }
        for future in concurrent.futures.as_completed(future_to_system):
            system = future_to_system[future]
            results[system] = future.result()

    return results


def nix_build(
    attr_names_per_system: dict[System, set[str]],
    args: str,
    cache_directory: Path,
    local_system: System,
    allow: AllowedFeatures,
    build_graph: str,
    nix_path: str,
    n_threads: int,
) -> dict[System, list[Attr]]:
    if not attr_names_per_system:
        info("Nothing to be built.")
        return {}

    attrs_per_system: dict[System, list[Attr]] = multi_system_eval(
        attr_names_per_system,
        allow,
        nix_path,
        n_threads=n_threads,
    )

    filtered_per_system = {
        system: [attr.name for attr in attrs if not (attr.broken or attr.blacklisted)]
        for system, attrs in attrs_per_system.items()
    }

    if all(len(filtered) == 0 for filtered in filtered_per_system.values()):
        return attrs_per_system

    command = [
        build_graph,
        "build",
        "--file",
        REVIEW_SHELL,
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

    command += build_shell_file_args(
        cache_dir=cache_directory,
        attrs_per_system=filtered_per_system,
        local_system=local_system,
    ) + shlex.split(args)

    sh(command)
    return attrs_per_system


def build_shell_file_args(
    cache_dir: Path,
    attrs_per_system: dict[System, list[str]],
    local_system: str,
) -> list[str]:
    attrs_file = cache_dir.joinpath("attrs.nix")
    with attrs_file.open("w+") as f:
        f.write("{\n")
        for system, attrs in attrs_per_system.items():
            f.write(f"  {system} = [\n")
            for attr in attrs:
                f.write(f'    "{attr}"\n')
            f.write("  ];\n")
        f.write("}")

    return [
        "--argstr",
        "local-system",
        local_system,
        "--argstr",
        "attrs-path",
        str(attrs_file),
    ]
