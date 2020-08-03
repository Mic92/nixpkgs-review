import argparse

from ..github import GithubClient
from .utils import ensure_github_token, get_current_pr


def merge_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    github_client.merge_pr(get_current_pr(), dict(method=args.method))
