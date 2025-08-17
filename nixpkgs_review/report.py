import functools
import html
import json
import os
import re
import socket
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from re import Pattern
from typing import Literal

from .nix import Attr
from .utils import System, info, link, skipped, system_order_key, to_link, warn

# https://github.com/orgs/community/discussions/27190
MAX_GITHUB_COMMENT_LENGTH = 65536


def get_log_filename(a: Attr, system: str) -> str:
    return f"{a.name}-{system}.log"


def get_log_dir(root: Path) -> Path:
    return root / "logs"


def print_number(
    logs_dir: Path,
    system: str,
    packages: list[Attr],
    msg: str,
    what: str = "package",
    log: Callable[[str], None] = warn,
) -> None:
    if len(packages) == 0:
        return
    plural = "s" if len(packages) > 1 else ""
    log(f"{len(packages)} {what}{plural} {msg}:")
    log(
        " ".join(
            [
                to_link(to_file_uri(logs_dir / get_log_filename(pkg, system)), pkg.name)
                for pkg in packages
            ]
        )
    )
    log("")


def html_pkgs_section(
    emoji: str, packages: list[Attr], msg: str, what: str = "package"
) -> str:
    if len(packages) == 0:
        return ""
    plural = "s" if len(packages) > 1 else ""
    res = "<details>\n"
    res += (
        f"  <summary>{emoji} {len(packages)} {what}{plural} {msg}:</summary>\n  <ul>\n"
    )
    for pkg in packages:
        res += f"    <li>{pkg.name}"
        if len(pkg.aliases) > 0:
            res += f" ({', '.join(pkg.aliases)})"
        res += "</li>\n"
    res += "  </ul>\n</details>\n"
    return res


def get_file_tail(file: Path, lines: int = 20) -> str:
    try:
        with file.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(end - lines * 1024, 0), os.SEEK_SET)
            return "\n".join(
                f.read().decode("utf-8", errors="replace").splitlines()[-lines:]
            )
    except OSError:
        return ""


def remove_ansi_escape_sequences(text: str) -> str:
    """Remove ANSI escape sequences from a string."""
    ansi_escape_pattern = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape_pattern.sub("", text)


def html_logs_section(logs_dir: Path, packages: list[Attr], system: str) -> str:
    res = ""
    seen_tails = set()
    for pkg in packages:
        tail = html.escape(
            remove_ansi_escape_sequences(
                get_file_tail(logs_dir / get_log_filename(pkg, system))
            )
        )
        if tail:
            if not res:
                res = "\n---\n"
                res += f"<details>\n<summary>Error logs: `{system}`</summary>\n"
            if tail in seen_tails:
                continue
            res += f"<details>\n<summary>{pkg.name}</summary>\n<pre>{tail}</pre>\n</details>\n"
            seen_tails.add(tail)
    if res:
        res += "</details>\n"
    return res


class LazyDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.created = False

    def ensure(self) -> Path:
        if not self.created:
            self.path.mkdir(exist_ok=True)
            self.created = True
        return self.path


def get_nix_config(name: str | None = None) -> dict[str, str]:
    resp = subprocess.run(
        [
            "nix",
            "--extra-experimental-features",
            "nix-command",
            "config",
            "show",
            *([name] if name is not None else []),
        ],
        text=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=None,
    )

    if resp.returncode == 0:
        if resp.stdout is None:
            return {}
        if name is not None:
            return {name: resp.stdout.strip()}

        out = {}
        for line in resp.stdout.splitlines():
            if not line:
                continue
            lhs, sep, rhs = line.partition(" = ")
            if not sep:
                continue
            out[lhs] = rhs
        return out

    return {}


