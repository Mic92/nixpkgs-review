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
from ..utils import warn, Branch
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

def parse_branches(branch_args: List[str]) -> List[int]:
    branches: List[int] = []
    for arg in branch_args:
        branch = Branch(arg)
        branches.append(branch)
    return branches


# based on pr_command
def branch_command(args: argparse.Namespace) -> str:

    branches = parse_branches(args.branches)

    use_ofborg_eval = False # ofborg is only available for pr

    checkout_option = (
        CheckoutOption.MERGE if args.checkout == "merge" else CheckoutOption.COMMIT
    )

    contexts = []

    with Buildenv(args), ExitStack() as stack:
        for branch in branches:
            builddir = stack.enter_context(Builddir(f"branch-{branch}"))
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
                contexts.append((branch, builddir.path, review.build_branch(branch)))
            except subprocess.CalledProcessError:
                warn(f"failed to build branch: {branch}")

        for branch, path, attrs in contexts:
            review.start_review(attrs, path, branch=branch)

        if len(contexts) != len(branches):
            sys.exit(1)
    return str(builddir.path)
