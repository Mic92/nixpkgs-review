import argparse
import re
import subprocess
import sys

from contextlib import ExitStack
from typing import List

from ..builddir import Builddir
from ..review import CheckoutOption, Review
from ..utils import warn


def parse_pr_numbers(number_args: List[str]) -> List[int]:
    prs: List[int] = []
    for arg in number_args:
        m = re.match(r"(\d+)-(\d+)", arg)
        if m:
            prs.extend(range(int(m.group(1)), int(m.group(2))))
        else:
            m = re.match(r"https://github.com/NixOS/nixpkgs/pull/(\d+)/?.*", arg)
            if m:
                prs.append(int(m.group(1)))
            else:
                try:
                    prs.append(int(arg))
                except ValueError:
                    warn(f"expected number, got {m}")
                    sys.exit(1)
    return prs


def pr_command(args: argparse.Namespace) -> None:
    prs = parse_pr_numbers(args.number)
    use_ofborg_eval = args.eval == "ofborg"
    checkout_option = (
        CheckoutOption.MERGE if args.checkout == "merge" else CheckoutOption.COMMIT
    )

    if args.post_result and not args.token:
        warn(
            "Posting PR comments requires a Github API token; see https://github.com/Mic92/nixpkgs-review#github-api-token"
        )
        sys.exit(1)

    contexts = []

    with ExitStack() as stack:
        for pr in prs:
            builddir = stack.enter_context(Builddir(f"pr-{pr}"))
            try:
                review = Review(
                    builddir=builddir,
                    build_args=args.build_args,
                    no_shell=args.no_shell,
                    api_token=args.token,
                    use_ofborg_eval=use_ofborg_eval,
                    only_packages=set(args.package),
                    package_regexes=args.package_regex,
                    checkout=checkout_option,
                )
                contexts.append((pr, review.build_pr(pr)))
            except subprocess.CalledProcessError:
                warn(f"https://github.com/NixOS/nixpkgs/pull/{pr} failed to build")

        for pr, attrs in contexts:
            review.start_review(attrs, pr, args.post_result)

        if len(contexts) != len(prs):
            sys.exit(1)