def write_error_logs(
    attrs_per_system: dict[str, list[Attr]],
    directory: Path,
    *,
    max_workers: int | None = 1,
) -> None:
    logs = LazyDirectory(get_log_dir(directory))
    results = LazyDirectory(directory.joinpath("results"))
    failed_results = LazyDirectory(directory.joinpath("failed_results"))

    extra_nix_log_args = []

    # filter https://cache.nixos.org from acting as build-log substituters
    # to avoid hammering it
    # IDEA: also add the remote builders if user has not already configured this
    # TODO: should this option respect '--build-args'? 'nix log' accepts most, but not all
    substituters = get_nix_config("substituters").get("substituters")
    if substituters is not None:
        extra_nix_log_args += [
            "--option",
            "substituters",
            " ".join(
                i for i in substituters.split() if i and i != "https://cache.nixos.org"
            ),
        ]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for system, attrs in attrs_per_system.items():
            for attr in attrs:
                # Broken attrs have no drv_path.
                if attr.blacklisted or attr.drv_path is None:
                    continue

                attr_name: str = f"{attr.name}-{system}"

                if attr.path is not None and attr.path.exists():
                    if attr.was_build():
                        symlink_source = results.ensure().joinpath(attr_name)
                    else:
                        symlink_source = failed_results.ensure().joinpath(attr_name)
                    if os.path.lexists(symlink_source):
                        symlink_source.unlink()
                    symlink_source.symlink_to(attr.path)

                @pool.submit
                def future(attr: Attr = attr, system: str = system) -> None:
                    for path in [f"{attr.drv_path}^*", attr.path]:
                        if not path:
                            continue

                        with (
                            logs.ensure()
                            .joinpath(get_log_filename(attr, system))
                            .open("w+") as f
                        ):
                            nix_log = subprocess.run(
                                [
                                    "nix",
                                    "--extra-experimental-features",
                                    "nix-command",
                                    "log",
                                    path,
                                    *extra_nix_log_args,
                                ],
                                stdout=f,
                                check=False,
                            )
                            if nix_log.returncode == 0:
                                break


def _serialize_attrs(attrs: list[Attr]) -> list[str]:
    return [a.name for a in attrs]


class SystemReport:
    def __init__(self, attrs: list[Attr]) -> None:
        self.broken: list[Attr] = []
        self.failed: list[Attr] = []
        self.non_existent: list[Attr] = []
        self.blacklisted: list[Attr] = []
        self.tests: list[Attr] = []
        self.built: list[Attr] = []

        for attr in attrs:
            if attr.broken:
                self.broken.append(attr)
            elif attr.blacklisted:
                self.blacklisted.append(attr)
            elif not attr.exists:
                self.non_existent.append(attr)
            elif not attr.was_build():
                self.failed.append(attr)
            elif attr.name.startswith("nixosTests."):
                self.tests.append(attr)
            else:
                self.built.append(attr)

    def serialize(self) -> dict[str, list[str]]:
        return {
            "broken": _serialize_attrs(self.broken),
            "non-existent": _serialize_attrs(self.non_existent),
            "blacklisted": _serialize_attrs(self.blacklisted),
            "failed": _serialize_attrs(self.failed),
            "built": _serialize_attrs(self.built),
            "tests": _serialize_attrs(self.tests),
        }


def order_reports(reports: dict[System, SystemReport]) -> dict[System, SystemReport]:
    """Ensure that systems are always ordered consistently in reports"""
    return dict(
        sorted(
            reports.items(),
            key=lambda item: system_order_key(system=item[0]),
            reverse=True,
        )
    )


# https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda
def to_file_uri(path: Path) -> str:
    """Convert a path to a file URI, including hostname."""
    return f"file://{socket.gethostname()}{path.absolute()}"


