import io
import json
import multiprocessing
import os
import shlex
import subprocess
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple

from .utils import sh

ROOT = Path(os.path.dirname(os.path.realpath(__file__)))


class GithubClient:
    def __init__(self, api_token: Optional[str]) -> None:
        self.api_token = api_token

    def get(self, path: str) -> Any:
        url = urllib.parse.urljoin("https://api.github.com/", path)
        req = urllib.request.Request(url)
        if self.api_token:
            req.add_header("Authorization", f"token {self.api_token}")
        return json.loads(urllib.request.urlopen(req).read())


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
        self, name: str, exists: bool, broken: bool, path: Optional[str]
    ) -> None:
        self.name = name
        self.exists = exists
        self.broken = broken
        self.path = path

    def was_build(self) -> bool:
        if self.path is None:
            return False
        res = subprocess.run(
            ["nix-store", "--verify-path", self.path], stderr=subprocess.DEVNULL
        )
        return res.returncode == 0


def native_packages(packages_per_system: Dict[str, Set[str]]) -> Set[str]:
    system = subprocess.check_output(["nix", "eval", "--raw", "nixpkgs.system"]).decode(
        "utf-8"
    )
    return packages_per_system[system]


class Review:
    def __init__(
        self,
        worktree_dir: str,
        build_args: str,
        api_token: Optional[str] = None,
        use_ofborg_eval: Optional[bool] = True,
        checkout: CheckoutOption = CheckoutOption.MERGE,
    ) -> None:
        self.worktree_dir = worktree_dir
        self.build_args = build_args
        self.github_client = GithubClient(api_token)
        self.use_ofborg_eval = use_ofborg_eval
        self.checkout = checkout

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
        return build(attrs, self.build_args)

    def checkout_pr(self, base_rev: str, pr_rev: str) -> None:
        if self.checkout == CheckoutOption.MERGE:
            git_worktree(self.worktree_dir, base_rev)
            self.git_merge(pr_rev)
        else:
            git_worktree(self.worktree_dir, pr_rev)

    def build_pr(self, pr_number: int) -> List[Attr]:
        pr = self.github_client.get(f"repos/NixOS/nixpkgs/pulls/{pr_number}")
        if self.use_ofborg_eval:
            packages_per_system = self.get_borg_eval_gist(pr)
        else:
            packages_per_system = None
        merge_rev, pr_rev = fetch_refs(pr["base"]["ref"], f"pull/{pr['number']}/head")

        if self.checkout == CheckoutOption.MERGE:
            base_rev = merge_rev
        else:
            base_rev = (
                subprocess.check_output(["git", "merge-base", merge_rev, pr_rev])
                .decode("utf-8")
                .strip()
            )

        if packages_per_system is None:
            return self.build_commit(base_rev, pr_rev)

        self.checkout_pr(base_rev, pr_rev)

        packages = native_packages(packages_per_system)

        return build(packages, self.build_args)

    def review_commit(self, branch: str, reviewed_commit: str) -> None:
        branch_rev = fetch_refs(branch)[0]
        nix_shell(self.build_commit(branch_rev, reviewed_commit))

    def review_pr(self, pr_number: int) -> None:
        """
        Review a pull request from the nixpkgs github repository
        """
        nix_shell(self.build_pr(pr_number))

    def get_borg_eval_gist(self, pr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        packages_per_system: DefaultDict[str, list] = defaultdict(list)
        statuses = self.github_client.get(pr["statuses_url"])
        for status in statuses:
            url = status.get("target_url", "")
            if (
                status["description"] == "^.^!"
                and status["creator"]["login"] == "GrahamcOfBorg"
                and url != ""
            ):
                url = urllib.parse.urlparse(url)
                raw_gist_url = (
                    f"https://gist.githubusercontent.com/GrahamcOfBorg{url.path}/raw/"
                )
                for line in urllib.request.urlopen(raw_gist_url):
                    if line == b"":
                        break
                    system, attribute = line.decode("utf-8").split()
                    packages_per_system[system].append(attribute)
                return packages_per_system
        return None


def nix_shell(attrs: List[Attr]) -> None:
    cmd = ["nix-shell"]

    broken = []
    failed = []
    non_existant = []

    for a in attrs:
        if a.broken:
            broken.append(a.name)
        elif not a.exists:
            non_existant.append(a.name)
        elif not a.was_build():
            failed.append(a.name)
        else:
            cmd.append(f"-p")
            cmd.append(a.name)

    if len(broken) > 0:
        print(f"The {len(broken)} packages are marked as broken and were skipped:")
        print(" ".join(broken))

    if len(non_existant) > 0:
        print(
            f"The {len(non_existant)} packages were present in ofBorgs evaluation, but not found in our checkout:"
        )
        print(" ".join(non_existant))

    if len(failed) > 0:
        print(f"The {len(failed)} packages failed to build:")
        print(" ".join(failed))

    if len(cmd) == 1:
        print("No packages were successfully build, skip nix-shell")
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

    results = []
    for name, props in json.loads(subprocess.check_output(cmd)).items():
        attr = Attr(name, props["exists"], props["broken"], props["path"])
        results.append(attr)
    return results


def build(attr_names: Set[str], args: str) -> List[Attr]:
    if not attr_names:
        print("Nothing changed")
        return []

    result_dir = tempfile.mkdtemp(prefix="nox-review-")
    attrs = eval_attrs(result_dir, attr_names)
    non_broken = []
    for attr in attrs:
        if not attr.broken:
            non_broken.append(attr.name)

    if len(non_broken) == 0:
        return attrs

    print("Building in {}".format(result_dir))
    command = [
        "nix-shell",
        "--no-out-link",
        "--keep-going",
        "--max-jobs",
        str(multiprocessing.cpu_count()),
        # only matters for single-user nix and trusted users
        "--option",
        "build-use-sandbox",
        "true",
        "--run",
        "true",
    ] + shlex.split(args)

    command.append("-p")
    for a in non_broken:
        command.append(a)
    try:
        sh(command, cwd=result_dir)
    except subprocess.CalledProcessError:
        pass
    return attrs


PackageSet = Set[Tuple[str, str]]


def list_packages(path: str, check_meta: bool = False) -> PackageSet:
    cmd = ["nix-env", "-f", path, "-qaP", "--xml", "--out-path", "--show-trace"]
    if check_meta:
        cmd.append("--meta")
    output = subprocess.check_output(cmd)
    context = ET.iterparse(io.StringIO(output.decode("utf-8")), events=("start",))
    packages = set()
    for (event, elem) in context:
        if elem.tag == "item":
            attrib = elem.attrib["attrPath"]
        elif elem.tag == "output":
            assert attrib is not None
            path = elem.attrib["path"]
            packages.add((attrib, path))
    return packages


def fetch_refs(*refs: str) -> List[str]:
    cmd = ["git", "fetch", "--force", "https://github.com/NixOS/nixpkgs"]
    for i, ref in enumerate(refs):
        cmd.append(f"{ref}:refs/nix-review/{i}")
    sh(cmd)
    shas = []
    for i, ref in enumerate(refs):
        o = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"refs/nix-review/{i}"]
        )
        shas.append(o.strip().decode("utf-8"))
    return shas


def differences(old: PackageSet, new: PackageSet) -> Set[str]:
    raw = new - old
    return {l[0] for l in raw}
