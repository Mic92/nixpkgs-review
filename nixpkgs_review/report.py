import json
import os
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from re import Pattern
from typing import Literal

from .nix import Attr
from .utils import System, info, link, skipped, system_order_key, warn


def print_number(
    packages: list[Attr],
    msg: str,
    what: str = "package",
    log: Callable[[str], None] = warn,
) -> None:
    if len(packages) == 0:
        return
    plural = "s" if len(packages) > 1 else ""
    names = (a.name for a in packages)
    log(f"{len(packages)} {what}{plural} {msg}:")
    log(" ".join(names))
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


class LazyDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.created = False

    def ensure(self) -> Path:
        if not self.created:
            self.path.mkdir(exist_ok=True)
            self.created = True
        return self.path


def write_error_logs(
    attrs_per_system: dict[str, list[Attr]],
    directory: Path,
    *,
    max_workers: int | None = 1,
) -> None:
    logs = LazyDirectory(directory.joinpath("logs"))
    results = LazyDirectory(directory.joinpath("results"))
    failed_results = LazyDirectory(directory.joinpath("failed_results"))

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
                def future(attr: Attr = attr, attr_name: str = attr_name) -> None:
                    for path in [f"{attr.drv_path}^*", attr.path]:
                        if not path:
                            continue

                        with logs.ensure().joinpath(attr_name + ".log").open("w+") as f:
                            nix_log = subprocess.run(
                                [
                                    "nix",
                                    "--extra-experimental-features",
                                    "nix-command",
                                    "log",
                                    path,
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
            elif attr.name.startswith("nixosTests."):
                self.tests.append(attr)
            elif not attr.was_build():
                self.failed.append(attr)
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


class Report:
    def __init__(
        self,
        attrs_per_system: dict[str, list[Attr]],
        extra_nixpkgs_config: str,
        only_packages: set[str],
        package_regex: list[Pattern[str]],
        skip_packages: set[str],
        skip_packages_regex: list[Pattern[str]],
        show_header: bool = True,
        max_workers: int | None = 1,
        *,
        checkout: Literal["merge", "commit"] = "merge",
    ) -> None:
        self.show_header = show_header
        self.max_workers = max_workers
        self.attrs = attrs_per_system
        self.checkout = checkout
        self.only_packages = only_packages
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
        directory.joinpath("report.md").write_text(self.markdown(pr))
        directory.joinpath("report.json").write_text(self.json(pr))

        write_error_logs(self.attrs, directory, max_workers=self.max_workers)

    def succeeded(self) -> bool:
        """Whether the report is considered a success or a failure"""
        return all((len(report.failed) == 0) for report in self.system_reports.values())

    def json(self, pr: int | None) -> str:
        return json.dumps(
            {
                "systems": list(self.system_reports.keys()),
                "pr": pr,
                "checkout": self.checkout,
                "extra-nixpkgs-config": self.extra_nixpkgs_config,
                "only_packages": list(self.only_packages),
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

    def markdown(self, pr: int | None) -> str:
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
                "package-regex": self.package_regex,
                "skip-package": self.skip_packages,
                "skip-package-regex": self.skip_packages_regex,
            }.items():
                if option_value:
                    cmd += f" --{option_name} " + f" --{option_name} ".join(
                        option_value
                    )
            msg += f"Command: `{cmd}`\n"

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

        return msg

    def print_console(self, pr: int | None) -> None:
        if pr is not None:
            pr_url = f"https://github.com/NixOS/nixpkgs/pull/{pr}"
            info("\nLink to currently reviewing PR:")
            link(f"\u001b]8;;{pr_url}\u001b\\{pr_url}\u001b]8;;\u001b\\\n")

        for system, report in self.system_reports.items():
            info(f"--------- Report for '{system}' ---------")
            print_number(report.broken, "marked as broken and skipped", log=skipped)
            print_number(
                report.non_existent,
                "present in ofBorgs evaluation, but not found in the checkout",
                log=skipped,
            )
            print_number(report.blacklisted, "blacklisted", log=skipped)
            print_number(report.failed, "failed to build")
            print_number(report.tests, "built", what="tests", log=print)
            print_number(report.built, "built", log=print)
