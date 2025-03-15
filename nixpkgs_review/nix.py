import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from sys import platform
from tempfile import NamedTemporaryFile
from typing import Any, Final

from .allow import AllowedFeatures
from .errors import NixpkgsReviewError
from .utils import ROOT, System, info, sh, warn


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
        return self.name.startswith("nixosTests") or ".passthru.tests." in self.name

    def outputs_with_name(self) -> dict[str, Path]:
        def with_output(output: str) -> str:
            if output == "out":
                return self.name
            return f"{self.name}.{output}"

        return {with_output(output): path for output, path in self.outputs.items()}


REVIEW_SHELL: Final[str] = str(ROOT.joinpath("nix/review-shell.nix"))


def nix_shell(
    attrs_per_system: dict[System, list[str]],
    cache_directory: Path,
    local_system: str,
    build_graph: str,
    nix_path: str,
    nixpkgs_config: Path,
    nixpkgs_overlay: Path,
    run: str | None = None,
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
        nixpkgs_config=nixpkgs_config,
    )
    if sandbox:
        args = _nix_shell_sandbox(
            nix_shell,
            shell_file_args,
            cache_directory,
            nix_path,
            nixpkgs_config,
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
    nixpkgs_config: Path,
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

    def tmpfs(path: Path | str, is_dir: bool = True) -> list[str]:
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
        REVIEW_SHELL,
        "--nix-path",
        nix_path,
    ]


def _nix_eval_filter(json: list[Any]) -> list[Attr]:
    # workaround https://github.com/NixOS/ofborg/issues/269
    blacklist = {
        "appimage-run-tests",
        "darwin.builder",
        "nixos-install-tools",
        "tests.nixos-functions.nixos-test",
        "tests.nixos-functions.nixosTest-test",
        "tests.php.overrideAttrs-preserves-enabled-extensions",
        "tests.php.withExtensions-enables-previously-disabled-extensions",
        "tests.trivial",
        "tests.writers",
    }

    def is_blacklisted(name: str) -> bool:
        return name in blacklist or any(
            name.startswith(f"{entry}.") for entry in blacklist
        )

    attr_by_path: dict[Path, Attr] = {}
    broken = []
    for props in json:
        drv_path = None
        outputs = None
        if not props["broken"]:
            drv_path = Path(props["drvPath"])
            outputs = {output: Path(path) for output, path in props["outputs"].items()}

        # the 'name' field might be quoted, so get the unqoted one from 'attrPath'
        name = props["attrPath"][1]
        attr = Attr(
            name=name,
            exists=props["exists"],
            broken=props["broken"],
            blacklisted=is_blacklisted(name),
            outputs=outputs,
            drv_path=drv_path,
        )
        if attr.drv_path is not None:
            other = attr_by_path.get(attr.drv_path, None)
            if other is None:
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
    num_parallel_evals: int,
    max_memory_size: int,
    include_passthru_tests: bool = False,
) -> list[Attr]:
    return multi_system_eval(
        {system: attrs},
        allow=allow,
        nix_path=nix_path,
        num_parallel_evals=num_parallel_evals,
        max_memory_size=max_memory_size,
        include_passthru_tests=include_passthru_tests,
    ).get(system, [])


def multi_system_eval(
    attr_names_per_system: dict[System, set[str]],
    allow: AllowedFeatures,
    nix_path: str,
    num_parallel_evals: int,
    max_memory_size: int,
    include_passthru_tests: bool = False,
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
            str(num_parallel_evals),
            "--max-memory-size",
            str(max_memory_size),
            "--extra-experimental-features",
            "" if allow.url_literals else "no-url-literals",
            "--expr",
            f"""(import {eval_script} {{
              attr-json = {attr_json.name};
              include-passthru-tests = {str(include_passthru_tests).lower()};
            }})""",
            "--nix-path",
            nix_path,
            "--allow-import-from-derivation"
            if allow.ifd
            else "--no-allow-import-from-derivation",
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

        systems_packages = {}
        for line in nix_eval.stdout.splitlines():
            attrs = json.loads(line)
            system = attrs["attrPath"][0]
            systems_packages.setdefault(system, list()).append(attrs)

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
    allow: AllowedFeatures,
    build_graph: str,
    nix_path: str,
    num_parallel_evals: int,
    max_memory_size: int,
) -> dict[System, list[Attr]]:
    if not attr_names_per_system:
        info("Nothing to be built.")
        return {}

    attrs_per_system: dict[System, list[Attr]] = multi_system_eval(
        attr_names_per_system,
        allow,
        nix_path,
        num_parallel_evals=num_parallel_evals,
        max_memory_size=max_memory_size,
    )

    paths = []
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
        "--extra-experimental-features",
        "nix-command",
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

    sh(command, input="\n".join(str(p) for p in paths))
    return attrs_per_system


def build_shell_file_args(
    cache_dir: Path,
    attrs_per_system: dict[System, list[str]],
    local_system: str,
    nixpkgs_config: Path,
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
        print(f.read())

    return [
        "--argstr",
        "local-system",
        local_system,
        "--argstr",
        "nixpkgs-path",
        str(cache_dir.joinpath("nixpkgs/")),
        "--argstr",
        "nixpkgs-config-path",
        str(nixpkgs_config),
        "--argstr",
        "attrs-path",
        str(attrs_file),
    ]
