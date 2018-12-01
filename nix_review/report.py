import os
import subprocess
from pathlib import Path
from typing import Callable, List

from .nix import Attr
from .utils import info, warn


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

    def write_error_logs(self, directory: Path) -> None:
        logs = directory.joinpath("logs")
        logs.mkdir(exist_ok=True)
        for attr in self.attrs:
            if attr.path is not None and os.path.exists(attr.path):
                with open(logs.joinpath(attr.name + ".log"), "w+") as f:
                    subprocess.run(["nix", "log", attr.path], stdout=f)

    def report_number(
        self,
        packages: List[Attr],
        msg: str,
        what: str = "package",
        log: Callable[[str], None] = warn,
    ) -> None:
        plural = "s" if len(packages) == 0 else ""
        names = (a.name for a in packages)
        if len(packages) > 0:
            log(f"{len(packages)} {what}{plural} {msg}:")
            log(" ".join(names))
            log("")

    def print_console(self) -> None:
        self.report_number(self.broken, "are marked as broken and were skipped")
        self.report_number(
            self.non_existant,
            "were present in ofBorgs evaluation, but not found in our checkout",
        )
        self.report_number(self.blacklisted, "were blacklisted")
        self.report_number(self.failed, "failed to build:")
        self.report_number(self.tests, "where build:", what="tests", log=info)
        self.report_number(self.built, "where build:", log=info)
