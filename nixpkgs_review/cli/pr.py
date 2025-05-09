import argparse
import re
import sys
from contextlib import ExitStack
from typing import TYPE_CHECKING

from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.builddir import Builddir
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.errors import NixpkgsReviewError
from nixpkgs_review.review import CheckoutOption, Review
from nixpkgs_review.utils import System, warn

from .utils import ensure_github_token

if TYPE_CHECKING:
    from pathlib import Path

    from nixpkgs_review.nix import Attr


def parse_pr_numbers(number_args: list[str]) -> list[int]:
    prs: list[int] = []
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
                    warn(f"expected number or URL, got {m}")
                    sys.exit(1)
    return prs


def pr_command(args: argparse.Namespace) -> str:
    prs: list[int] = parse_pr_numbers(args.number)
    match args.eval:
        case "ofborg":
            warn("Warning: `--eval=ofborg` is deprecated. Use `--eval=github` instead.")
            args.eval = "github"
        case "auto":
            if args.token:
                args.eval = "github"
            else:
                if not args.package:
                    warn(
                        "No GitHub token provided via GITHUB_TOKEN variable. Falling back to local evaluation.\n"
                        "Tip: Install the `gh` command line tool and run `gh auth login` to authenticate."
                    )
                args.eval = "local"
        case "github":
            if not args.token:
                warn("No GitHub token provided")
                sys.exit(1)
    use_github_eval = args.eval == "github"
    checkout_option = (
        CheckoutOption.MERGE if args.checkout == "merge" else CheckoutOption.COMMIT
    )

    if args.post_result or args.approve_pr:
        ensure_github_token(args.token)
    if args.system:
        warn("Warning: The `--system` is deprecated. Use `--systems` instead.")
        args.systems = args.system

    contexts: list[
        tuple[
            # PR number
            int,
            # builddir path
            Path,
            # Attrs to build for each system
            dict[System, list[Attr]],
            # PR revision
            str | None,
        ]
    ] = []

    allow = AllowedFeatures(args.allow)

    builddir = None
    with (
        Buildenv(allow.aliases, args.extra_nixpkgs_config) as nixpkgs_config,
        ExitStack() as stack,
    ):
        review = None
        for pr in prs:
            builddir = stack.enter_context(Builddir(f"pr-{pr}"))
            try:
                review = Review(
                    builddir=builddir,
                    build_args=args.build_args,
                    no_shell=args.no_shell,
                    run=args.run,
                    remote=args.remote,
                    api_token=args.token,
                    use_github_eval=use_github_eval,
                    only_packages=set(args.package),
                    package_regexes=args.package_regex,
                    skip_packages=set(args.skip_package),
                    skip_packages_regex=args.skip_package_regex,
                    systems=args.systems.split(" "),
                    allow=allow,
                    checkout=checkout_option,
                    sandbox=args.sandbox,
                    build_graph=args.build_graph,
                    nixpkgs_config=nixpkgs_config,
                    extra_nixpkgs_config=args.extra_nixpkgs_config,
                    num_parallel_evals=args.num_parallel_evals,
                    show_header=not args.no_headers,
                    show_logs=not args.no_logs,
                )
                contexts.append(
                    (pr, builddir.path, review.build_pr(pr), review.head_commit)
                )
            except NixpkgsReviewError as e:
                warn(f"https://github.com/NixOS/nixpkgs/pull/{pr} failed to build: {e}")
        assert review is not None

        all_succeeded = all(
            review.start_review(
                commit,
                attrs,
                path,
                pr,
                args.post_result,
                args.print_result,
                args.approve_pr,
            )
            for pr, path, attrs, commit in contexts
        )

        if args.no_shell:
            sys.exit(0 if all_succeeded else 1)

        if len(contexts) != len(prs):
            sys.exit(1)
    assert builddir is not None
    return str(builddir.path)
