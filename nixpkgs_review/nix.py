from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from sys import platform
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Final, NotRequired, TypedDict

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
    outputs: dict[str, Path] | None
    drv_path: Path | None
    aliases: list[str] = field(default_factory=list)
    _path_verified: bool | None = field(init=False, default=None)

    def was_build(self) -> bool:
        if self.outputs is None or len(self.outputs) == 0:
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
                *self.outputs.values(),
            ],
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._path_verified = res.returncode == 0
        return self._path_verified

    def is_test(self) -> bool:
        return self.name.startswith("nixosTests")

    def outputs_with_name(self) -> dict[str, Path]:
        def with_output(output: str) -> str:
            if output == "out":
                return self.name
            return f"{self.name}.{output}"

        return {
            with_output(output): path for output, path in (self.outputs or {}).items()
        }


REVIEW_SHELL: Final[str] = str(ROOT.joinpath("nix/review-shell.nix"))


def _nix_common_flags(allow: AllowedFeatures, nix_path: str) -> list[str]:
    return [
        "--extra-experimental-features",
        "nix-command" if allow.url_literals else "nix-command no-url-literals",
        "--nix-path",
        nix_path,
        "--allow-import-from-derivation"
        if allow.ifd
        else "--no-allow-import-from-derivation",
    ]


def nix_shell(
    attrs_per_system: dict[System, list[Attr]],
    cache_directory: Path,
    build_graph: str,
    nix_path: str,
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
    )
    if sandbox:
        args = _nix_shell_sandbox(
            nix_shell,
            shell_file_args,
            cache_directory,
            nix_path,
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
    attrPath: list[str]
    outputs: NotRequired[dict[str, str]]
    drvPath: NotRequired[str]
    extraValue: NotRequired[NixEvalPropsExtra]


class NixEvalPropsExtra(TypedDict):
    exists: bool
    broken: bool


NixEvalResult = list[NixEvalProps]


def _nix_eval_filter(packages: NixEvalResult) -> list[Attr]:
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
    for props in packages:
        drv_path = None
        outputs = None
        extra_value = props.get("extraValue", {})

        if not extra_value.get("broken", True):
            drv_path = Path(props["drvPath"])
            outputs = {output: Path(path) for output, path in props["outputs"].items()}

        # the 'name' field might be quoted, so get the unqoted one from 'attrPath'
        name = props["attrPath"][1]
        attr = Attr(
            name=name,
            exists=extra_value.get("exists", True),
            broken=extra_value.get("broken", True),
            blacklisted=name in blacklist,
            outputs=outputs,
            drv_path=drv_path,
        )
        if attr.drv_path is not None:
            if (other := attr_by_path.get(attr.drv_path)) is None:
                attr_by_path[attr.drv_path] = attr
            elif len(other.name) > len(attr.name):
                attr_by_path[attr.drv_path] = attr
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
    num_eval_workers: int,
    max_memory_size: int,
) -> list[Attr]:
    return multi_system_eval(
        {system: attrs},
        allow=allow,
        nix_path=nix_path,
        num_eval_workers=num_eval_workers,
        max_memory_size=max_memory_size,
    ).get(system, [])


def multi_system_eval(
    attr_names_per_system: dict[System, set[str]],
    allow: AllowedFeatures,
    nix_path: str,
    num_eval_workers: int,
    max_memory_size: int,
) -> dict[System, list[Attr]]:
    attr_json = NamedTemporaryFile(mode="w+", delete=False)  # noqa: SIM115
    delete = True
    try:
        json.dump(
            {system: list(attrs) for system, attrs in attr_names_per_system.items()},
            attr_json,
        )
        eval_script = str(ROOT.joinpath("nix/evalAttrs.nix"))
        attr_json.flush()
        cmd = [
            "nix-eval-jobs",
            "--workers",
            str(num_eval_workers),
            "--max-memory-size",
            str(max_memory_size),
            *_nix_common_flags(allow, nix_path),
            "--expr",
            f"(import {eval_script} {{ attr-json = {attr_json.name}; }})",
            "--apply",
            "d: { inherit (d) exists broken; }",
        ]

        info("$ " + shlex.join(cmd))
        nix_eval = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
        if nix_eval.returncode != 0:
            delete = False
            msg = (
                f"{' '.join(cmd)} failed to run, {attr_json.name} was stored inspection"
            )
            raise NixpkgsReviewError(msg)

        systems_packages: dict[System, NixEvalResult] = {
            system: list() for system in attr_names_per_system
        }
        for line in nix_eval.stdout.splitlines():
            eval_result: NixEvalProps = json.loads(line)
            if not isinstance(eval_result, dict):
                msg = f"Expected eval result to be a dict, got {type(eval_result)}"
                raise TypeError(msg)
            system = eval_result["attrPath"][0]
            systems_packages[system].append(eval_result)

        return {
            system: _nix_eval_filter(packages)
            for system, packages in systems_packages.items()
        }
    finally:
        attr_json.close()
        if delete:
            Path(attr_json.name).unlink()


def nix_build(
    attr_names_per_system: dict[System, set[str]],
    args: str,
    cache_directory: Path,
    allow: AllowedFeatures,
    build_graph: str,
    nix_path: str,
    num_eval_workers: int,
    max_memory_size: int,
) -> dict[System, list[Attr]]:
    if not attr_names_per_system:
        info("Nothing to be built.")
        return {}

    attrs_per_system: dict[System, list[Attr]] = multi_system_eval(
        attr_names_per_system,
        allow,
        nix_path,
        num_eval_workers=num_eval_workers,
        max_memory_size=max_memory_size,
    )

    paths: list[str] = []
    for attrs in attrs_per_system.values():
        paths.extend(
            f"{attr.drv_path}^*"
            for attr in attrs
            if not (attr.broken or attr.blacklisted)
        )

    if len(paths) == 0:
        return attrs_per_system

    command = [
        build_graph,
        "build",
        *_nix_common_flags(allow, nix_path),
        "--no-link",
        "--keep-going",
        "--stdin",
    ]

    if platform == "linux":
        command += [
            # only matters for single-user nix and trusted users
            "--option",
            "build-use-sandbox",
            "relaxed",
        ]

    command += shlex.split(args)

    rebuilds_file = cache_directory / "rebuilds.txt"
    with rebuilds_file.open("w+") as f:
        f.write("".join(f"{p}\n" for p in paths))
        f.seek(0, os.SEEK_SET)

        sh(command, stdin=f)

    return attrs_per_system


def build_shell_file_args(
    cache_dir: Path,
    attrs_per_system: dict[System, list[Attr]],
) -> list[str]:
    # Emulate `nixpkgs.lib.getDev`
    def get_dev(attr: Attr) -> str:
        outputs = attr.outputs or {}
        return str(
            outputs.get("dev") or outputs.get("out") or next(iter(outputs.values()))
        )

    outputs_file = cache_dir.joinpath("outputs.json")
    with outputs_file.open("w+") as f:
        json.dump(
            [get_dev(attr) for attrs in attrs_per_system.values() for attr in attrs],
            f,
        )

    return [
        "--argstr",
        "outputs-path",
        str(outputs_file),
    ]