class Report:
    def __init__(
        self,
        commit: str | None,
        attrs_per_system: dict[str, list[Attr]],
        extra_nixpkgs_config: str,
        only_packages: set[str],
        additional_packages: set[str],
        package_regex: list[Pattern[str]],
        skip_packages: set[str],
        skip_packages_regex: list[Pattern[str]],
        show_header: bool = True,
        show_logs: bool = False,
        max_workers: int | None = 1,
        *,
        checkout: Literal["merge", "commit"] = "merge",
    ) -> None:
        self.commit = commit
        self.show_header = show_header
        self.show_logs = show_logs
        self.max_workers = max_workers
        self.attrs = attrs_per_system
        self.checkout = checkout
        self.only_packages = only_packages
        self.additional_packages = additional_packages
        self.package_regex = [r.pattern for r in package_regex]
        self.skip_packages = skip_packages
        self.skip_packages_regex = [r.pattern for r in skip_packages_regex]

        if extra_nixpkgs_config != "{ }":
            self.extra_nixpkgs_config: str | None = extra_nixpkgs_config
        else:
            self.extra_nixpkgs_config = None

        reports: dict[System, SystemReport] = {}
        for system, attrs in attrs_per_system.items():
            reports[system] = SystemReport(attrs)
        self.system_reports: dict[System, SystemReport] = order_reports(reports)

    def built_packages(self) -> dict[System, list[str]]:
        return {
            system: [a.name for a in report.built]
            for system, report in self.system_reports.items()
        }

    def write(self, directory: Path, pr: int | None) -> None:
        # write logs first because snippets from them may be needed for the report
        write_error_logs(self.attrs, directory, max_workers=self.max_workers)
        directory.joinpath("report.md").write_text(self.markdown(directory, pr))
        directory.joinpath("report.json").write_text(self.json(pr))

    def succeeded(self) -> bool:
        """Whether the report is considered a success or a failure"""
        return all((len(report.failed) == 0) for report in self.system_reports.values())

    def json(self, pr: int | None) -> str:
        return json.dumps(
            {
                "systems": list(self.system_reports.keys()),
                "pr": pr,
                "commit": self.commit,
                "checkout": self.checkout,
                "extra-nixpkgs-config": self.extra_nixpkgs_config,
                "only_packages": list(self.only_packages),
                "additional_packages": list(self.additional_packages),
                "package_regex": list(self.package_regex),
                "skip_packages": list(self.skip_packages),
                "skip_packages_regex": list(self.skip_packages_regex),
                "result": {
                    system: report.serialize()
                    for system, report in self.system_reports.items()
                },
            },
            sort_keys=True,
            indent=4,
        )

    def markdown(self, root: Path, pr: int | None) -> str:
        msg = ""
        if self.show_header:
            msg += "## `nixpkgs-review` result\n\n"
            msg += "Generated using [`nixpkgs-review`](https://github.com/Mic92/nixpkgs-review).\n\n"

            cmd = "nixpkgs-review"
            if pr is not None:
                cmd += f" pr {pr}"
            if self.extra_nixpkgs_config:
                cmd += f" --extra-nixpkgs-config '{self.extra_nixpkgs_config}'"
            if self.checkout != "merge":
                cmd += f" --checkout {self.checkout}"
            for option_name, option_value in {
                "package": self.only_packages,
                "additional-package": self.additional_packages,
                "package-regex": self.package_regex,
                "skip-package": self.skip_packages,
                "skip-package-regex": self.skip_packages_regex,
            }.items():
                if option_value:
                    cmd += f" --{option_name} " + f" --{option_name} ".join(
                        option_value
                    )
            msg += f"Command: `{cmd}`\n"
            if self.commit:
                msg += f"Commit: `{self.commit}`\n"

        for system, report in self.system_reports.items():
            msg += "\n---\n"
            msg += f"### `{system}`\n"
            msg += html_pkgs_section(
                ":fast_forward:", report.broken, "marked as broken and skipped"
            )
            msg += html_pkgs_section(
                ":fast_forward:",
                report.non_existent,
                "present in ofBorgs evaluation, but not found in the checkout",
            )
            msg += html_pkgs_section(
                ":fast_forward:", report.blacklisted, "blacklisted"
            )
            msg += html_pkgs_section(":x:", report.failed, "failed to build")
            msg += html_pkgs_section(
                ":white_check_mark:", report.tests, "built", what="test"
            )
            msg += html_pkgs_section(":white_check_mark:", report.built, "built")

        if self.show_logs:
            truncated_msg = (
                "\n---\n"
                "WARNING: Some logs were not included in this report: there were too many."
            )
            for system, report in self.system_reports.items():
                if not report.failed:
                    continue
                full_msg = msg
                full_msg += html_logs_section(get_log_dir(root), report.failed, system)
                # if the final message won't fit a single github comment, stop
                if len(full_msg) > MAX_GITHUB_COMMENT_LENGTH - len(truncated_msg):
                    msg += truncated_msg
                    break
                msg = full_msg

        return msg

    def print_console(self, root: Path, pr: int | None) -> None:
        if pr is not None:
            pr_url = f"https://github.com/NixOS/nixpkgs/pull/{pr}"
            info("\nLink to currently reviewing PR:")
            link(to_link(pr_url, pr_url))

        logs_dir = get_log_dir(root)
        for system, report in self.system_reports.items():
            info(f"--------- Report for '{system}' ---------")
            p = functools.partial(print_number, logs_dir, system)
            p(report.broken, "marked as broken and skipped", log=skipped)
            p(
                report.non_existent,
                "present in ofBorgs evaluation, but not found in the checkout",
                log=skipped,
            )
            p(report.blacklisted, "blacklisted", log=skipped)
            p(report.failed, "failed to build")
            p(report.tests, "built", what="test", log=print)
            p(report.built, "built", log=print)

        info("Logs can be found under:")
        link(to_link(to_file_uri(logs_dir), str(logs_dir)))
        info("")
