from __future__ import annotations

import re
import sys
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any

from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.builddir import Builddir
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.errors import NixpkgsReviewError
from nixpkgs_review.review import (
    CheckoutOption,
    Review,
    ReviewAction,
    ReviewConfig,
    ShellOptions,
    build_config_from_args,
    package_filter_from_args,
)
from nixpkgs_review.utils import System, die, warn

from .utils import ensure_github_token

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from nixpkgs_review.nix import Attr


def parse_pr_numbers(number_args: list[str]) -> list[int]:
    prs: list[int] = []
    for arg in number_args:
        if m := re.match(r"(\d+)-(\d+)", arg):
            prs.extend(range(int(m.group(1)), int(m.group(2))))
        elif m := re.match(r"https://github.com/NixOS/nixpkgs/pull/(\d+)/?.*", arg):
            prs.append(int(m.group(1)))
        else:
            try:
                prs.append(int(arg))
            except ValueError:
                die(f"expected number or URL, got {arg!r}")
    return prs


def _validate_pr_json(args: argparse.Namespace, prs: list[int]) -> dict[int, Any]:
    pr_objects: dict[int, Any] = {}
    for obj in args.pr_json:
        if (
            not isinstance(obj, dict)
            or "number" not in obj
            or not isinstance((number := obj["number"]), int)
        ):
            die(f"Invalid Pull Request JSON object provided: {obj}")
        pr_objects[number] = obj
    if args.pr_json and (missing := [pr for pr in prs if pr not in pr_objects]):
        die(
            f"API lookups for PRs are disabled due to the use of the --pr-json flag, but no JSON objects have been specified for the following PRs: {', '.join(map(str, missing))}"
        )
    return pr_objects


def _handle_deprecated_args(args: argparse.Namespace) -> None:
    if args.eval == "ofborg":
        warn("Warning: `--eval=ofborg` is deprecated. Use `--eval=github` instead.")
        args.eval = "github"
    if args.system:
        warn("Warning: The `--system` is deprecated. Use `--systems` instead.")
        args.systems = args.system


def pr_command(args: argparse.Namespace) -> str:
    prs: list[int] = parse_pr_numbers(args.number)
    _handle_deprecated_args(args)

    checkout_option = CheckoutOption[args.checkout.upper()]

    pr_objects = _validate_pr_json(args, prs)

    if args.merge_pr and not args.approve_pr:
        warn("--merge-pr must be used with --approve-pr")
        sys.exit(1)

    if args.post_result or args.approve_pr or args.merge_pr:
        ensure_github_token(args.token)

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
        Buildenv(
            allow_aliases=allow.aliases, extra_nixpkgs_config=args.extra_nixpkgs_config
        ) as nixpkgs_config,
        ExitStack() as stack,
    ):
        review = None
        for pr in prs:
            builddir = stack.enter_context(Builddir(f"pr-{pr}"))
            try:
                review = Review(
                    builddir=builddir,
                    package_filter=package_filter_from_args(args),
                    build_config=build_config_from_args(
                        args, allow, builddir.nix_path, nixpkgs_config
                    ),
                    review_config=ReviewConfig(
                        remote=args.remote,
                        extra_nixpkgs_config=args.extra_nixpkgs_config,
                        systems=args.systems.split(" "),
                        api_token=args.token,
                        eval_type=args.eval,
                        checkout=checkout_option,
                        pr_object=pr_objects.get(pr),
                        show_header=not args.no_headers,
                        show_logs=not args.no_logs,
                        show_pr_info=not args.no_pr_info,
                    ),
                    shell_options=ShellOptions(
                        no_shell=args.no_shell,
                        run=args.run,
                        sandbox=args.sandbox,
                        build_args=args.build_args,
                        build_graph=args.build_graph,
                    ),
                )
                contexts.append(
                    (pr, builddir.path, review.build_pr(pr), review.head_commit)
                )
            except NixpkgsReviewError as e:
                warn(f"https://github.com/NixOS/nixpkgs/pull/{pr} failed to build: {e}")
        assert review is not None

        action = ReviewAction(
            post_result=args.post_result,
            print_result=args.print_result,
            approve_pr=args.approve_pr,
            merge_pr=args.merge_pr,
        )
        all_succeeded = all(
            review.start_review(commit, attrs, path, pr, action=action)
            for pr, path, attrs, commit in contexts
        )

        if args.no_shell:
            sys.exit(0 if all_succeeded or args.no_exit_status else 1)

        if len(contexts) != len(prs):
            sys.exit(1)
    assert builddir is not None
    return str(builddir.path)
