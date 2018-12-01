from typing import List

from .nix import Attr
from .utils import info, warn


class Report:
    def __init__(self, attrs: List[Attr]):
        self.broken: List[str] = []
        self.failed: List[str] = []
        self.non_existant: List[str] = []
        self.blacklisted: List[str] = []
        self.tests: List[str] = []
        self.built_packages: List[str] = []

        for a in attrs:
            if a.broken:
                self.broken.append(a.name)
            elif a.blacklisted:
                self.blacklisted.append(a.name)
            elif not a.exists:
                self.non_existant.append(a.name)
            elif a.name.startswith("nixosTests."):
                self.tests.append(a.name)
            elif not a.was_build():
                self.failed.append(a.name)
            else:
                self.built_packages.append(a.name)

    def print_console(self) -> None:
        error_msgs = []

        if len(self.broken) > 0:
            error_msgs.append(
                f"{len(self.broken)} package(s) are marked as broken and were skipped:"
            )
            error_msgs.append(" ".join(self.broken))

        if len(self.non_existant) > 0:
            error_msgs.append(
                f"{len(self.non_existant)} package(s) were present in ofBorgs evaluation, but not found in our checkout:"
            )
            error_msgs.append(" ".join(self.non_existant))

        if len(self.blacklisted) > 0:
            error_msgs.append(f"{len(self.blacklisted)} package(s) were blacklisted:")
            error_msgs.append(" ".join(self.blacklisted))

        if len(self.failed) > 0:
            error_msgs.append(f"{len(self.failed)} package(s) failed to build:")
            error_msgs.append(" ".join(self.failed))

        if len(error_msgs) > 0:
            warn("\n".join(error_msgs))

        if len(self.tests) > 0:
            info("The following tests where build")
            info(" ".join(self.tests))

        if len(self.built_packages) > 0:
            info("The following packages where build")
            info(" ".join(self.built_packages))
