import os
import sys
import traceback
import urllib.error
from itertools import islice
import json
from pathlib import Path
from typing import Callable, List, Optional

from humanize import naturaldelta

from .github import GithubClient
from .nix import Attr
from .utils import info, link, warn


def print_number(
    packages: List[Attr],
    msg: str,
    what: str = "package",
    log: Callable[[str], None] = warn,
    show: int = -1,
) -> None:
    if len(packages) == 0:
        return
    plural = "s" if len(packages) > 1 else ""
    names = (a.name for a in packages)
    log(f"{len(packages)} {what}{plural} {msg}:")
    if show == -1 or show > len(packages):
        log(" ".join(names))
    else:
        log(" ".join(islice(names, show)) + " ...")
    log("")


def html_pkgs_section(
    packages: List[Attr], msg: str, what: str = "package", show: int = -1
) -> str:
    if len(packages) == 0:
        return ""
    plural = "s" if len(packages) > 1 else ""

    res = "<details>\n"
    res += f"  <summary>{len(packages)} {what}{plural} {msg}:</summary>\n  <ul>\n"
    for i, pkg in enumerate(packages):
        if show > 0 and i >= show:
            res += "    <li>...</li>\n"
            break

        if pkg.log_url is not None:
            res += f'    <li><a href="{pkg.log_url}">{pkg.name}</a>'
        else:
            res += f"    <li>{pkg.name}"
        if len(pkg.aliases) > 0:
            res += f" ({' ,'.join(pkg.aliases)})"
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


def write_result_links(attrs: List[Attr], directory: Path) -> None:
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


def write_error_logs(attrs: List[Attr], directory: Path) -> None:
    logs = LazyDirectory(directory.joinpath("logs"))

    for attr in attrs:
        with open(logs.ensure().joinpath(attr.name + ".log"), "w+") as f:
            log_content = attr.log()
            if log_content is not None:
                f.write(log_content)


class Report:
    def __init__(
        self, system: str, attrs: List[Attr], pr_rev: Optional[str] = None
    ) -> None:
        self.system = system
        self.attrs = attrs
        self.pr_rev: Optional[str] = pr_rev
        self.skipped: List[Attr] = []
        self.broken: List[Attr] = []
        self.timed_out: List[Attr] = []
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
            elif a.skipped:
                self.skipped.append(a)
            elif a.timed_out:
                self.timed_out.append(a)
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
        with open(directory.joinpath("report.md"), "w+") as f:
            f.write(self.markdown(pr))

        with open(directory.joinpath("report.json"), "w+") as f:
            f.write(self.json(pr))

        write_result_links(self.attrs, directory)
        write_error_logs(self.failed, directory)

    def succeeded(self) -> bool:
        """Whether the report is considered a success or a failure"""
        return len(self.failed) == 0

    def upload_build_logs(self, github_client: GithubClient, pr: Optional[int]) -> None:
        for pkg in self.failed:
            log_content = pkg.log(tail=1 * 1024 * 1014, strip_colors=True)
            build_time = pkg.build_time()
            description = f"system: {self.system}"
            if build_time is not None:
                description += f" | build_time: {naturaldelta(build_time)}"
            if pr is not None:
                description += f" | https://github.com/NixOS/nixpkgs/pull/{pr}"

            if log_content is not None and len(log_content) > 0:
                try:
                    gist = github_client.upload_gist(
                        name=pkg.name, content=log_content, description=description
                    )
                    pkg.log_url = gist["html_url"]
                except urllib.error.HTTPError:
                    # This is possible due to rate-limiting or a failure of that sort.
                    # It should not be fatal.
                    traceback.print_exc(file=sys.stderr)
            else:
                print(f"Log content for {pkg} was empty", file=sys.stderr)

    def json(self, pr: Optional[int]) -> str:
        def serialize_attrs(attrs: List[Attr]) -> List[str]:
            return list(map(lambda a: a.name, attrs))

        return json.dumps(
            {
                "system": self.system,
                "pr": pr,
                "pr_rev": self.pr_rev,
                "broken": serialize_attrs(self.broken),
                "non-existant": serialize_attrs(self.non_existant),
                "failed": serialize_attrs(self.failed),
                "skipped": serialize_attrs(self.skipped),
                "timed_out": serialize_attrs(self.timed_out),
                "blacklisted": serialize_attrs(self.blacklisted),
                "tests": serialize_attrs(self.tests),
                "built": serialize_attrs(self.built),
            },
            sort_keys=True,
            indent=4,
        )

    def markdown(self, pr: Optional[int]) -> str:
        cmd = "nixpkgs-review"
        if pr is not None:
            cmd += f" pr {pr}"

        shortcommit = f" at {self.pr_rev[:8]}" if self.pr_rev else ""
        link = "[1](https://github.com/Mic92/nixpkgs-review)"
        msg = f"Result of `{cmd}`{shortcommit} run on {self.system} {link}\n"

        msg += html_pkgs_section(self.broken, "marked as broken and skipped")
        msg += html_pkgs_section(
            self.non_existant,
            "present in ofBorgs evaluation, but not found in the checkout",
        )
        msg += html_pkgs_section(self.failed, "failed to build")
        msg += html_pkgs_section(
            self.skipped, "skipped due to time constraints", show=10
        )
        msg += html_pkgs_section(self.timed_out, "timed out")
        msg += html_pkgs_section(self.tests, "built", what="test")
        msg += html_pkgs_section(self.built, "built successfully")

        return msg

    def print_console(self, pr: Optional[int]) -> None:
        if pr is not None:
            pr_url = f"https://github.com/NixOS/nixpkgs/pull/{pr}"
            info("\nLink to currently reviewing PR:")
            link(f"\u001b]8;;{pr_url}\u001b\\{pr_url}\u001b]8;;\u001b\\\n")
        print_number(self.broken, "marked as broken and skipped")
        print_number(
            self.non_existant,
            "present in ofBorgs evaluation, but not found in the checkout",
        )
        print_number(self.blacklisted, "blacklisted")
        print_number(self.skipped, "skipped due to time constraints", show=10)
        print_number(self.timed_out, "timed out", show=True)
        print_number(self.failed, "failed to build")
        print_number(self.tests, "built", what="tests", log=print)
        print_number(self.built, "built successfully", log=print)
