import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Dict, List, Optional, Pattern, Set, Tuple

from .builddir import Builddir
from .github import GithubClient
from .nix import Attr, nix_build, nix_eval, nix_shell
from .report import Report
from .utils import info, sh, warn


class CheckoutOption(Enum):
    # Merge pull request into the target branch
    MERGE = 1
    # Checkout the committer's pull request. This is useful if changes in the
    # target branch has not been build yet by hydra and would trigger too many
    # builds. This option comes at the cost of ignoring the latest changes of
    # the target branch.
    COMMIT = 2


def native_packages(packages_per_system: Dict[str, Set[str]]) -> Set[str]:
    system = subprocess.run(
        ["nix", "eval", "--raw", "nixpkgs.system"], check=True, stdout=subprocess.PIPE
    )
    return set(packages_per_system[system.stdout.decode("utf-8")])


class Review:
    def __init__(
        self,
        builddir: Builddir,
        build_args: str,
        api_token: Optional[str] = None,
        use_ofborg_eval: Optional[bool] = True,
        only_packages: Set[str] = set(),
        package_regexes: List[Pattern[str]] = [],
        checkout: CheckoutOption = CheckoutOption.MERGE,
    ) -> None:
        self.builddir = builddir
        self.build_args = build_args
        self.github_client = GithubClient(api_token)
        self.use_ofborg_eval = use_ofborg_eval
        self.checkout = checkout
        self.only_packages = only_packages
        self.package_regex = package_regexes

    def worktree_dir(self) -> str:
        return str(self.builddir.worktree_dir)

    def git_merge(self, commit: str) -> None:
        sh(["git", "merge", "--no-commit", commit], cwd=self.worktree_dir())

    def apply_unstaged(self, staged: bool = False) -> None:
        args = ["git", "--no-pager", "diff"]
        args.extend(["--staged"] if staged else [])
        diff_proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        diff = diff_proc.stdout.read()

        if not diff:
            info("No diff detected, stopping review...")
            sys.exit(0)

        info("Applying `nixpkgs` diff...")
        result = subprocess.run(["git", "apply"], cwd=self.worktree_dir(), input=diff)

        if result.returncode != 0:
            warn("Failed to apply diff in %s" % self.worktree_dir())
            sys.exit(1)

    def build_commit(
        self, base_commit: str, reviewed_commit: Optional[str], staged: bool = False
    ) -> List[Attr]:
        """
        Review a local git commit
        """
        self.git_worktree(base_commit)
        base_packages = list_packages(str(self.worktree_dir()))

        if reviewed_commit is None:
            self.apply_unstaged(staged)
        else:
            self.git_merge(reviewed_commit)

        merged_packages = list_packages(str(self.worktree_dir()), check_meta=True)

        attrs = differences(base_packages, merged_packages)
        return self.build(attrs, self.build_args)

    def git_worktree(self, commit: str) -> None:
        sh(["git", "worktree", "add", self.worktree_dir(), commit])

    def checkout_pr(self, base_rev: str, pr_rev: str) -> None:
        if self.checkout == CheckoutOption.MERGE:
            self.git_worktree(base_rev)
            self.git_merge(pr_rev)
        else:
            self.git_worktree(pr_rev)

    def build(self, packages: Set[str], args: str) -> List[Attr]:
        packages = filter_packages(packages, self.only_packages, self.package_regex)
        return nix_build(packages, args, self.builddir.path)

    def build_pr(self, pr_number: int) -> List[Attr]:
        pr = self.github_client.get(f"repos/NixOS/nixpkgs/pulls/{pr_number}")
        if self.use_ofborg_eval:
            packages_per_system = self.github_client.get_borg_eval_gist(pr)
        else:
            packages_per_system = None
        merge_rev, pr_rev = fetch_refs(
            "https://github.com/NixOS/nixpkgs",
            pr["base"]["ref"],
            f"pull/{pr['number']}/head",
        )

        if self.checkout == CheckoutOption.MERGE:
            base_rev = merge_rev
        else:
            run = subprocess.run(
                ["git", "merge-base", merge_rev, pr_rev],
                check=True,
                stdout=subprocess.PIPE,
            )
            base_rev = run.stdout.decode("utf-8").strip()

        if packages_per_system is None:
            return self.build_commit(base_rev, pr_rev)

        self.checkout_pr(base_rev, pr_rev)

        packages = native_packages(packages_per_system)
        return self.build(packages, self.build_args)

    def start_review(self, attr: List[Attr], pr: Optional[int] = None) -> None:
        os.environ["NIX_PATH"] = self.builddir.nixpkgs_path()
        report = Report(attr)
        report.print_console(pr)
        report.write(self.builddir.path, pr)
        nix_shell(report.built_packages(), self.builddir.path)

    def review_commit(
        self,
        branch: str,
        remote: str,
        reviewed_commit: Optional[str],
        staged: bool = False,
    ) -> None:
        branch_rev = fetch_refs(remote, branch)[0]
        self.start_review(self.build_commit(branch_rev, reviewed_commit, staged))


