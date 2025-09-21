from __future__ import annotations

import concurrent.futures
import fcntl
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, cast
from urllib.error import URLError
from xml.etree import ElementTree as ET

from . import git, http_requests
from .builddir import Builddir
from .errors import NixpkgsReviewError
from .github import GithubClient, GitHubPullRequest
from .nix import Attr, nix_build, nix_eval, nix_shell
from .report import Report
from .utils import System, current_system, die, info, sh, system_order_key, warn

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator
    from re import Pattern

    from .allow import AllowedFeatures

# keep up to date with `supportedPlatforms`
# https://github.com/NixOS/ofborg/blob/cf2c6712bd7342406e799110e7cd465aa250cdca/ofborg/src/outpaths.nix#L12
PLATFORMS_LINUX: set[str] = {"aarch64-linux", "x86_64-linux"}
PLATFORMS_DARWIN: set[str] = {"aarch64-darwin", "x86_64-darwin"}
PLATFORMS_AARCH64: set[str] = {"aarch64-darwin", "aarch64-linux"}
PLATFORMS_X64: set[str] = {"x86_64-darwin", "x86_64-linux"}
PLATFORMS: set[str] = PLATFORMS_LINUX.union(PLATFORMS_DARWIN)


class CheckoutOption(Enum):
    # Merge pull request into the target branch
    MERGE = 1
    # Checkout the committer's pull request. This is useful if changes in the
    # target branch has not been build yet by hydra and would trigger too many
    # builds. This option comes at the cost of ignoring the latest changes of
    # the target branch.
    COMMIT = 2


def print_packages(
    names: list[str],
    msg: str,
) -> None:
    if not names:
        return
    plural = "s" if len(names) > 1 else ""

    print(f"{len(names)} package{plural} {msg}:")
    print(" ".join(names))
    print()


@dataclass
class Package:
    pname: str
    version: str
    attr_path: str
    store_path: str | None
    homepage: str | None
    description: str | None
    position: str | None
    old_pkg: Package | None = field(default=None, init=False)


def print_updates(changed_pkgs: list[Package], removed_pkgs: list[Package]) -> None:
    new = []
    updated = []
    for pkg in changed_pkgs:
        if pkg.old_pkg is None:
            new.append(
                f"{pkg.attr_path} (init at {pkg.version})" if pkg.version else pkg.pname
            )
        elif pkg.old_pkg.version != pkg.version:
            updated.append(f"{pkg.attr_path} ({pkg.old_pkg.version} → {pkg.version})")
        else:
            updated.append(pkg.pname)

    removed = [f"{p.pname} (†{p.version})" for p in removed_pkgs]

    print_packages(new, "added")
    print_packages(updated, "updated")
    print_packages(removed, "removed")


