from __future__ import annotations

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
from .nix import Attr, BuildConfig, ShellConfig, multi_system_eval, nix_build, nix_shell
from .report import Report, ReportOptions
from .utils import (
    PackageFilter,
    System,
    current_system,
    die,
    info,
    sh,
    system_order_key,
    warn,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Iterator
    from re import Pattern

    from .allow import AllowedFeatures

# keep up to date with `supportedPlatforms`
# https://github.com/NixOS/ofborg/blob/cf2c6712bd7342406e799110e7cd465aa250cdca/ofborg/src/outpaths.nix#L12
PLATFORMS_LINUX: set[str] = {"aarch64-linux", "x86_64-linux"}
PLATFORMS_DARWIN: set[str] = {"aarch64-darwin", "x86_64-darwin"}
PLATFORMS_AARCH64: set[str] = {"aarch64-darwin", "aarch64-linux"}
PLATFORMS_X64: set[str] = {"x86_64-darwin", "x86_64-linux"}
PLATFORMS: set[str] = PLATFORMS_LINUX.union(PLATFORMS_DARWIN)


@dataclass(frozen=True)
class ReviewAction:
    """Flags controlling what to do after a review completes."""

    post_result: bool = False
    print_result: bool = False
    approve_pr: bool = False
    merge_pr: bool = False


class CheckoutOption(Enum):
    # Merge pull request into the target branch
    MERGE = 1
    # Checkout the committer's pull request. This is useful if changes in the
    # target branch has not been build yet by hydra and would trigger too many
    # builds. This option comes at the cost of ignoring the latest changes of
    # the target branch.
    COMMIT = 2
    # Checkout the base (target) branch, for reference
    BASE = 3


@dataclass(frozen=True)
class ReviewConfig:
    """What to review and how: scope, eval strategy, checkout, and display."""

    remote: str
    extra_nixpkgs_config: str
    systems: list[System]
    eval_type: str = "auto"
    api_token: str | None = None
    checkout: CheckoutOption = CheckoutOption.MERGE
    pr_object: dict[str, Any] | None = None
    show_header: bool = True
    show_logs: bool = False
    show_pr_info: bool = True


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


@dataclass(frozen=True)
class ShellOptions:
    """Options controlling the interactive shell after building."""

    no_shell: bool = False
    run: str | None = None
    sandbox: bool = False
    build_args: str = ""
    build_graph: str = "nix"


class Review:
    def __init__(
        self,
        *,
        builddir: Builddir,
        review_config: ReviewConfig,
        build_config: BuildConfig,
        shell_options: ShellOptions,
        package_filter: PackageFilter | None = None,
    ) -> None:
        self.builddir = builddir
        self.review_config = review_config
        self.github_client = GithubClient(review_config.api_token)
        self.package_filter = package_filter or PackageFilter()
        if not review_config.systems:
            msg = "Systems is empty"
            raise NixpkgsReviewError(msg)
        self.systems = set(
            itertools.chain(
                *(
                    self._process_aliases_for_systems(s.lower())
                    for s in review_config.systems
                )
            )
        )
        self.build_config = build_config
        self.shell_options = shell_options
        self.head_commit: str | None = None

    @property
    def _use_github_eval(self) -> bool:
        # If the user explicitly asks for local eval, just do it
        if self.review_config.eval_type == "local" or self.package_filter.only_packages:
            return False

        # Handle the GH_TOKEN eventually not being provided
        if not self.review_config.api_token:
            warn("No GitHub token provided via GITHUB_TOKEN variable.")
            if self.review_config.eval_type == "github":
                sys.exit(1)
            # For "auto" mode, fall back to local evaluation
            warn(
                "Falling back to local evaluation.\n"
                "Tip: Install the `gh` command line tool and run `gh auth login` to authenticate."
            )
            return False

        # GHA evaluation only evaluates nixpkgs with an empty config.
        # Its results might be incorrect when a non-default nixpkgs config is requested
        if self.review_config.extra_nixpkgs_config.replace(" ", "") == "{}":
            return True

        warn("Non-default --extra-nixpkgs-config provided.")
        if self.review_config.eval_type == "github":
            warn(
                "Forcing `github` evaluation -> Be warned that the evaluation results might not correspond to the provided nixpkgs config"
            )
            return True

        # For "auto" mode, fall back to local evaluation
        warn("Falling back to local evaluation")
        return False

    @staticmethod
    def _process_aliases_for_systems(system: str) -> set[str]:
        aliases: dict[str, set[str]] = {
            "current": {current_system()},
            "all": PLATFORMS,
            "linux": PLATFORMS_LINUX,
            "darwin": PLATFORMS_DARWIN,
            "macos": PLATFORMS_DARWIN,
            "x64": PLATFORMS_X64,
            "x86": PLATFORMS_X64,
            "x86_64": PLATFORMS_X64,
            "x86-64": PLATFORMS_X64,
            "x64_86": PLATFORMS_X64,
            "x64-86": PLATFORMS_X64,
            "aarch64": PLATFORMS_AARCH64,
            "arm64": PLATFORMS_AARCH64,
        }
        return aliases.get(system, {system})

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

            diff_lines = diff_content.split("\n")
            limited_diff = "\n".join(diff_lines[:500])

            try:
                subprocess.run(
                    [delta_cmd, "--side-by-side", "--line-numbers", "--paging=never"],
                    input=limited_diff,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )
            except subprocess.SubprocessError:
                print(limited_diff)

            if len(diff_lines) > 500:
                print(
                    f"\n... (diff truncated, showing first 500 lines of {len(diff_lines)} total)"
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

    def _build_commit_packages(
        self,
        base_commit: str,
        head_commit: str | None,
        merge_commit: str | None = None,
        *,
        staged: bool = False,
    ) -> dict[System, list[Attr]]:
        if head_commit is None:
            self.apply_unstaged(staged=staged)
        else:
            match self.review_config.checkout:
                case CheckoutOption.COMMIT:
                    self.git_checkout(head_commit)
                case CheckoutOption.MERGE:
                    if merge_commit:
                        self.git_checkout(merge_commit)
                    else:
                        self.git_merge(head_commit)
                case CheckoutOption.BASE:
                    self.git_checkout(base_commit)

        changed_attrs = {
            system: set(self.package_filter.only_packages) for system in self.systems
        }

        return self.build(changed_attrs, self.shell_options.build_args)

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

        if self.package_filter.only_packages:
            return self._build_commit_packages(
                base_commit, head_commit, merge_commit, staged=staged
            )

        print("Local evaluation for computing rebuilds")

        base_packages: dict[System, list[Package]] = list_packages(
            self.builddir.nix_path,
            self.systems,
            self.build_config.allow,
        )

        if head_commit is None:
            self.apply_unstaged(staged=staged)
        elif merge_commit:
            self.git_checkout(merge_commit)
        else:
            self.git_merge(head_commit)

        merged_packages: dict[System, list[Package]] = list_packages(
            self.builddir.nix_path,
            self.systems,
            self.build_config.allow,
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

        if head_commit and self.review_config.checkout == CheckoutOption.COMMIT:
            self.git_checkout(head_commit)
        elif base_commit and self.review_config.checkout == CheckoutOption.BASE:
            self.git_checkout(base_commit)

        return self.build(changed_attrs, self.shell_options.build_args)

    def git_worktree(self, commit: str) -> None:
        # Prune stale worktree metadata in case the cache directory was
        # externally deleted (e.g. user cleaned ~/.cache).  Without this,
        # git refuses to re-use a path it still considers registered.
        git.run(["worktree", "prune"])
        res = git.run(["worktree", "add", self.worktree_dir(), commit])
        if res.returncode != 0:
            msg = f"Failed to add worktree for {commit} in {self.worktree_dir()}. git worktree failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def build(
        self, packages_per_system: dict[System, set[str]], args: str
    ) -> dict[System, list[Attr]]:
        packages_per_system = filter_packages_per_system(
            packages_per_system,
            self.package_filter,
            self.build_config,
        )
        packages_per_system = {
            system: self.package_filter.additional_packages | packages
            for system, packages in packages_per_system.items()
        }
        return nix_build(
            packages_per_system,
            args,
            self.builddir.path,
            self.build_config,
            self.shell_options.build_graph,
        )

    def _fetch_packages_from_github_eval(
        self, pr: GitHubPullRequest
    ) -> dict[System, set[str]] | None:
        assert all(system in PLATFORMS for system in self.systems)
        print("-> Fetching eval results from GitHub actions")
        packages_per_system = self.github_client.get_github_action_eval_result(pr)
        if packages_per_system is not None:
            return packages_per_system

        timeout_s: int = 10
        print(f"...Results are not (yet) available. Retrying in {timeout_s}s")
        waiting_time_s: int = 0

        while packages_per_system is None:
            waiting_time_s += timeout_s
            print(".", end="")
            sys.stdout.flush()
            time.sleep(timeout_s)
            packages_per_system = self.github_client.get_github_action_eval_result(pr)
            if waiting_time_s > 10 * 60:
                die(
                    "\nTimeout exceeded: No evaluation seems to be available on GitHub."
                    "\nLook for an eventual evaluation error issue on the PR web page."
                    "\nAlternatively, use `--eval local` to do the evaluation locally."
                )
        print()
        print("-> Successfully fetched rebuilds: no local evaluation needed")
        return packages_per_system

    def _resolve_pr_revisions(
        self, pr: GitHubPullRequest
    ) -> tuple[str, str, str | None]:
        merge_commit_sha = pr.get("merge_commit_sha")
        if merge_commit_sha:
            [merge_rev] = fetch_refs(
                self.review_config.remote, merge_commit_sha, shallow_depth=2
            )
            base_rev = git.verify_commit_hash(f"{merge_rev}^1")
            head_rev = git.verify_commit_hash(f"{merge_rev}^2")
            return base_rev, head_rev, merge_rev

        warn(
            "GitHub API returned no merge commit for this PR; falling back to "
            "base/head SHAs for local merge evaluation."
        )
        base_rev, head_rev = fetch_refs(
            self.review_config.remote,
            pr["base"]["sha"],
            pr["head"]["sha"],
            shallow_depth=2,
        )
        return base_rev, head_rev, None

    def _checkout_pr_revision(
        self, base_rev: str, head_rev: str, merge_rev: str | None
    ) -> None:
        match self.review_config.checkout:
            case CheckoutOption.MERGE:
                if merge_rev:
                    self.git_worktree(merge_rev)
                else:
                    self.git_worktree(base_rev)
                    self.git_merge(head_rev)
            case CheckoutOption.COMMIT:
                self.git_worktree(head_rev)
            case CheckoutOption.BASE:
                self.git_worktree(base_rev)

    def build_pr(self, pr_number: int) -> dict[System, list[Attr]]:
        pr = (
            cast("GitHubPullRequest", self.review_config.pr_object)
            if self.review_config.pr_object
            else self.github_client.pull_request(pr_number)
        )
        self.head_commit = pr["head"]["sha"]

        if self.review_config.show_pr_info:
            self._display_pr_info(pr, pr_number)

        packages_per_system = (
            self._fetch_packages_from_github_eval(pr) if self._use_github_eval else None
        )

        base_rev, head_rev, merge_rev = self._resolve_pr_revisions(pr)

        if self.package_filter.only_packages:
            packages_per_system = {
                system: set(self.package_filter.only_packages)
                for system in self.systems
            }

        if packages_per_system is None:
            if self.review_config.checkout == CheckoutOption.BASE:
                die(
                    "--checkout base without --package/-p requires GitHub evaluation.\n"
                    "Local evaluation compares base against itself, which always yields zero rebuilds.\n"
                    "Either specify packages explicitly with -p, or use --eval github."
                )
            return self.build_commit(base_rev, head_rev, merge_rev)

        self._checkout_pr_revision(base_rev, head_rev, merge_rev)

        for system in list(packages_per_system.keys()):
            if system not in self.systems:
                packages_per_system.pop(system)
        return self.build(packages_per_system, self.shell_options.build_args)

    def start_review(
        self,
        commit: str | None,
        attrs_per_system: dict[System, list[Attr]],
        path: Path,
        pr: int | None = None,
        action: ReviewAction | None = None,
    ) -> bool:
        action = action or ReviewAction()
        os.environ.pop("NIXPKGS_CONFIG", None)
        os.environ["NIXPKGS_REVIEW_ROOT"] = str(path)
        if pr:
            os.environ["PR"] = str(pr)
        report = Report(
            commit,
            attrs_per_system,
            self.package_filter,
            ReportOptions(
                extra_nixpkgs_config=self.review_config.extra_nixpkgs_config,
                checkout=self.review_config.checkout.name.lower(),  # type: ignore[arg-type]
                show_header=self.review_config.show_header,
                show_logs=self.review_config.show_logs,
                max_workers=min(32, os.cpu_count() or 1),
            ),
        )
        report.print_console(path, pr)
        report.write(path, pr)

        success = report.succeeded()

        if pr and action.post_result:
            self.github_client.comment_issue(pr, report.markdown(path, pr))

        if pr and action.approve_pr and success:
            if action.merge_pr and self.github_client.is_nixpkgs_committer():
                self.github_client.approve_pr(
                    pr,
                    "Approved automatically following the successful run of `nixpkgs-review`.",
                )
                self.github_client.merge_pr(pr, report.commit)
            else:
                self.github_client.approve_pr(
                    pr,
                    "Approved automatically following the successful run of `nixpkgs-review`."
                    + ("\n\n@NixOS/nixpkgs-merge-bot merge" if action.merge_pr else ""),
                )

        if action.print_result:
            print(report.markdown(path, pr))

        if not self.shell_options.no_shell:
            shell_config = ShellConfig(
                cache_directory=path,
                local_system=self.build_config.local_system,
                build_graph=self.shell_options.build_graph,
                nix_path=self.builddir.nix_path,
                nixpkgs_config=self.build_config.nixpkgs_config,
                nixpkgs_overlay=self.builddir.overlay.path,
                run=self.shell_options.run,
                sandbox=self.shell_options.sandbox,
            )
            nix_shell(report.built_packages(), shell_config)

        return success

    def review_commit(
        self,
        path: Path,
        branch: str,
        reviewed_commit: str | None,
        action: ReviewAction | None = None,
        *,
        staged: bool = False,
    ) -> None:
        branch_rev = fetch_refs(self.review_config.remote, branch)[0]
        self.start_review(
            reviewed_commit,
            self.build_commit(branch_rev, reviewed_commit, staged=staged),
            path,
            action=action,
        )


def _extract_meta_value(elem: ET.Element) -> str:
    if elem.attrib["type"] == "strings":
        return ", ".join(e.attrib["value"] for e in elem)
    return elem.attrib["value"]


def parse_packages_xml(stdout: IO[str]) -> list[Package]:
    packages: list[Package] = []
    current_pkg: Package | None = None

    context = ET.iterparse(stdout, events=("start", "end"))  # noqa: S314
    for event, elem in context:
        if elem.tag == "item" and event == "start":
            attrs = elem.attrib
            current_pkg = Package(
                pname=attrs["pname"],
                version=attrs["version"],
                attr_path=attrs["attrPath"],
                store_path=None,
                homepage=None,
                description=None,
                position=None,
            )
        elif (
            elem.tag == "item"
            and event == "end"
            and current_pkg
            and current_pkg.store_path
        ):
            packages.append(current_pkg)
        elif (
            elem.tag == "output"
            and event == "start"
            and elem.attrib["name"] == "out"
            and current_pkg
        ):
            current_pkg.store_path = elem.attrib["path"]
        elif elem.tag == "meta" and event == "end" and current_pkg:
            name = elem.attrib["name"]
            match name:
                case "homepage":
                    current_pkg.homepage = _extract_meta_value(elem)
                case "description":
                    current_pkg.description = _extract_meta_value(elem)
                case "position":
                    current_pkg.position = _extract_meta_value(elem)

        # delete element/attribute connections to free up memory, but don't clear
        # meta `string`s before they are processed
        if event == "end" and elem.tag != "string":
            elem.clear()
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
    *,
    check_meta: bool = False,
) -> dict[System, list[Package]]:
    results: dict[System, list[Package]] = {}
    for system in systems:
        results[system] = _list_packages_system(
            system=system,
            nix_path=nix_path,
            allow=allow,
            check_meta=check_meta,
        )

    return results


def _collect_package_attrs(
    eval_results: list[Attr],
    *,
    ignore_nonexisting: bool = True,
) -> dict[Path, Attr]:
    attrs: dict[Path, Attr] = {}

    nonexisting = []

    for attr in eval_results:
        if not attr.exists:
            nonexisting.append(attr.name)
        elif not attr.broken:
            assert attr.drv_path is not None
            attrs[attr.drv_path] = attr

    if not ignore_nonexisting and len(nonexisting) > 0:
        die(f"These packages do not exist: {' '.join(nonexisting)}")
    return attrs


def _join_packages_for_system(
    changed_attrs: dict[Path, Attr],
    specified_attrs: dict[Path, Attr],
) -> set[str]:
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


def _apply_package_filters(
    packages: set[str],
    skip_packages: set[str],
    skip_package_regexes: list[Pattern[str]],
) -> set[str]:
    """Apply skip filters to the package set."""
    if skip_packages:
        packages = packages - skip_packages

    for attr in packages.copy():
        for regex in skip_package_regexes:
            if regex.match(attr):
                packages.discard(attr)

    return packages


def _match_package_regexes(
    changed_packages: set[str],
    package_regexes: list[Pattern[str]],
) -> set[str]:
    """Find packages matching any of the given regex patterns."""
    packages = set()
    for attr in changed_packages:
        for regex in package_regexes:
            if regex.match(attr):
                packages.add(attr)
                break  # No need to check other regexes for this attr
    return packages


def filter_packages_per_system(
    changed_packages_per_system: dict[System, set[str]],
    package_filter: PackageFilter,
    build_config: BuildConfig,
) -> dict[System, set[str]]:
    needs_filtering = any(
        [
            package_filter.only_packages,
            package_filter.package_regexes,
            package_filter.skip_packages,
            package_filter.skip_packages_regex,
        ]
    )

    # Short-circuit if no filtering is needed
    if not needs_filtering:
        return changed_packages_per_system

    # When --package is used, we need to evaluate both changed and specified
    # packages to find their drv paths and intersect them. Batch all systems
    # into a single multi_system_eval call for parallelism.
    joined_per_system: dict[System, set[str]] = {}
    if package_filter.only_packages:
        # Build a combined attr set: all changed + specified packages per system
        changed_eval_input: dict[System, set[str]] = {}
        specified_eval_input: dict[System, set[str]] = {}
        for system, changed in changed_packages_per_system.items():
            changed_eval_input[system] = changed
            specified_eval_input[system] = package_filter.only_packages

        # Two multi_system_eval calls (one for changed, one for specified),
        # each evaluating all systems in parallel via nix-eval-jobs workers
        changed_results = multi_system_eval(
            changed_eval_input,
            build_config,
        )
        specified_results = multi_system_eval(
            specified_eval_input,
            build_config,
        )

        for system in changed_packages_per_system:
            changed_attrs = _collect_package_attrs(
                changed_results.get(system, []),
            )
            specified_attrs = _collect_package_attrs(
                specified_results.get(system, []),
                ignore_nonexisting=False,
            )
            joined_per_system[system] = _join_packages_for_system(
                changed_attrs, specified_attrs
            )

    result: dict[System, set[str]] = {}
    for system, changed_packages in changed_packages_per_system.items():
        packages: set[str] = set()

        if package_filter.only_packages:
            packages = joined_per_system.get(system, set())

        if package_filter.package_regexes:
            packages |= _match_package_regexes(
                changed_packages, package_filter.package_regexes
            )

        # If no packages selected yet, use all changed packages
        if not packages:
            packages = changed_packages.copy()

        result[system] = _apply_package_filters(
            packages,
            package_filter.skip_packages,
            package_filter.skip_packages_regex,
        )

    return result


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
        old_pkg = old_attrs.get(new_pkg.attr_path)
        if old_pkg is None or old_pkg.store_path != new_pkg.store_path:
            new_pkg.old_pkg = old_pkg
            changed_packages.append(new_pkg)
        if old_pkg:
            del old_attrs[old_pkg.attr_path]

    return (changed_packages, list(old_attrs.values()))


def package_filter_from_args(args: argparse.Namespace) -> PackageFilter:
    """Create a PackageFilter from parsed CLI arguments."""
    return PackageFilter(
        only_packages=set(args.package),
        additional_packages=set(args.additional_package),
        package_regexes=args.package_regex,
        skip_packages=set(args.skip_package),
        skip_packages_regex=args.skip_package_regex,
    )


def build_config_from_args(
    args: argparse.Namespace,
    allow: AllowedFeatures,
    nix_path: str,
    nixpkgs_config: Path,
) -> BuildConfig:
    """Create a BuildConfig from parsed CLI arguments."""
    return BuildConfig(
        allow=allow,
        nix_path=nix_path,
        local_system=current_system(),
        nixpkgs_config=nixpkgs_config,
        num_eval_workers=args.num_eval_workers,
        max_memory_size=args.max_memory_size,
    )


def _review_from_args(
    builddir: Builddir,
    args: argparse.Namespace,
    build_config: BuildConfig,
) -> Review:
    """Create a Review configured for local revision review."""
    return Review(
        builddir=builddir,
        package_filter=package_filter_from_args(args),
        build_config=build_config,
        review_config=ReviewConfig(
            remote=args.remote,
            extra_nixpkgs_config=args.extra_nixpkgs_config,
            systems=args.systems.split(" "),
            eval_type="local",
        ),
        shell_options=ShellOptions(
            no_shell=args.no_shell,
            run=args.run,
            sandbox=args.sandbox,
            build_args=args.build_args,
            build_graph=args.build_graph,
        ),
    )


@dataclass(frozen=True)
class LocalRevisionTarget:
    """What local revision to review and what to do after."""

    commit: str | None = None
    staged: bool = False
    action: ReviewAction | None = None


def review_local_revision(
    builddir_path: str,
    args: argparse.Namespace,
    build_config_factory: Callable[[str], BuildConfig],
    target: LocalRevisionTarget | None = None,
) -> Path:
    target = target or LocalRevisionTarget()
    with Builddir(builddir_path) as builddir:
        review = _review_from_args(
            builddir,
            args,
            build_config_factory(builddir.nix_path),
        )
        review.review_commit(
            builddir.path,
            args.branch,
            target.commit,
            action=target.action,
            staged=target.staged,
        )
        return builddir.path
