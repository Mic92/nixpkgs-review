# draft

import argparse
import re
import subprocess
import sys
from contextlib import ExitStack
from typing import List
from urllib.parse import urlparse, unquote

from ..builddir import Builddir
from ..buildenv import Buildenv
from ..review import CheckoutOption, Review
from ..utils import warn
from .utils import ensure_github_token

# TODO maybe use https://github.com/nephila/giturlparse

# branch vs pr
# pr's are "special branches" on github
# branches are refs under refs/heads/
# pr's are refs under refs/pull/$number/head
# example: https://github.com/milahu/random/pull/4
# $ git ls-remote https://github.com/milahu/random | grep bdb17792 
# bdb177925a580798ba152774be1f66e88472912e        refs/heads/milahu-patch-1
# bdb177925a580798ba152774be1f66e88472912e        refs/pull/4/head
# $ git ls-remote https://github.com/milahu/random | grep refs/heads/
# ec031ad1f3e405893ead8954dfab16aecd07f809        refs/heads/master
# bdb177925a580798ba152774be1f66e88472912e        refs/heads/milahu-patch-1
# ec031ad1f3e405893ead8954dfab16aecd07f809        refs/heads/a/b/c/d/test
# ec031ad1f3e405893ead8954dfab16aecd07f809        refs/heads/github.com/a/b/c/d

# TODO handle special chars in branch names?
# valid branch names:
# a-b
# a+b
# a&b
# a%b
# https://stackoverflow.com/questions/3651860/which-characters-are-illegal-within-a-branch-name
# https://stackoverflow.com/questions/56612400/not-a-valid-git-branch-name

# parser was manually tested with
# ./bin/nix-review branch "https://github.com/NixOS/nixpkgs/compare/master...a/b-c%2Bd%26e%25f(g)hijk%3Dl.m%5D__%40n%23op%3Cq%3Er%C2%A7t%22u'v%60w%C2%B4x%3By_z" staging milahu:patch-1 "https://github.com/delroth/nixpkgs/commit/a9f5b7dbfe16c81a026946f2c9931479be31171d"  "https://github.com/NixOS/nixpkgs/compare/master...milahu:patch-123" "https://github.com/NixOS/nixpkgs/compare/master..milahu:patch-123" 