class Review:
    def __init__(
        self,
        builddir: Builddir,
        build_args: str,
        no_shell: bool,
        run: str,
        remote: str,
        systems: list[System],
        allow: AllowedFeatures,
        build_graph: str,
        nixpkgs_config: Path,
        extra_nixpkgs_config: str,
        eval_type: str,
        api_token: str | None = None,
        only_packages: set[str] | None = None,
        additional_packages: set[str] | None = None,
        package_regexes: list[Pattern[str]] | None = None,
        skip_packages: set[str] | None = None,
        skip_packages_regex: list[Pattern[str]] | None = None,
        checkout: CheckoutOption = CheckoutOption.MERGE,
        *,
        sandbox: bool = False,
        num_parallel_evals: int = 1,
        show_header: bool = True,
        show_logs: bool = False,
        show_pr_info: bool = True,
        pr_object: dict[str, Any] | None = None,
    ) -> None:
        self.builddir = builddir
        self.build_args = build_args
        self.no_shell = no_shell
        self.run = run
        self.remote = remote
        self.api_token = api_token
        self.github_client = GithubClient(api_token)
        self.eval_type = eval_type
        self.checkout = checkout
        self.only_packages = only_packages or set()
        self.additional_packages = additional_packages or set()
        self.package_regex = package_regexes or []
        self.skip_packages = skip_packages or set()
        self.skip_packages_regex = skip_packages_regex or []
        self.local_system = current_system()
        if not systems:
            msg = "Systems is empty"
            raise NixpkgsReviewError(msg)
        self.systems = set(
            itertools.chain(
                *[self._process_aliases_for_systems(s.lower()) for s in systems]
            )
        )
        self.allow = allow
        self.sandbox = sandbox
        self.build_graph = build_graph
        self.nixpkgs_config = nixpkgs_config
        self.extra_nixpkgs_config = extra_nixpkgs_config
        self.num_parallel_evals = num_parallel_evals
        self.show_header = show_header
        self.show_logs = show_logs
        self.show_pr_info = show_pr_info
        self.head_commit: str | None = None
        self.pr_object = pr_object

    @property
    def _use_github_eval(self) -> bool:
        # If the user explicitly asks for local eval, just do it
        if self.eval_type == "local":
            return False

        if self.only_packages:
            return False

        # Handle the GH_TOKEN eventually not being provided
        if not self.api_token:
            warn("No GitHub token provided via GITHUB_TOKEN variable.")
            match self.eval_type:
                case "auto":
                    warn(
                        "Falling back to local evaluation.\n"
                        "Tip: Install the `gh` command line tool and run `gh auth login` to authenticate."
                    )
                    return False
                case "github":
                    sys.exit(1)

        # GHA evaluation only evaluates nixpkgs with an empty config.
        # Its results might be incorrect when a non-default nixpkgs config is requested
        normalized_config = self.extra_nixpkgs_config.replace(" ", "")

        if normalized_config == "{}":
            return True

        warn("Non-default --extra-nixpkgs-config provided.")
        match self.eval_type:
            # By default, fall back to local evaluation
            case "auto":
                warn("Falling back to local evaluation")
                return False

            # If the user explicitly requires GitHub eval, warn him, but proceed
            case "github":
                warn(
                    "Forcing `github` evaluation -> Be warned that the evaluation results might not correspond to the provided nixpkgs config"
                )
                return True

            # This should never happen
            case _:
                die("Invalid eval_type")
        return None

    def _process_aliases_for_systems(self, system: str) -> set[str]:
        match system:
            case "current":
                return {current_system()}
            case "all":
                return PLATFORMS
            case "linux":
                return PLATFORMS_LINUX
            case "darwin" | "macos":
                return PLATFORMS_DARWIN
            case "x64" | "x86" | "x86_64" | "x86-64" | "x64_86" | "x64-86":
                return PLATFORMS_X64
            case "aarch64" | "arm64":
                return PLATFORMS_AARCH64
            case _:
                return {system}

    def worktree_dir(self) -> str:
        return str(self.builddir.worktree_dir)

    def _render_markdown(self, content: str, max_length: int = 1000) -> None:
        """Render markdown content using glow if available, otherwise plain text."""
        is_truncated = len(content) > max_length
        content = content[:max_length]

        if (glow_cmd := shutil.which("glow")) and os.isatty(sys.stdout.fileno()):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(content)
                temp_file = f.name
            try:
                subprocess.run([glow_cmd, temp_file], check=False)
            finally:
                Path(temp_file).unlink()
        else:
            print(content)

        if is_truncated:
            print("\n... (truncated)")

    def _display_diff_preview(self, diff_content: str) -> None:
        """Display diff preview with delta if available."""
        files_changed = set()
        for line in diff_content.split("\n"):
            if (
                line.startswith("diff --git")
                and (parts := line.split())
                and len(parts) >= 3
            ):
                file_path = parts[2].lstrip("a/")
                files_changed.add(file_path)

        if files_changed:
            print(f"\nFiles changed ({len(files_changed)} files):")
            for file_path in sorted(files_changed)[:20]:
                print(f"  - {file_path}")
            if len(files_changed) > 20:
                print(f"  ... and {len(files_changed) - 20} more files")

        if (delta_cmd := shutil.which("delta")) and os.isatty(sys.stdout.fileno()):
            print(f"\n{'-' * 40}")
            print("Diff preview (showing first 500 lines):")
            print(f"{'-' * 40}")

            diff_lines = diff_content.split("\n")[:500]
            limited_diff = "\n".join(diff_lines)

            try:
                subprocess.run(
                    [delta_cmd, "--side-by-side", "--line-numbers", "--paging=never"],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )
            except subprocess.SubprocessError:
                print(limited_diff)

            if len(diff_content.split("\n")) > 500:
                print(
                    f"\n... (diff truncated, showing first 500 lines of {len(diff_content.split('\n'))} total)"
                )
            print(f"{'-' * 40}")

    def _display_pr_info(self, pr: GitHubPullRequest, pr_number: int) -> None:
        """Display PR description and diff information."""
        print(f"\n{'=' * 80}")
        print(f"PR #{pr_number}: {pr['title']}")
        print(f"{'=' * 80}")
        print(f"Author: {pr['user']['login']}")
        print(f"Branch: {pr['head']['label']} -> {pr['base']['label']}")
        print(f"State: {pr['state']}")

        if pr.get("draft", False):
            print("Status: Draft")

        if pr["body"]:
            print(f"\nDescription:\n{'-' * 40}")
            self._render_markdown(pr["body"])
            print(f"{'-' * 40}")

        diff_url = pr["diff_url"]
        if not diff_url:
            return

        try:
            with http_requests.urlopen(diff_url) as response:
                diff_content = response.read().decode("utf-8")
            self._display_diff_preview(diff_content)
        except (URLError, OSError):
            pass

        print(f"{'=' * 80}\n")

    def git_merge(self, commit: str) -> None:
        res = git.run(
            ["merge", "--no-commit", "--no-ff", commit], cwd=self.worktree_dir()
        )
        if res.returncode != 0:
            msg = f"Failed to merge {commit} into {self.worktree_dir()}. git merge failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def git_checkout(self, commit: str) -> None:
        res = git.run(["checkout", commit], cwd=self.worktree_dir())
        if res.returncode != 0:
            msg = f"Failed to checkout {commit} in {self.worktree_dir()}. git checkout failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def apply_unstaged(self, *, staged: bool = False) -> None:
        args = [
            "--no-pager",
            "diff",
            "--no-ext-diff",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        ]
        args.extend(["--staged"] if staged else [])
        diff = git.run(args, stdout=subprocess.PIPE).stdout

        if not diff:
            info("No diff detected, stopping review...")
            sys.exit(0)

        info("Applying `nixpkgs` diff...")
        result = git.run(["apply"], cwd=self.worktree_dir(), stdin=diff)

        if result.returncode != 0:
            die(f"Failed to apply diff in {self.worktree_dir()}")

    def build_commit(
        self,
        base_commit: str,
        head_commit: str | None,
        merge_commit: str | None = None,
        *,
        staged: bool = False,
    ) -> dict[System, list[Attr]]:
        """
        Review a local git commit
        """
        self.git_worktree(base_commit)
        changed_attrs: dict[System, set[str]] = {}

        if self.only_packages:
            if head_commit is None:
                self.apply_unstaged(staged=staged)
            else:
                match self.checkout:
                    case CheckoutOption.COMMIT:
                        self.git_checkout(head_commit)
                    case CheckoutOption.MERGE:
                        if merge_commit:
                            self.git_checkout(merge_commit)
                        else:
                            self.git_merge(head_commit)

            changed_attrs = {system: set(self.only_packages) for system in self.systems}

            return self.build(changed_attrs, self.build_args)

        print("Local evaluation for computing rebuilds")

        # TODO: nix-eval-jobs ?
        base_packages: dict[System, list[Package]] = list_packages(
            self.builddir.nix_path,
            self.systems,
            self.allow,
            n_threads=self.num_parallel_evals,
        )

        if head_commit is None:
            self.apply_unstaged(staged=staged)
        elif merge_commit:
            self.git_checkout(merge_commit)
        else:
            self.git_merge(head_commit)

        # TODO: nix-eval-jobs ?
        merged_packages: dict[System, list[Package]] = list_packages(
            self.builddir.nix_path,
            self.systems,
            self.allow,
            n_threads=self.num_parallel_evals,
            check_meta=True,
        )

        # Systems ordered correctly (x86_64-linux, aarch64-linux, x86_64-darwin, aarch64-darwin)
        sorted_systems: list[System] = sorted(
            self.systems,
            key=system_order_key,
            reverse=True,
        )
        changed_attrs = {}
        for system in sorted_systems:
            changed_pkgs, removed_pkgs = differences(
                base_packages[system], merged_packages[system]
            )
            print(f"--------- Impacted packages on '{system}' ---------")
            print_updates(changed_pkgs, removed_pkgs)

            changed_attrs[system] = {p.attr_path for p in changed_pkgs}

        if head_commit and self.checkout == CheckoutOption.COMMIT:
            self.git_checkout(head_commit)

        return self.build(changed_attrs, self.build_args)

    def git_worktree(self, commit: str) -> None:
        res = git.run(["worktree", "add", self.worktree_dir(), commit])
        if res.returncode != 0:
            msg = f"Failed to add worktree for {commit} in {self.worktree_dir()}. git worktree failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def build(
        self, packages_per_system: dict[System, set[str]], args: str
    ) -> dict[System, list[Attr]]:
        packages_per_system = {
            system: self.additional_packages
            | filter_packages(
                packages,
                self.only_packages,
                self.package_regex,
                self.skip_packages,
                self.skip_packages_regex,
                system,
                self.allow,
                self.builddir.nix_path,
            )
            for system, packages in packages_per_system.items()
        }
        return nix_build(
            packages_per_system,
            args,
            self.builddir.path,
            self.local_system,
            self.allow,
            self.build_graph,
            self.builddir.nix_path,
            self.nixpkgs_config,
            self.num_parallel_evals,
        )

    def build_pr(self, pr_number: int) -> dict[System, list[Attr]]:
        pr = (
            cast("GitHubPullRequest", self.pr_object)
            if self.pr_object
            else self.github_client.pull_request(pr_number)
        )
        self.head_commit = pr["head"]["sha"]

        if self.show_pr_info:
            self._display_pr_info(pr, pr_number)

        packages_per_system: dict[System, set[str]] | None = None

        if self._use_github_eval:
            assert all(system in PLATFORMS for system in self.systems)
            print("-> Fetching eval results from GitHub actions")

            packages_per_system = self.github_client.get_github_action_eval_result(pr)
            if packages_per_system is None:
                timeout_s: int = 10
                print(f"...Results are not (yet) available. Retrying in {timeout_s}s")
                waiting_time_s: int = 0
                while packages_per_system is None:
                    waiting_time_s += timeout_s
                    print(".", end="")
                    sys.stdout.flush()
                    time.sleep(timeout_s)
                    packages_per_system = (
                        self.github_client.get_github_action_eval_result(pr)
                    )
                    if waiting_time_s > 10 * 60:
                        die(
                            "\nTimeout exceeded: No evaluation seems to be available on GitHub."
                            "\nLook for an eventual evaluation error issue on the PR web page."
                            "\nAlternatively, use `--eval local` to do the evaluation locally."
                        )
                print()

            print("-> Successfully fetched rebuilds: no local evaluation needed")
        else:
            packages_per_system = None

        [merge_rev] = fetch_refs(self.remote, pr["merge_commit_sha"], shallow_depth=2)
        base_rev = git.verify_commit_hash(f"{merge_rev}^1")
        head_rev = git.verify_commit_hash(f"{merge_rev}^2")

        if self.only_packages:
            packages_per_system = {
                system: set(self.only_packages) for system in self.systems
            }

        if packages_per_system is None:
            return self.build_commit(base_rev, head_rev, merge_rev)

        match self.checkout:
            case CheckoutOption.MERGE:
                self.git_worktree(merge_rev)
            case CheckoutOption.COMMIT:
                self.git_worktree(head_rev)

        for system in list(packages_per_system.keys()):
            if system not in self.systems:
                packages_per_system.pop(system)
        return self.build(packages_per_system, self.build_args)

    def start_review(
        self,
        commit: str | None,
        attrs_per_system: dict[System, list[Attr]],
        path: Path,
        pr: int | None = None,
        *,
        post_result: bool | None = False,
        print_result: bool = False,
        approve_pr: bool = False,
    ) -> bool:
        os.environ.pop("NIXPKGS_CONFIG", None)
        os.environ["NIXPKGS_REVIEW_ROOT"] = str(path)
        if pr:
            os.environ["PR"] = str(pr)
        report = Report(
            commit,
            attrs_per_system,
            self.extra_nixpkgs_config,
            checkout=self.checkout.name.lower(),  # type: ignore[arg-type]
            only_packages=self.only_packages,
            additional_packages=self.additional_packages,
            package_regex=self.package_regex,
            skip_packages=self.skip_packages,
            skip_packages_regex=self.skip_packages_regex,
            show_header=self.show_header,
            show_logs=self.show_logs,
            # we don't use self.num_parallel_evals here since its choice
            # is mainly capped by available RAM
            max_workers=min(32, os.cpu_count() or 1),  # 'None' assumes IO tasks
        )
        report.print_console(path, pr)
        report.write(path, pr)

        success = report.succeeded()

        if pr and post_result:
            self.github_client.comment_issue(pr, report.markdown(path, pr))

        if pr and approve_pr and success:
            self.github_client.approve_pr(
                pr,
                "Approved automatically following the successful run of `nixpkgs-review`.",
            )

        if print_result:
            print(report.markdown(path, pr))

        if not self.no_shell:
            nix_shell(
                report.built_packages(),
                path,
                self.local_system,
                self.build_graph,
                self.builddir.nix_path,
                self.nixpkgs_config,
                self.builddir.overlay.path,
                self.run,
                sandbox=self.sandbox,
            )

        return success

    def review_commit(
        self,
        path: Path,
        branch: str,
        reviewed_commit: str | None,
        *,
        staged: bool = False,
        print_result: bool = False,
        approve_pr: bool = False,
    ) -> None:
        branch_rev = fetch_refs(self.remote, branch)[0]
        self.start_review(
            reviewed_commit,
            self.build_commit(branch_rev, reviewed_commit, staged=staged),
            path,
            print_result=print_result,
            approve_pr=approve_pr,
        )


