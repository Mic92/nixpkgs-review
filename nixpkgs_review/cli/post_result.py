import argparse
import os
import sys
from pathlib import Path

from ..github import GithubClient
from ..utils import warn
from .utils import ensure_github_token


def post_result_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    pr_env = os.environ.get("PR", None)
    if pr_env is None:
        warn("PR environment variable not set. Are you in a nixpkgs-review nix-shell?")
        sys.exit(1)
    pr = int(pr_env)

    report = Path(os.environ["NIXPKGS_REVIEW_ROOT"]) / "report.md"
    if not report.exists():
        warn(f"Report not found in {report}. Are you in a nixpkgs-review nix-shell?")
        sys.exit(1)

    with open(report) as f:
        report_text = f.read()
    github_client.comment_issue(pr, report_text)
