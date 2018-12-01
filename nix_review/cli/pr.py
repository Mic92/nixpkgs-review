import argparse
import re
import sys
import subprocess
from typing import List
from contextlib import ExitStack

from ..review import CheckoutOption, Review
from ..utils import info, warn
from ..builddir import Builddir


def parse_pr_numbers(number_args: List[str]) -> List[int]:
    prs: List[int] = []
    for arg in number_args:
        m = re.match(r"(\d+)-(\d+)", arg)
        if m:
            prs.extend(range(int(m.group(1)), int(m.group(2))))
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

    contexts = []

    with ExitStack() as stack:
        for pr in prs:
            builddir = stack.enter_context(Builddir(f"pr-{pr}"))
            try:
                review = Review(
                    builddir=builddir,
                    build_args=args.build_args,
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
            info(f"https://github.com/NixOS/nixpkgs/pull/{pr}")
            review.start_review(attrs)

        if len(contexts) != len(prs):
            sys.exit(1)
