import io
import json
import multiprocessing
import os
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Set, Tuple

from .github import GithubClient
from .utils import info, sh, warn

ROOT = Path(os.path.dirname(os.path.realpath(__file__)))


class CheckoutOption(Enum):
    # Merge pull request into the target branch
    MERGE = 1
    # Checkout the committer's pull request. This is useful if changes in the
    # target branch has not been build yet by hydra and would trigger too many
    # builds. This option comes at the cost of ignoring the latest changes of
    # the target branch.
    COMMIT = 2


class Attr:
    def __init__(
        self,
        name: str,
        exists: bool,
        broken: bool,
        blacklisted: bool,
        path: Optional[str],
    ) -> None:
        self.name = name
        self.exists = exists
        self.broken = broken
        self.blacklisted = blacklisted
        self.path = path

    def was_build(self) -> bool:
        if self.path is None:
            return False
        res = subprocess.run(
            ["nix-store", "--verify-path", self.path], stderr=subprocess.DEVNULL
        )
        return res.returncode == 0

    def is_test(self) -> bool:
        return self.name.startswith("nixosTests")


def native_packages(packages_per_system: Dict[str, Set[str]]) -> Set[str]:
    nix_eval = subprocess.run(
        ["nix", "eval", "--raw", "nixpkgs.system"], check=True, stdout=subprocess.PIPE
    )
    return set(packages_per_system[nix_eval.stdout.decode("utf-8")])


class Review:
    def __init__(
        self,
        worktree_dir: str,
        build_args: str,
        api_token: Optional[str] = None,
        use_ofborg_eval: Optional[bool] = True,
        only_packages: Set[str] = set(),
        package_regexes: List[Pattern[str]] = [],
        checkout: CheckoutOption = CheckoutOption.MERGE,
    ) -> None:
        self.worktree_dir = worktree_dir
        self.build_args = build_args
        self.github_client = GithubClient(api_token)
        self.use_ofborg_eval = use_ofborg_eval
        self.checkout = checkout
        self.only_packages = only_packages
        self.package_regex = package_regexes

    def git_merge(self, commit: str) -> None:
        sh(["git", "merge", "--no-commit", commit], cwd=self.worktree_dir)

    def build_commit(self, base_commit: str, reviewed_commit: str) -> List[Attr]:
        """
        Review a local git commit
        """
        git_worktree(self.worktree_dir, base_commit)
        base_packages = list_packages(self.worktree_dir)

        self.git_merge(reviewed_commit)

        merged_packages = list_packages(self.worktree_dir, check_meta=True)

        attrs = differences(base_packages, merged_packages)
        return self.build(attrs, self.build_args)

    def checkout_pr(self, base_rev: str, pr_rev: str) -> None:
        if self.checkout == CheckoutOption.MERGE:
            git_worktree(self.worktree_dir, base_rev)
            self.git_merge(pr_rev)
        else:
            git_worktree(self.worktree_dir, pr_rev)

    def build(self, packages: Set[str], args: str) -> List[Attr]:
        packages = filter_packages(packages, self.only_packages, self.package_regex)
        return build(packages, args)

    def build_pr(self, pr_number: int) -> List[Attr]:
        pr = self.github_client.get(f"repos/NixOS/nixpkgs/pulls/{pr_number}")
        if self.use_ofborg_eval:
            packages_per_system = self.github_client.get_borg_eval_gist(pr)
        else:
            packages_per_system = None
        merge_rev, pr_rev = fetch_refs(pr["base"]["ref"], f"pull/{pr['number']}/head")

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

    def review_commit(self, branch: str, reviewed_commit: str) -> None:
        branch_rev = fetch_refs(branch)[0]
        nix_shell(self.build_commit(branch_rev, reviewed_commit))

    def review_pr(self, pr_number: int) -> None:
        """
        Review a pull request from the nixpkgs github repository
        """
        nix_shell(self.build_pr(pr_number))