class Branch:

    remote = "https://github.com/NixOS/nixpkgs"
    branch = None
    commit = None

    def __repr__(self):
        return f"Branch:\n  remote: {self.remote}\n  branch: {self.branch}\n  commit: {self.commit}"

    def __init__(self, raw_input):

        if not ":" in raw_input:
            # compare a nixpkgs branch to the nixpkgs master branch
            self.branch = raw_input
            # input is not a url, so it's not urlencoded
            #self.branch = unquote(raw_input)
            return

        url = urlparse(raw_input)

        if not url.scheme in {"https", "git", "git+ssh"}: # TODO more?
            # format is user:branch
            # example: alice:a/b-c+d&e%f
            parts = raw_input.split(":")
            if len(parts) != 2:
                raise Exception(f"branch expected format user:branch, got {repr(raw_input)}")
            [owner, branch] = parts
            self.remote = f"https://github.com/{owner}/nixpkgs"
            self.branch = branch
            # input is not a url, so it's not urlencoded
            # copy branch from github webinterface https://github.com/milahu/random/pull/5
            # -> a/b-c+d&e%f(g)hijk=l.m]__@n#op<q>r§t"u'v`w´x;y_z
            #self.branch = unquote(branch)
            return

        if url.netloc != "github.com":
            # TODO implement: gitlab, gitea, ... maybe use https://github.com/nephila/giturlparse
            raise Exception(f"not implemented. branch must be a github url, got {repr(raw_input)}")

        # path='/alice/nixpkgs/tree/a/b-c+d&e%f'
        # illegal chars in branch name: :^,~[\?!
        # legal branch name: a/b-c+d&e%f(g)hijk=l.m]__@n#op<q>r§t"u'v`w´x;y_z
        # https://github.com/milahu/random/tree/a/b-c%2Bd%26e%25f(g)hijk%3Dl.m%5D__%40n%23op%3Cq%3Er%C2%A7t%22u'v%60w%C2%B4x%3By_z
        # path="/milahu/random/tree/a/b-c%2Bd%26e%25f(g)hijk%3Dl.m%5D__%40n%23op%3Cq%3Er%C2%A7t%22u'v%60w%C2%B4x%3By_z"
        # unquote(path) = /milahu/random/tree/a/b-c+d&e%f(g)hijk=l.m]__@n#op<q>r§t"u'v`w´x;y_z

        dirs = url.path.split("/")

        if dirs[2] != "nixpkgs":
            raise Exception(f"branch repo name must be nixpkgs, got {repr(raw_input)}")

        if dirs[3] == "tree":
            # https://github.com/delroth/nixpkgs/tree/gstreamermm-build-fix
            # https://github.com/milahu/random/tree/a/b/c/d/test
            # https://github.com/milahu/random/tree/github.com/a/b/c/d
            # $ git branch a:b:c:d
            # fatal: 'a:b:c:d' is not a valid branch name.
            self.branch = unquote("/".join(dirs[4:]))
            return

        if dirs[3] == "commit":
            # https://github.com/delroth/nixpkgs/commit/a9f5b7dbfe16c81a026946f2c9931479be31171d
            self.commit = dirs[4]
            owner = dirs[1]
            self.remote = f"https://github.com/{owner}/nixpkgs"
            return

        if dirs[3] == "compare":
            # ex: https://github.com/NixOS/nixpkgs/compare/master...delroth:gstreamermm-build-fix
            if not raw_input.startswith("https://github.com/NixOS/nixpkgs/compare/master.."):
                raise Exception(f"expected github compare link versus nixpkgs master, got {repr(raw_input)}")

            branch = unquote("/".join(dirs[4:]))
            if branch.startswith("master..."):
                branch = branch[9:]
            elif branch.startswith("master.."):
                branch = branch[8:]

            parts = branch.split(":")
            if len(parts) == 2:
                [owner, branch] = parts
                self.remote = f"https://github.com/{owner}/nixpkgs"
                self.branch = branch
                return
            if len(parts) == 1:
                # base is NixOS/nixpkgs
                self.branch = branch
                return
            raise Exception(f"expected github compare link with user:branch or branch, got {repr(raw_input)}")

        raise Exception(f"failed to parse branch from {repr(raw_input)}")

        #if branch == None and commit == None:
        #    raise Exception("branch requires either branch-name or commit-hash")


def parse_branches(branch_args: List[str]) -> List[int]:
    # example inputs:
    # https://github.com/delroth/nixpkgs/tree/gstreamermm-build-fix
    # https://github.com/delroth/nixpkgs/commit/a9f5b7dbfe16c81a026946f2c9931479be31171d
    # https://github.com/NixOS/nixpkgs/compare/master...delroth:gstreamermm-build-fix
    # delroth:gstreamermm-build-fix
    branches: List[int] = []
    for arg in branch_args:
        branch = Branch(arg)
        print("arg", arg)
        print("branch", branch)
        branches.append(branch)
    return branches


# based on pr_command
def branch_command(args: argparse.Namespace) -> str:
    branches = parse_branches(args.branches)

    import sys; sys.exit() # debug

    use_ofborg_eval = args.eval == "ofborg"
    checkout_option = (
        CheckoutOption.MERGE if args.checkout == "merge" else CheckoutOption.COMMIT
    )

    #if args.post_result:
    #    ensure_github_token(args.token)

    contexts = []

    with Buildenv(args), ExitStack() as stack:
        for branch in branches:
            builddir = stack.enter_context(Builddir(f"branch-{branch}")) # TODO slugify branch to filepath
            try:
                review = Review(
                    builddir=builddir,
                    build_args=args.build_args,
                    no_shell=args.no_shell,
                    run=args.run,
                    remote=args.remote,
                    api_token=args.token,
                    use_ofborg_eval=use_ofborg_eval,
                    only_packages=set(args.package),
                    package_regexes=args.package_regex,
                    skip_packages=set(args.skip_package),
                    skip_packages_regex=args.skip_package_regex,
                    system=args.system,
                    checkout=checkout_option,
                    allow_aliases=args.allow_aliases,
                    sandbox=args.sandbox,
                )
                # TODO implement review.build_branch
                contexts.append((branch, builddir.path, review.build_branch(branch)))
            except subprocess.CalledProcessError:
                warn(f"failed to build branch: {branch}")

        for branch, path, attrs in contexts:
            post_result = False # only for pr's
            review.start_review(attrs, path, branch, post_result)

        if len(contexts) != len(branches):
            sys.exit(1)
    return str(builddir.path)