PackageSet = Set[Tuple[str, str]]


def list_packages(path: str, check_meta: bool = False) -> PackageSet:
    cmd = ["nix-env", "-f", path, "-qaP", "--xml", "--out-path", "--show-trace"]
    if check_meta:
        cmd.append("--meta")
    info("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    packages = set()
    with proc as nix_env:
        context = ET.iterparse(nix_env.stdout, events=("start",))
        for (event, elem) in context:
            if elem.tag == "item":
                attrib = elem.attrib["attrPath"]
            elif elem.tag == "output":
                assert attrib is not None
                path = elem.attrib["path"]
                packages.add((attrib, path))
    return packages


def package_attrs(
    package_set: Set[str], ignore_nonexisting: bool = True
) -> Dict[str, Attr]:
    attrs: Dict[str, Attr] = {}

    nonexisting = []

    for attr in nix_eval(package_set):
        if not attr.exists:
            nonexisting.append(attr.name)
        elif not attr.broken:
            assert attr.path is not None
            attrs[attr.path] = attr

    if not ignore_nonexisting and len(nonexisting) > 0:
        warn(f"The packages do not exists:")
        warn(" ".join(nonexisting))
        sys.exit(1)
    return attrs


def join_packages(changed_packages: Set[str], specified_packages: Set[str]) -> Set[str]:
    changed_attrs = package_attrs(changed_packages)
    specified_attrs = package_attrs(specified_packages, ignore_nonexisting=False)

    tests: Dict[str, Attr] = {}
    for path, attr in specified_attrs.items():
        # ofborg does not include tests and manual evaluation is too expensive
        if attr.is_test():
            tests[path] = attr

    nonexistant = specified_attrs.keys() - changed_attrs.keys() - tests.keys()

    if len(nonexistant) != 0:
        warn(
            "The following packages specified with `-p` are not rebuild by the pull request"
        )
        warn(" ".join(specified_attrs[path].name for path in nonexistant))
        sys.exit(1)
    union_paths = (changed_attrs.keys() & specified_attrs.keys()) | tests.keys()

    return set(specified_attrs[path].name for path in union_paths)


def filter_packages(
    changed_packages: Set[str],
    specified_packages: Set[str],
    package_regexes: List[Pattern[str]],
) -> Set[str]:
    packages: Set[str] = set()

    if len(specified_packages) == 0 and len(package_regexes) == 0:
        return changed_packages

    if len(specified_packages) > 0:
        packages = join_packages(changed_packages, specified_packages)

    for attr in changed_packages:
        for regex in package_regexes:
            if regex.match(attr):
                packages.add(attr)
    return packages


def fetch_refs(repo: str, *refs: str) -> List[str]:
    cmd = ["git", "-c", "fetch.prune=false", "fetch", "--force", repo]
    for i, ref in enumerate(refs):
        cmd.append(f"{ref}:refs/nix-review/{i}")
    sh(cmd)
    shas = []
    for i, ref in enumerate(refs):
        out = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"refs/nix-review/{i}"]
        )
        shas.append(out.strip().decode("utf-8"))
    return shas


def differences(old: PackageSet, new: PackageSet) -> Set[str]:
    raw = new - old
    return {l[0] for l in raw}


def review_local_revision(
    builddir_path: str,
    args: argparse.Namespace,
    commit: Optional[str],
    staged: bool = False,
) -> None:
    with Builddir(builddir_path) as builddir:
        review = Review(
            builddir=builddir,
            build_args=args.build_args,
            only_packages=set(args.package),
            package_regexes=args.package_regex,
        )
        review.review_commit(args.branch, args.remote, commit, staged)