def nix_shell(attrs: List[Attr]) -> None:
    cmd = ["nix-shell"]

    broken = []
    failed = []
    non_existant = []
    blacklisted = []
    tests = []

    for a in attrs:
        if a.broken:
            broken.append(a.name)
        elif a.blacklisted:
            blacklisted.append(a.name)
        elif not a.exists:
            non_existant.append(a.name)
        elif a.name.startswith("nixosTests."):
            tests.append(a.name)
        elif not a.was_build():
            failed.append(a.name)
        else:
            cmd.append("-p")
            cmd.append(a.name)

    error_msgs = []

    if len(broken) > 0:
        error_msgs.append(
            f"{len(broken)} package(s) are marked as broken and were skipped:"
        )
        error_msgs.append(" ".join(broken))

    if len(non_existant) > 0:
        error_msgs.append(
            f"{len(non_existant)} package(s) were present in ofBorgs evaluation, but not found in our checkout:"
        )
        error_msgs.append(" ".join(non_existant))

    if len(blacklisted) > 0:
        error_msgs.append(f"{len(blacklisted)} package(s) were blacklisted:")
        error_msgs.append(" ".join(blacklisted))

    if len(failed) > 0:
        error_msgs.append(f"{len(failed)} package(s) failed to build:")
        error_msgs.append(" ".join(failed))

    if len(error_msgs) > 0:
        warn("\n".join(error_msgs))

    if len(tests) > 0:
        info("The following tests where build")
        info(" ".join(tests))

    if len(cmd) == 1:
        info("No packages were successfully build, skip nix-shell")
    else:
        sh(cmd)


def git_worktree(worktree_dir: str, commit: str) -> None:
    sh(["git", "worktree", "add", worktree_dir, commit])


def eval_attrs(resultdir: str, attrs: Set[str]) -> List[Attr]:
    """
    Filter broken or non-existing attributes.
    """
    attr_json = os.path.join(resultdir, "attr.json")
    with open(attr_json, "w+") as f:
        json.dump(list(attrs), f)
        f.flush()
    cmd = [
        "nix",
        "eval",
        "--json",
        f"((import {str(ROOT.joinpath('nix/evalAttrs.nix'))}) {{ attr-json = {attr_json}; }})",
    ]
    # workaround https://github.com/NixOS/ofborg/issues/269
    blacklist = set(
        ["tests.nixos-functions.nixos-test", "tests.nixos-functions.nixosTest-test"]
    )

    results = []
    nix_eval = subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    for name, props in json.loads(nix_eval.stdout).items():
        attr = Attr(
            name=name,
            exists=props["exists"],
            broken=props["broken"],
            blacklisted=name in blacklist,
            path=props["path"],
        )
        results.append(attr)
    return results


def build(attr_names: Set[str], args: str) -> List[Attr]:
    if not attr_names:
        info("Nothing changed")
        return []

    result_dir = tempfile.TemporaryDirectory(prefix="nix-review-")

    attrs = eval_attrs(result_dir.name, attr_names)
    filtered = []
    for attr in attrs:
        if not (attr.broken or attr.blacklisted):
            filtered.append(attr.name)

    if len(filtered) == 0:
        return attrs

    info("Building in {}".format(result_dir.name))
    command = [
        "nix",
        "build",
        "-f",
        "<nixpkgs>",
        "--keep-going",
        # only matters for single-user nix and trusted users
        "--max-jobs",
        str(multiprocessing.cpu_count()),
        "--option",
        "build-use-sandbox",
        "true",
    ] + shlex.split(args)

    for a in filtered:
        command.append(a)
    try:
        sh(command, cwd=result_dir.name)
    except subprocess.CalledProcessError:
        pass
    return attrs


PackageSet = Set[Tuple[str, str]]


def list_packages(path: str, check_meta: bool = False) -> PackageSet:
    cmd = ["nix-env", "-f", path, "-qaP", "--xml", "--out-path", "--show-trace"]
    if check_meta:
        cmd.append("--meta")
    nix_env = subprocess.run(cmd, stdout=subprocess.PIPE)
    context = ET.iterparse(
        io.StringIO(nix_env.stdout.decode("utf-8")), events=("start",)
    )
    packages = set()
    for (event, elem) in context:
        if elem.tag == "item":
            attrib = elem.attrib["attrPath"]
        elif elem.tag == "output":
            assert attrib is not None
            path = elem.attrib["path"]
            packages.add((attrib, path))
    return packages


def package_attrs(
    tempdir: str, package_set: Set[str], ignore_nonexisting: bool = True
) -> Dict[str, Attr]:
    attrs: Dict[str, Attr] = {}

    nonexisting = []

    for attr in eval_attrs(tempdir, package_set):
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
    with tempfile.TemporaryDirectory(prefix="nix-review-") as tempdir:
        changed_attrs = package_attrs(tempdir, changed_packages)
        specified_attrs = package_attrs(
            tempdir, specified_packages, ignore_nonexisting=False
        )

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


def fetch_refs(*refs: str) -> List[str]:
    cmd = ["git", "fetch", "--force", "https://github.com/NixOS/nixpkgs"]
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
