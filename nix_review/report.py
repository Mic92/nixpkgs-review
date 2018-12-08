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
    file.write(f"  <summary>{len(packages)} {what}{plural} {msg}:</summary>\n")
    for pkg in packages:
        file.write(f"  - {pkg.name}")
        if len(pkg.aliases) > 0:
            file.write(f" ({' ,'.join(pkg.aliases)})")
        file.write("\n")
    file.write(f"</details>\n")


class LazyDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.created = False

    def ensure(self) -> Path:
        if not self.created:
            self.path.mkdir(exist_ok=True)
            self.created = True
        return self.path


def write_error_logs(attrs: List[Attr], directory: Path) -> None:
    logs = LazyDirectory(directory.joinpath("logs"))
    results = LazyDirectory(directory.joinpath("results"))
    failed_results = LazyDirectory(directory.joinpath("failed_results"))
    for attr in attrs:
        if attr.path is not None and os.path.exists(attr.path):
            if attr.was_build():
                symlink_source = results.ensure().joinpath(attr.name)
            else:
                symlink_source = failed_results.ensure().joinpath(attr.name)
            if os.path.lexists(symlink_source):
                symlink_source.unlink()
            symlink_source.symlink_to(attr.path)
            with open(logs.ensure().joinpath(attr.name + ".log"), "w+") as f:
                subprocess.run(["nix", "log", attr.path], stdout=f)


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
        write_error_logs(self.attrs, directory)

    def write_markdown(self, directory: Path, pr: Optional[int]) -> None:
        with open(directory.joinpath("report.md"), "w+") as f:
            f.write(f"Result of [nix-review](https://github.com/Mic92/nix-review)")
            if pr is not None:
                f.write(f" pr {pr}\n")
            else:
                f.write(f"\n")
            write_number(f, self.broken, "are marked as broken and were skipped")
            write_number(
                f,
                self.non_existant,
                "were present in ofBorgs evaluation, but not found in the checkout",
            )
            write_number(f, self.blacklisted, "were blacklisted")
            write_number(f, self.failed, "failed to build")
            write_number(f, self.tests, "were build", what="test")
            write_number(f, self.built, "were build")

    def print_console(self, pr: Optional[int]) -> None:
        if pr is not None:
            info(f"https://github.com/NixOS/nixpkgs/pull/{pr}")
        print_number(self.broken, "are marked as broken and were skipped")
        print_number(
            self.non_existant,
            "were present in ofBorgs evaluation, but not found in the checkout",
        )
        print_number(self.blacklisted, "were blacklisted")
        print_number(self.failed, "failed to build")
        print_number(self.tests, "were build", what="tests", log=print)
        print_number(self.built, "were build", log=print)
