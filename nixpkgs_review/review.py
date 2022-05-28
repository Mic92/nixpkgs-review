import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import IO, Dict, List, Optional, Pattern, Set, Tuple

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


def native_packages(packages_per_system: Dict[str, Set[str]], system: str) -> Set[str]:
    return set(packages_per_system[system])


def print_packages(
    names: List[str],
    msg: str,
) -> None:
    if len(names) == 0:
        return
    plural = "s" if len(names) > 1 else ""

    print(f"{len(names)} package{plural} {msg}:")
    print(" ".join(names))
    print("")


@dataclass
class Package:
    pname: str
    version: str
    attr_path: str
    store_path: Optional[str]
    homepage: Optional[str]
    description: Optional[str]
    position: Optional[str]
    old_pkg: "Optional[Package]" = field(init=False)


def print_updates(changed_pkgs: List[Package], removed_pkgs: List[Package]) -> None:
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

    removed = list(f"{p.pname} (†{p.version})" for p in removed_pkgs)

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
        system: str,
        api_token: Optional[str] = None,
        use_ofborg_eval: Optional[bool] = True,
        only_packages: Set[str] = set(),
        package_regexes: List[Pattern[str]] = [],
        skip_packages: Set[str] = set(),
        skip_packages_regex: List[Pattern[str]] = [],
        checkout: CheckoutOption = CheckoutOption.MERGE,
        allow_aliases: bool = False,
        sandbox: bool = False,
    ) -> None:
        self.builddir = builddir
        self.build_args = build_args
        self.no_shell = no_shell
        self.run = run
        self.remote = remote
        self.github_client = GithubClient(api_token)
        self.use_ofborg_eval = use_ofborg_eval
        self.checkout = checkout
        self.only_packages = only_packages
        self.package_regex = package_regexes
        self.skip_packages = skip_packages
        self.skip_packages_regex = skip_packages_regex
        self.system = system
        self.allow_aliases = allow_aliases
        self.sandbox = sandbox

    def worktree_dir(self) -> str:
        return str(self.builddir.worktree_dir)

    def git_merge(self, commit: str) -> None:
        sh(["git", "merge", "--no-commit", "--no-ff", commit], cwd=self.worktree_dir())

    def apply_unstaged(self, staged: bool = False) -> None:
        args = ["git", "--no-pager", "diff", "--no-ext-diff"]
        args.extend(["--staged"] if staged else [])
        diff_proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        assert diff_proc.stdout
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
        base_packages = list_packages(str(self.worktree_dir()), self.system)

        if reviewed_commit is None:
            self.apply_unstaged(staged)
        else:
            self.git_merge(reviewed_commit)

        merged_packages = list_packages(
            str(self.worktree_dir()), self.system, check_meta=True
        )

        changed_pkgs, removed_pkgs = differences(base_packages, merged_packages)
        changed_attrs = set(p.attr_path for p in changed_pkgs)
        print_updates(changed_pkgs, removed_pkgs)
        return self.build(changed_attrs, self.build_args)

    def git_worktree(self, commit: str) -> None:
        sh(["git", "worktree", "add", self.worktree_dir(), commit])

    def checkout_pr(self, base_rev: str, pr_rev: str) -> None:
        if self.checkout == CheckoutOption.MERGE:
            self.git_worktree(base_rev)
            self.git_merge(pr_rev)
        else:
            self.git_worktree(pr_rev)

    def build(self, packages: Set[str], args: str) -> List[Attr]:
        packages = filter_packages(
            packages,
            self.only_packages,
            self.package_regex,
            self.skip_packages,
            self.skip_packages_regex,
            self.system,
            self.allow_aliases,
        )
        return nix_build(
            packages, args, self.builddir.path, self.system, self.allow_aliases
        )

    def build_pr(self, pr_number: int) -> List[Attr]:
        pr = self.github_client.pull_request(pr_number)

        if self.use_ofborg_eval:
            packages_per_system = self.github_client.get_borg_eval_gist(pr)
        else:
            packages_per_system = None
        merge_rev, pr_rev = fetch_refs(
            self.remote,
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
                text=True,
            )
            base_rev = run.stdout.strip()

        if packages_per_system is None:
            return self.build_commit(base_rev, pr_rev)

        self.checkout_pr(base_rev, pr_rev)

        packages = native_packages(packages_per_system, self.system)
        return self.build(packages, self.build_args)

    def start_review(
        self,
        attr: List[Attr],
        path: Path,
        pr: Optional[int] = None,
        post_result: Optional[bool] = False,
    ) -> None:
        os.environ.pop("NIXPKGS_CONFIG", None)
        os.environ["NIX_PATH"] = path.as_posix()
        if pr:
            os.environ["PR"] = str(pr)
        report = Report(self.system, attr)
        report.print_console(pr)
        report.write(path, pr)

        if pr and post_result:
            self.github_client.comment_issue(pr, report.markdown(pr))

        if self.no_shell:
            sys.exit(0 if report.succeeded() else 1)
        else:
            nix_shell(
                report.built_packages(), path, self.system, self.run, self.sandbox
            )

    def review_commit(
        self,
        path: Path,
        branch: str,
        reviewed_commit: Optional[str],
        staged: bool = False,
    ) -> None:
        branch_rev = fetch_refs(self.remote, branch)[0]
        self.start_review(self.build_commit(branch_rev, reviewed_commit, staged), path)