def parse_packages_xml(stdout: IO[str]) -> list[Package]:
    packages: list[Package] = []
    path = None
    attrs = None
    homepage = None
    description = None
    position = None
    context = ET.iterparse(stdout, events=("start", "end"))  # noqa: S314
    for event, elem in context:
        match elem.tag:
            case "item":
                match event:
                    case "start":
                        attrs = elem.attrib
                        homepage = None
                        description = None
                        position = None
                        path = None
                    case "end":
                        assert attrs is not None
                        if path is None:
                            # architecture not supported
                            continue
                        pkg = Package(
                            pname=attrs["pname"],
                            version=attrs["version"],
                            attr_path=attrs["attrPath"],
                            store_path=path,
                            homepage=homepage,
                            description=description,
                            position=position,
                        )
                        packages.append(pkg)
            case "output" if event == "start" and elem.attrib["name"] == "out":
                path = elem.attrib["path"]
            case "meta" if event == "start":
                name = elem.attrib["name"]
                if name in ["homepage", "description", "position"]:
                    value = (
                        ", ".join(e.attrib["value"] for e in elem)
                        if elem.attrib["type"] == "strings"
                        else elem.attrib["value"]
                    )
                    match name:
                        case "homepage":
                            homepage = value
                        case "description":
                            description = value
                        case "position":
                            position = value
    return packages


