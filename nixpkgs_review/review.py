import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from re import Pattern
from typing import IO, Any
from xml.etree import ElementTree as ET

from . import eval_ci
from .allow import AllowedFeatures
from .builddir import Builddir
from .errors import NixpkgsReviewError
from .github import GithubClient
from .nix import Attr, nix_build, nix_eval, nix_shell
from .report import Report
from .utils import System, current_system, info, sh, system_order_key, warn

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
    if len(names) == 0:
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
    old_pkg: "Package | None" = field(init=False)


def print_updates(changed_pkgs: list[Package], removed_pkgs: list[Package]) -> None:
    new = []
    updated = []
    for pkg in changed_pkgs:
        if pkg.old_pkg is None:
            if pkg.version != "":
                new.append(f"{pkg.attr_path} (init at {pkg.version})")
            else:
                new.append(pkg.pname)
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
        api_token: str | None = None,
        use_github_eval: bool | None = True,
        only_packages: set[str] | None = None,
        package_regexes: list[Pattern[str]] | None = None,
        skip_packages: set[str] | None = None,
        skip_packages_regex: list[Pattern[str]] | None = None,
        checkout: CheckoutOption = CheckoutOption.MERGE,
        sandbox: bool = False,
        num_parallel_evals: int = 1,
        show_header: bool = True,
    ) -> None:
        if skip_packages_regex is None:
            skip_packages_regex = []
        if skip_packages is None:
            skip_packages = set()
        if package_regexes is None:
            package_regexes = []
        if only_packages is None:
            only_packages = set()
        self.builddir = builddir
        self.build_args = build_args
        self.no_shell = no_shell
        self.run = run
        self.remote = remote
        self.github_client = GithubClient(api_token)
        self.use_github_eval = use_github_eval
        self.checkout = checkout
        self.only_packages = only_packages
        self.package_regex = package_regexes
        self.skip_packages = skip_packages
        self.skip_packages_regex = skip_packages_regex
        self.local_system = current_system()
        match len(systems):
            case 0:
                msg = "Systems is empty"
                raise NixpkgsReviewError(msg)
            case 1:
                self.systems = self._process_aliases_for_systems(
                    next(iter(systems)).lower()
                )
            case _:
                self.systems = set(systems)
        self.allow = allow
        self.sandbox = sandbox
        self.build_graph = build_graph
        self.nixpkgs_config = nixpkgs_config
        self.extra_nixpkgs_config = extra_nixpkgs_config
        self.num_parallel_evals = num_parallel_evals
        self.show_header = show_header

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

    def git_merge(self, commit: str) -> None:
        res = sh(
            ["git", "merge", "--no-commit", "--no-ff", commit], cwd=self.worktree_dir()
        )
        if res.returncode != 0:
            msg = f"Failed to merge {commit} into {self.worktree_dir()}. git merge failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def git_checkout(self, commit: str) -> None:
        res = sh(["git", "checkout", commit], cwd=self.worktree_dir())
        if res.returncode != 0:
            msg = f"Failed to checkout {commit} in {self.worktree_dir()}. git checkout failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def apply_unstaged(self, staged: bool = False) -> None:
        args = [
            "git",
            "--no-pager",
            "diff",
            "--no-ext-diff",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        ]
        args.extend(["--staged"] if staged else [])
        with subprocess.Popen(args, stdout=subprocess.PIPE) as diff_proc:
            assert diff_proc.stdout
            diff = diff_proc.stdout.read()

        if not diff:
            info("No diff detected, stopping review...")
            sys.exit(0)

        info("Applying `nixpkgs` diff...")
        result = subprocess.run(
            ["git", "apply"], cwd=self.worktree_dir(), input=diff, check=False
        )

        if result.returncode != 0:
            warn(f"Failed to apply diff in {self.worktree_dir()}")
            sys.exit(1)

    def build_commit(
        self,
        base_commit: str,
        reviewed_commit: str | None,
        staged: bool = False,
    ) -> dict[System, list[Attr]]:
        """
        Review a local git commit
        """
        self.git_worktree(base_commit)

        print("Local evaluation for computing rebuilds")

        # Source: https://github.com/NixOS/nixpkgs/blob/master/ci/eval/README.md
        # TODO: make those overridable
        max_jobs: int = len(self.systems)
        # n_cores: int = multiprocessing.cpu_count() // max_jobs
        n_cores: int = self.num_parallel_evals
        chunk_size: int = 200_000

        with tempfile.TemporaryDirectory() as temp_dir:
            before_dir: str = str(temp_dir / Path("before_eval_results"))
            after_dir: str = str(temp_dir / Path("after_eval_results"))
            # TODO: handle `self.allow` settings
            eval_ci.local_eval(
                worktree_dir=self.builddir.worktree_dir,
                systems=self.systems,
                max_jobs=max_jobs,
                n_cores=n_cores,
                chunk_size=chunk_size,
                output_dir=before_dir,
            )

            if reviewed_commit is None:
                self.apply_unstaged(staged)
            elif self.checkout == CheckoutOption.MERGE:
                self.git_checkout(reviewed_commit)
            else:
                self.git_merge(reviewed_commit)

            eval_ci.local_eval(
                worktree_dir=self.builddir.worktree_dir,
                systems=self.systems,
                max_jobs=max_jobs,
                n_cores=n_cores,
                chunk_size=chunk_size,
                output_dir=after_dir,
            )

            # merged_packages: dict[System, list[Package]] = list_packages(
            #     self.builddir.nix_path,
            #     self.systems,
            #     self.allow,
            #     n_threads=self.num_parallel_evals,
            #     check_meta=True,
            # )

            output_dir: Path = temp_dir / Path("comparison")
            eval_ci.compare(
                worktree_dir=self.builddir.worktree_dir,
                before_dir=before_dir,
                after_dir=after_dir,
                output_dir=str(output_dir),
            )

            with (output_dir / Path("changed-paths.json")).open() as compare_result:
                outpaths_dict: dict[str, Any] = json.load(compare_result)

        # Systems ordered correctly (x86_64-linux, aarch64-linux, x86_64-darwin, aarch64-darwin)
        sorted_systems: list[System] = sorted(
            self.systems,
            key=system_order_key,
            reverse=True,
        )

        changed_attrs: dict[System, set[str]] = {}
        for system in sorted_systems:
            print(f"--------- Rebuilds on '{system}' ---------")

            rebuilds: set[str] = set(
                outpaths_dict["rebuildsByPlatform"].get(system, [])
            )
            print_packages(
                names=list(rebuilds),
                msg="to rebuild",
            )

            changed_attrs[system] = rebuilds

        return self.build(changed_attrs, self.build_args)

    def git_worktree(self, commit: str) -> None:
        res = sh(["git", "worktree", "add", self.worktree_dir(), commit])
        if res.returncode != 0:
            msg = f"Failed to add worktree for {commit} in {self.worktree_dir()}. git worktree failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)

    def build(
        self, packages_per_system: dict[System, set[str]], args: str
    ) -> dict[System, list[Attr]]:
        for system, packages in packages_per_system.items():
            packages_per_system[system] = filter_packages(
                packages,
                self.only_packages,
                self.package_regex,
                self.skip_packages,
                self.skip_packages_regex,
                system,
                self.allow,
                self.builddir.nix_path,
            )
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
        pr = self.github_client.pull_request(pr_number)

        packages_per_system: dict[System, set[str]] | None = None
        if self.use_github_eval and all(system in PLATFORMS for system in self.systems):
            # Attempt to fetch the GitHub actions evaluation result
            print("-> Attempting to fetch eval results from GitHub actions")
            packages_per_system = self.github_client.get_github_action_eval_result(pr)

            if packages_per_system is not None:
                print("-> Successfully fetched rebuilds: no local evaluation needed")

        else:
            packages_per_system = None

        if self.checkout == CheckoutOption.MERGE:
            base_rev, pr_rev = fetch_refs(
                self.remote,
                pr["base"]["ref"],
                f"pull/{pr['number']}/merge",
            )
        else:
            merge_rev, pr_rev = fetch_refs(
                self.remote,
                pr["base"]["ref"],
                f"pull/{pr['number']}/head",
            )
            run = subprocess.run(
                ["git", "merge-base", merge_rev, pr_rev],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
            )
            if run.returncode != 0:
                msg = f"Failed to get the merge base of {merge_rev} with PR {pr_rev}"
                raise NixpkgsReviewError(msg)
            base_rev = run.stdout.strip()

        if packages_per_system is None:
            return self.build_commit(base_rev, pr_rev)

        self.git_worktree(pr_rev)

        for system in list(packages_per_system.keys()):
            if system not in self.systems:
                packages_per_system.pop(system)
        return self.build(packages_per_system, self.build_args)

    def start_review(
        self,
        attrs_per_system: dict[System, list[Attr]],
        path: Path,
        pr: int | None = None,
        post_result: bool | None = False,
        print_result: bool = False,
    ) -> bool:
        os.environ.pop("NIXPKGS_CONFIG", None)
        os.environ["NIXPKGS_REVIEW_ROOT"] = str(path)
        if pr:
            os.environ["PR"] = str(pr)
        report = Report(
            attrs_per_system,
            self.extra_nixpkgs_config,
            checkout=self.checkout.name.lower(),  # type: ignore[arg-type]
            show_header=self.show_header,
        )
        report.print_console(pr)
        report.write(path, pr)

        if pr and post_result:
            self.github_client.comment_issue(pr, report.markdown(pr))

        if print_result:
            print(report.markdown(pr))

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
                self.sandbox,
            )

        return report.succeeded()

    def review_commit(
        self,
        path: Path,
        branch: str,
        reviewed_commit: str | None,
        staged: bool = False,
        print_result: bool = False,
    ) -> None:
        branch_rev = fetch_refs(self.remote, branch)[0]
        self.start_review(
            self.build_commit(branch_rev, reviewed_commit, staged),
            path,
            print_result=print_result,
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
        if elem.tag == "item":
            if event == "start":
                attrs = elem.attrib
                homepage = None
                description = None
                position = None
                path = None
            else:
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
        elif event == "start" and elem.tag == "output" and elem.attrib["name"] == "out":
            path = elem.attrib["path"]
        elif event == "start" and elem.tag == "meta":
            name = elem.attrib["name"]
            if name not in ["homepage", "description", "position"]:
                continue
            if elem.attrib["type"] == "strings":
                values = (e.attrib["value"] for e in elem)
                value = ", ".join(values)
            else:
                value = elem.attrib["value"]
            if name == "homepage":
                homepage = value
            elif name == "description":
                description = value
            elif name == "position":
                position = value
    return packages


def package_attrs(
    package_set: set[str],
    system: str,
    allow: AllowedFeatures,
    nix_path: str,
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
        warn("These packages do not exist:")
        warn(" ".join(nonexisting))
        sys.exit(1)
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
        warn(
            "The following packages specified with `-p` are not rebuilt by the pull request"
        )
        warn(" ".join(specified_attrs[path].name for path in nonexistent))
        sys.exit(1)
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

    if (
        len(specified_packages) == 0
        and len(package_regexes) == 0
        and len(skip_packages) == 0
        and len(skip_package_regexes) == 0
    ):
        return changed_packages

    if len(specified_packages) > 0:
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
        packages = changed_packages

    if len(skip_packages) > 0:
        for package in skip_packages:
            packages.discard(package)

    for attr in packages.copy():
        for regex in skip_package_regexes:
            if regex.match(attr):
                packages.discard(attr)

    return packages


def fetch_refs(repo: str, *refs: str) -> list[str]:
    cmd = ["git", "-c", "fetch.prune=false", "fetch", "--no-tags", "--force", repo]
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if shallow.returncode != 0:
        msg = f"Failed to detect if {repo} is shallow repository"
        raise NixpkgsReviewError(msg)
    if shallow.stdout.strip() == "true":
        cmd.append("--depth=1")
    for i, ref in enumerate(refs):
        cmd.append(f"{ref}:refs/nixpkgs-review/{i}")
    res = sh(cmd)
    if res.returncode != 0:
        msg = f"Failed to fetch {refs} from {repo}. git fetch failed with exit code {res.returncode}"
        raise NixpkgsReviewError(msg)
    shas = []
    for i, ref in enumerate(refs):
        cmd = ["git", "rev-parse", "--verify", f"refs/nixpkgs-review/{i}"]
        out = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, check=False)
        if out.returncode != 0:
            msg = f"Failed to fetch {ref} from {repo} with command: {''.join(cmd)}"
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
        review.review_commit(builddir.path, args.branch, commit, staged, print_result)
        return builddir.path