def parse_packages_xml(stdout: IO[str]) -> List[Package]:
    packages: List[Package] = []
    path = None
    context = ET.iterparse(stdout, events=("start", "end"))
    for (event, elem) in context:
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


def list_packages(path: str, system: str, check_meta: bool = False) -> List[Package]:
    cmd = [
        "nix-env",
        "--option",
        "system",
        system,
        "-f",
        path,
        "-qaP",
        "--xml",
        "--out-path",
        "--show-trace",
    ]
    if check_meta:
        cmd.append("--meta")
    info("$ " + " ".join(cmd))
    with tempfile.NamedTemporaryFile(mode="w") as tmp:
        subprocess.run(cmd, stdout=tmp, check=True)
        tmp.flush()
        with open(tmp.name) as f:
            return parse_packages_xml(f)


def package_attrs(
    package_set: Set[str],
    system: str,
    ignore_nonexisting: bool = True,
    allow_aliases: bool = False,
) -> Dict[str, Attr]:
    attrs: Dict[str, Attr] = {}

    nonexisting = []

    for attr in nix_eval(package_set, system, allow_aliases):
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
    changed_packages: Set[str],
    specified_packages: Set[str],
    system: str,
    allow_aliases: bool,
) -> Set[str]:
    changed_attrs = package_attrs(changed_packages, system)
    specified_attrs = package_attrs(
        specified_packages,
        system,
        ignore_nonexisting=False,
        allow_aliases=allow_aliases,
    )

    tests: Dict[str, Attr] = {}
    for path, attr in specified_attrs.items():
        # ofborg does not include tests and manual evaluation is too expensive
        if attr.is_test():
            tests[path] = attr

    nonexistant = specified_attrs.keys() - changed_attrs.keys() - tests.keys()

    if len(nonexistant) != 0:
        warn(
            "The following packages specified with `-p` are not rebuilt by the pull request"
        )
        warn(" ".join(specified_attrs[path].name for path in nonexistant))
        sys.exit(1)
    union_paths = (changed_attrs.keys() & specified_attrs.keys()) | tests.keys()

    return set(specified_attrs[path].name for path in union_paths)


def filter_packages(
    changed_packages: Set[str],
    specified_packages: Set[str],
    package_regexes: List[Pattern[str]],
    skip_packages: Set[str],
    skip_package_regexes: List[Pattern[str]],
    system: str,
    allow_aliases: bool,
) -> Set[str]:
    packages: Set[str] = set()

    if (
        len(specified_packages) == 0
        and len(package_regexes) == 0
        and len(skip_packages) == 0
        and len(skip_package_regexes) == 0
    ):
        return changed_packages

    if len(specified_packages) > 0:
        packages = join_packages(
            changed_packages, specified_packages, system, allow_aliases
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


def fetch_refs(repo: str, *refs: str) -> List[str]:
    cmd = ["git", "-c", "fetch.prune=false", "fetch", "--no-tags", "--force", repo]
    for i, ref in enumerate(refs):
        cmd.append(f"{ref}:refs/nixpkgs-review/{i}")
    sh(cmd)
    shas = []
    for i, ref in enumerate(refs):
        out = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"refs/nixpkgs-review/{i}"], text=True
        )
        shas.append(out.strip())
    return shas


def differences(
    old: List[Package], new: List[Package]
) -> Tuple[List[Package], List[Package]]:
    old_attrs = dict((pkg.attr_path, pkg) for pkg in old)
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
    commit: Optional[str],
    staged: bool = False,
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
            system=args.system,
        )
        review.review_commit(builddir.path, args.branch, commit, staged)
        return builddir.path