def _list_packages_system(
    system: System,
    nix_path: str,
    allow: AllowedFeatures,
    *,
    check_meta: bool = False,
) -> list[Package]:
    cmd = [
        "nix-env",
        "--extra-experimental-features",
        "" if allow.url_literals else "no-url-literals",
        "--option",
        "system",
        system,
        "-f",
        "<nixpkgs>",
        "--nix-path",
        nix_path,
        "-qaP",
        "--xml",
        "--out-path",
        "--show-trace",
        "--allow-import-from-derivation"
        if allow.ifd
        else "--no-allow-import-from-derivation",
    ]
    if check_meta:
        cmd.append("--meta")
    info("$ " + " ".join(cmd))
    with tempfile.NamedTemporaryFile(mode="w") as tmp:
        res = subprocess.run(cmd, stdout=tmp, check=False)
        if res.returncode != 0:
            msg = f"Failed to list packages: nix-env failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)
        tmp.flush()
        with Path(tmp.name).open() as f:
            return parse_packages_xml(f)


def list_packages(
    nix_path: str,
    systems: set[System],
    allow: AllowedFeatures,
    n_threads: int,
    *,
    check_meta: bool = False,
) -> dict[System, list[Package]]:
    results: dict[System, list[Package]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        future_to_system = {
            executor.submit(
                _list_packages_system,
                system=system,
                nix_path=nix_path,
                allow=allow,
                check_meta=check_meta,
            ): system
            for system in systems
        }
        for future in concurrent.futures.as_completed(future_to_system):
            system = future_to_system[future]
            results[system] = future.result()

    return results


def package_attrs(
    package_set: set[str],
    system: str,
    allow: AllowedFeatures,
    nix_path: str,
    *,
    ignore_nonexisting: bool = True,
) -> dict[Path, Attr]:
    attrs: dict[Path, Attr] = {}

    nonexisting = []

    for attr in nix_eval(package_set, system, allow, nix_path):
        if not attr.exists:
            nonexisting.append(attr.name)
        elif not attr.broken:
            assert attr.path is not None
            attrs[attr.path] = attr

    if not ignore_nonexisting and len(nonexisting) > 0:
        die(f"These packages do not exist: {' '.join(nonexisting)}")
    return attrs


def join_packages(
    changed_packages: set[str],
    specified_packages: set[str],
    system: str,
    allow: AllowedFeatures,
    nix_path: str,
) -> set[str]:
    changed_attrs = package_attrs(changed_packages, system, allow, nix_path)
    specified_attrs = package_attrs(
        specified_packages,
        system,
        allow,
        nix_path,
        ignore_nonexisting=False,
    )

    # ofborg does not include tests and manual evaluation is too expensive
    tests = {path: attr for path, attr in specified_attrs.items() if attr.is_test()}

    nonexistent = specified_attrs.keys() - changed_attrs.keys() - tests.keys()

    if len(nonexistent) != 0:
        die(
            f"The following packages specified with `-p` are not rebuilt by the pull request: "
            f"{' '.join(specified_attrs[path].name for path in nonexistent)}"
        )
    union_paths = (changed_attrs.keys() & specified_attrs.keys()) | tests.keys()

    return {specified_attrs[path].name for path in union_paths}


def filter_packages(
    changed_packages: set[str],
    specified_packages: set[str],
    package_regexes: list[Pattern[str]],
    skip_packages: set[str],
    skip_package_regexes: list[Pattern[str]],
    system: str,
    allow: AllowedFeatures,
    nix_path: str,
) -> set[str]:
    packages: set[str] = set()
    assert isinstance(changed_packages, set)

    if not (
        specified_packages or package_regexes or skip_packages or skip_package_regexes
    ):
        return changed_packages

    if specified_packages:
        packages = join_packages(
            changed_packages,
            specified_packages,
            system,
            allow,
            nix_path,
        )

    for attr in changed_packages:
        for regex in package_regexes:
            if regex.match(attr):
                packages.add(attr)

    # if no packages are build explicitly then treat
    # like like all changed packages are supplied via --package
    # otherwise we can't discard the ones we do not like to build
    if not packages:
        packages = changed_packages.copy()

    if skip_packages:
        packages -= skip_packages

    for attr in packages.copy():
        for regex in skip_package_regexes:
            if regex.match(attr):
                packages.discard(attr)

    return packages


@contextmanager
def locked_open(filename: Path, mode: str = "r") -> Iterator[IO[str]]:
    """
    This is a context manager that provides an advisory write lock on the file specified by `filename` when entering the context, and releases the lock when leaving the context.
    The lock is acquired using the `fcntl` module's `LOCK_EX` flag, which applies an exclusive write lock to the file.
    """
    with filename.open(mode) as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
        fcntl.flock(fd, fcntl.LOCK_UN)


def resolve_git_dir() -> Path:
    dotgit = Path(".git")
    match (dotgit.is_file(), dotgit.is_dir()):
        case (True, False):
            actual_git_dir = dotgit.read_text().strip()
            if not actual_git_dir.startswith("gitdir: "):
                msg = f"Invalid .git file: {actual_git_dir} found in current directory"
                raise NixpkgsReviewError(msg)
            return Path() / actual_git_dir[8:]
        case (False, True):
            return dotgit
        case _:
            msg = "Cannot find .git file or directory in current directory"
            raise NixpkgsReviewError(msg)


def fetch_refs(repo: str, *refs: str, shallow_depth: int = 1) -> list[str]:
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if shallow.returncode != 0:
        msg = f"Failed to detect if {repo} is shallow repository"
        raise NixpkgsReviewError(msg)

    fetch_cmd = [
        "git",
        "-c",
        "fetch.prune=false",
        "fetch",
        "--no-tags",
        "--force",
        repo,
    ]
    if shallow.stdout.strip() == "true":
        fetch_cmd.append(f"--depth={shallow_depth}")
    for i, ref in enumerate(refs):
        fetch_cmd.append(f"{ref}:refs/nixpkgs-review/{i}")
    dotgit = resolve_git_dir()
    with locked_open(dotgit / "nixpkgs-review", "w"):
        res = sh(fetch_cmd)
        if res.returncode != 0:
            msg = f"Failed to fetch {refs} from {repo}. git fetch failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)
        shas = []
        for i, ref in enumerate(refs):
            rev_parse_cmd = ["git", "rev-parse", "--verify", f"refs/nixpkgs-review/{i}"]
            out = subprocess.run(
                rev_parse_cmd, text=True, stdout=subprocess.PIPE, check=False
            )
            if out.returncode != 0:
                msg = f"Failed to fetch {ref} from {repo} with command: {''.join(rev_parse_cmd)}"
                raise NixpkgsReviewError(msg)
            shas.append(out.stdout.strip())
        return shas


def differences(
    old: list[Package], new: list[Package]
) -> tuple[list[Package], list[Package]]:
    old_attrs = {pkg.attr_path: pkg for pkg in old}
    changed_packages = []
    for new_pkg in new:
        old_pkg = old_attrs.get(new_pkg.attr_path, None)
        if old_pkg is None or old_pkg.store_path != new_pkg.store_path:
            new_pkg.old_pkg = old_pkg
            changed_packages.append(new_pkg)
        if old_pkg:
            del old_attrs[old_pkg.attr_path]

    return (changed_packages, list(old_attrs.values()))


def review_local_revision(
    builddir_path: str,
    args: argparse.Namespace,
    allow: AllowedFeatures,
    nixpkgs_config: Path,
    commit: str | None,
    *,
    staged: bool = False,
    print_result: bool = False,
) -> Path:
    with Builddir(builddir_path) as builddir:
        review = Review(
            builddir=builddir,
            build_args=args.build_args,
            no_shell=args.no_shell,
            run=args.run,
            remote=args.remote,
            only_packages=set(args.package),
            eval_type="local",
            additional_packages=set(args.additional_package),
            package_regexes=args.package_regex,
            skip_packages=set(args.skip_package),
            skip_packages_regex=args.skip_package_regex,
            systems=args.systems.split(" "),
            allow=allow,
            sandbox=args.sandbox,
            build_graph=args.build_graph,
            nixpkgs_config=nixpkgs_config,
            extra_nixpkgs_config=args.extra_nixpkgs_config,
            num_parallel_evals=args.num_parallel_evals,
        )
        review.review_commit(
            builddir.path, args.branch, commit, staged=staged, print_result=print_result
        )
        return builddir.path
