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
from typing import TYPE_CHECKING, NotRequired, TypedDict

from .errors import NixpkgsReviewError
from .utils import ROOT, System, info, sh, warn

if TYPE_CHECKING:
    from .allow import AllowedFeatures


@dataclass(frozen=True)
class BuildConfig:
    """Configuration shared across nix build and eval operations."""

    allow: AllowedFeatures
    nix_path: str
    nixpkgs_config: Path
    num_eval_workers: int = 1
    max_memory_size: int = 4096
    pkgs: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    store: str | None = None
    eval_store: str | None = None


@dataclass
class Attr:
    name: str
    exists: bool
    broken: bool
    blacklisted: bool
    outputs: dict[str, Path] | None
    drv_path: Path | None
    aliases: list[str] = field(default_factory=list)
    store: str | None = None
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
                *store_flags(self.store),
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

    def serialize(self) -> dict:
        return {"name": self.name, "aliases": self.aliases}


def option_flags(options: tuple[tuple[str, str], ...]) -> list[str]:
    return [tok for name, value in options for tok in ("--option", name, value)]


def store_flags(store: str | None, eval_store: str | None = None) -> list[str]:
    return [
        *(["--store", store] if store else []),
        *(["--eval-store", eval_store] if eval_store else []),
    ]


def nix_common_flags(build_config: BuildConfig) -> list[str]:
    allow = build_config.allow
    return [
        "--extra-experimental-features",
        "nix-command",
        *([] if allow.url_literals else ["--option", "lint-url-literals", "fatal"]),
        "--nix-path",
        build_config.nix_path,
        "--allow-import-from-derivation"
        if allow.ifd
        else "--no-allow-import-from-derivation",
        *option_flags(build_config.options),
        *store_flags(build_config.store, build_config.eval_store),
    ]


@dataclass(frozen=True)
class ShellConfig:
    """Configuration for launching the review shell."""

    cache_directory: Path
    run: str | None = None
    sandbox: bool = False
    store: str | None = None


def review_shell_env(attrs: list[Attr]) -> dict[str, str]:
    """Environment for the review shell: bin/ of every built output on PATH.

    No nix evaluation is involved; the outputs are already known from
    nix-eval-jobs, so the shell starts instantly and works the same for
    foreign-system or cross packages."""
    bins = [
        str(path / "bin")
        for attr in attrs
        for path in (attr.outputs or {}).values()
        if (path / "bin").is_dir()
    ]
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([*bins, env.get("PATH", "")])
    # Picked up by shell prompts (bash PS1 in nixpkgs, starship, ...).
    env["IN_NIX_SHELL"] = "impure"
    env["name"] = "review-shell"
    return env


def nix_shell(attrs: list[Attr], config: ShellConfig) -> None:
    if config.store:
        warn(
            "Using a non-default --store: the review shell may fail to run "
            "binaries built into it, since they are not in the local /nix/store."
        )
    shell = os.environ.get("SHELL", "bash")
    cmd = ["bash", "-c", config.run] if config.run is not None else [shell]
    if config.sandbox:
        cmd = _sandbox(config) + cmd
    sh(cmd, cwd=config.cache_directory, env=review_shell_env(attrs))


def _sandbox(config: ShellConfig) -> list[str]:
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

    def tmpfs(path: Path | str) -> list[str]:
        return ["--dir", str(path), "--tmpfs", str(path)]

    home = Path.home()
    current_dir = Path().absolute()
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", home.joinpath(".config")))
    xauthority = Path(os.environ.get("XAUTHORITY", home.joinpath(".Xauthority")))
    uid = os.environ.get("UID", "1000")

    return [
        bwrap,
        "--die-with-parent",
        "--unshare-cgroup",
        "--unshare-ipc",
        "--unshare-uts",
        # / and cia.
        *bind("/"),
        *bind("/dev", dev=True),
        *tmpfs("/tmp"),  # noqa: S108
        # /run (also cover sockets for wayland/pulseaudio and pipewires)
        *bind(Path("/run/user").joinpath(uid), dev=True, try_=True),
        # HOME
        *tmpfs(home),
        *bind(current_dir, ro=False),
        *bind(config.cache_directory, ro=False),
        *bind(xdg_config_home.joinpath("nixpkgs"), try_=True),
        # For X11 applications
        *bind("/tmp/.X11-unix", try_=True),  # noqa: S108
        *bind(xauthority, try_=True),
        # GitHub
        *bind(xdg_config_home.joinpath("hub"), try_=True),
        *bind(xdg_config_home.joinpath("gh"), try_=True),
        "--",
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


def _nix_eval_filter(packages: NixEvalResult, store: str | None) -> list[Attr]:
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
        name = ".".join(props["attrPath"][1:])
        attr = Attr(
            name=name,
            exists=extra_value.get("exists", True),
            broken=extra_value.get("broken", True),
            blacklisted=name in blacklist,
            outputs=outputs,
            drv_path=drv_path,
            store=store,
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


def multi_system_eval(
    attr_names_per_system: dict[System, set[str]],
    build_config: BuildConfig,
    *,
    instantiate: bool = False,
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
            str(build_config.num_eval_workers),
            "--max-memory-size",
            str(build_config.max_memory_size),
            *([] if instantiate else ["--no-instantiate"]),
            *nix_common_flags(build_config),
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
            system: [] for system in attr_names_per_system
        }
        for line in nix_eval.stdout.splitlines():
            raw_result: dict[str, object] = json.loads(line)
            if not isinstance(raw_result, dict):
                msg = f"Expected eval result to be a dict, got {type(raw_result)}"
                raise TypeError(msg)
            # Skip error entries from nix-eval-jobs (e.g. system-level
            # evaluation failures) which lack per-package attrPath.
            # nix-eval-jobs already prints these errors to stderr.
            if "error" in raw_result:
                continue
            eval_result: NixEvalProps = raw_result  # type: ignore[assignment]
            system = eval_result["attrPath"][0]
            systems_packages[system].append(eval_result)

        return {
            system: _nix_eval_filter(packages, build_config.store)
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
    build_config: BuildConfig,
    build_graph: str,
) -> dict[System, list[Attr]]:
    if not attr_names_per_system:
        info("Nothing to be built.")
        return {}

    attrs_per_system: dict[System, list[Attr]] = multi_system_eval(
        attr_names_per_system, build_config, instantiate=True
    )

    installables = [
        f"{attr.drv_path}^*"
        for attrs in attrs_per_system.values()
        for attr in attrs
        if attr.drv_path and not (attr.broken or attr.blacklisted)
    ]
    if not installables:
        return attrs_per_system

    # Lets users re-run the exact build without re-evaluating:
    #   nix build --stdin < derivations
    cache_directory.joinpath("derivations").write_text(
        "".join(f"{i}\n" for i in installables)
    )

    command = [
        build_graph,
        "build",
        *nix_common_flags(build_config),
        "--no-link",
        "--keep-going",
        "--stdin",
        # only matters for single-user nix and trusted users
        *(["--option", "build-use-sandbox", "relaxed"] if platform == "linux" else []),
        *shlex.split(args),
    ]
    sh(command, stdin="\n".join(installables))
    return attrs_per_system
