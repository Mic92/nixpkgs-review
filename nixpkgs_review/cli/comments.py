import argparse

from ..github import GithubClient
from .utils import ensure_github_token, get_current_pr


def show_comments(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    github_client.comments(get_current_pr())
