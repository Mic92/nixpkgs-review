import os
import subprocess
from pathlib import Path
from typing import IO, Callable, List, Optional

from .nix import Attr
from .utils import info, warn


def print_number(
    packages: List[Attr],
    msg: str,
    what: str = "package",
    log: Callable[[str], None] = warn,
) -> None:
    if len(packages) == 0:
        return
    plural = "s" if len(packages) == 0 else ""
    names = (a.name for a in packages)
    log(f"{len(packages)} {what}{plural} {msg}:")
    log(" ".join(names))
    log("")


def write_number(
    file: IO[str], packages: List[Attr], msg: str, what: str = "package"
) -> None:
    if len(packages) == 0:
        return
    plural = "s" if len(packages) == 0 else ""
    file.write(f"<details>\n")
    file.write(f"  <summary>{len(packages)} {what}{plural} {msg}:<summary>\n")
    for pkg in packages:
        file.write(f"  - {pkg.name}\n")
    file.write(f"<details>\n")


class Report:
    def __init__(self, attrs: List[Attr]):
        self.attrs = attrs
        self.broken: List[Attr] = []
        self.failed: List[Attr] = []
        self.non_existant: List[Attr] = []
        self.blacklisted: List[Attr] = []
        self.tests: List[Attr] = []
        self.built: List[Attr] = []

        for a in attrs:
            if a.broken:
                self.broken.append(a)
            elif a.blacklisted:
                self.blacklisted.append(a)
            elif not a.exists:
                self.non_existant.append(a)
            elif a.name.startswith("nixosTests."):
                self.tests.append(a)
            elif not a.was_build():
                self.failed.append(a)
            else:
                self.built.append(a)

    def built_packages(self) -> List[str]:
        return [a.name for a in self.built]

    def write(self, directory: Path, pr: Optional[int]) -> None:
        self.write_markdown(directory, pr)
        self.write_error_logs(directory)

    def write_markdown(self, directory: Path, pr: Optional[int]) -> None:
        with open(directory.joinpath("report.md"), "w+") as f:
            f.write(f"Result of [nix-review](https://github.com/Mic92/nix-review)\n")
            if pr is not None:
                f.write(f"pr {pr}\n")
            else:
                f.write(f"\n")
            write_number(f, self.broken, "are marked as broken and were skipped")
            write_number(
                f,
                self.non_existant,
                "were present in ofBorgs evaluation, but not found in the checkout",
            )
            write_number(f, self.blacklisted, "were blacklisted")
            write_number(f, self.failed, "failed to build:")
            write_number(f, self.tests, "where build:", what="test")
            write_number(f, self.built, "where build:")

    def write_error_logs(self, directory: Path) -> None:
        logs = directory.joinpath("logs")
        log_created = False
        for attr in self.attrs:
            if attr.path is not None and os.path.exists(attr.path):
                if not log_created:
                    logs.mkdir(exist_ok=True)
                    log_created = True
                with open(logs.joinpath(attr.name + ".log"), "w+") as f:
                    subprocess.run(["nix", "log", attr.path], stdout=f)

    def print_console(self, pr: Optional[int]) -> None:
        if pr is not None:
            info(f"https://github.com/NixOS/nixpkgs/pull/{pr}")
        print_number(self.broken, "are marked as broken and were skipped")
        print_number(
            self.non_existant,
            "were present in ofBorgs evaluation, but not found in the checkout",
        )
        print_number(self.blacklisted, "were blacklisted")
        print_number(self.failed, "failed to build:")
        print_number(self.tests, "where build:", what="tests", log=info)
        print_number(self.built, "where build:", log=info)
