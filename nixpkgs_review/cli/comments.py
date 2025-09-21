from __future__ import annotations

import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Required, TypedDict, cast

from nixpkgs_review.github import GithubClient

from .utils import ensure_github_token, get_current_pr

if TYPE_CHECKING:
    import argparse


# GraphQL Response TypedDicts
class GitHubGraphQLAuthor(TypedDict):
    login: Required[str]


class GitHubGraphQLComment(TypedDict):
    author: Required[GitHubGraphQLAuthor]
    body: Required[str]
    createdAt: Required[str]


class GitHubGraphQLReviewComment(TypedDict):
    id: Required[str]
    author: Required[GitHubGraphQLAuthor]
    body: Required[str]
    createdAt: Required[str]
    diffHunk: Required[str]
    replyTo: dict[str, str] | None


class GitHubGraphQLReviewCommentsNode(TypedDict):
    nodes: Required[list[GitHubGraphQLReviewComment]]


class GitHubGraphQLReview(TypedDict):
    author: Required[GitHubGraphQLAuthor]
    body: Required[str]
    createdAt: Required[str]
    comments: Required[GitHubGraphQLReviewCommentsNode]


class GitHubGraphQLReviewsNode(TypedDict):
    nodes: Required[list[GitHubGraphQLReview]]


class GitHubGraphQLCommentsNode(TypedDict):
    nodes: Required[list[GitHubGraphQLComment]]


class GitHubGraphQLPullRequest(GitHubGraphQLComment):
    reviews: Required[GitHubGraphQLReviewsNode]
    comments: Required[GitHubGraphQLCommentsNode]


class GitHubGraphQLRepository(TypedDict):
    pullRequest: Required[GitHubGraphQLPullRequest]


class GitHubGraphQLResponse(TypedDict):
    repository: Required[GitHubGraphQLRepository]


def comments_query(pr: int) -> str:
    return string.Template("""
{
    repository(owner: "NixOS", name: "nixpkgs") {
        pullRequest(number: $pr) {
            author { login }
            body
            createdAt
            comments(last: 50) {
               nodes {
                   author { login }
                   body
                   createdAt
               }
               totalCount
            }
            reviews(last: 50) {
                totalCount
                nodes {
                    author { login }
                    body
                    createdAt
                    comments(last: 30) {
                        nodes {
                            author { login }
                            body
                            createdAt
                            diffHunk
                            id
                            replyTo {
                              id
                            }
                        }
                    }
                }
            }
        }
    }
}
""").substitute(pr=pr)


@dataclass
class Comment:
    author: str
    body: str
    created_at: datetime

    @staticmethod
    def from_json(data: GitHubGraphQLComment) -> Comment:
        return Comment(
            author=data["author"]["login"],
            body=data["body"],
            created_at=parse_time(data["createdAt"]),
        )


@dataclass
class ReviewComment(Comment):
    diff_hunk: str
    id: str
    reply_to: str | None
    replies: list[ReviewComment] = field(default_factory=list)

    @staticmethod
    def from_review_comment_json(data: GitHubGraphQLReviewComment) -> ReviewComment:
        reply_to_id = reply_to.get("id") if (reply_to := data.get("replyTo")) else None

        return ReviewComment(
            author=data["author"]["login"],
            body=data["body"],
            id=data["id"],
            reply_to=reply_to_id,
            created_at=parse_time(data["createdAt"]),
            diff_hunk=data["diffHunk"],
        )


@dataclass
class Review:
    author: str
    body: str
    created_at: datetime
    comments: list[ReviewComment]

    @staticmethod
    def from_json(data: GitHubGraphQLReview, comments: list[ReviewComment]) -> Review:
        return Review(
            author=data["author"]["login"],
            body=data["body"],
            created_at=parse_time(data["createdAt"]),
            comments=comments,
        )


def parse_time(string: str) -> datetime:
    # Should we care about timezone here? %z
    return datetime.strptime(string, "%Y-%m-%dT%H:%M:%SZ")  # noqa: DTZ007


def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def get_comments(github_token: str, pr_num: int) -> list[Comment | Review]:
    github_client = GithubClient(github_token)
    query = comments_query(pr_num)
    data = github_client.graphql(query)

    response = cast("GitHubGraphQLResponse", data)
    pr = response["repository"]["pullRequest"]

    comments: list[Comment | Review] = [Comment.from_json(pr)]

    # Include PR issue comments (separate from review threads)
    comments.extend(Comment.from_json(c) for c in pr["comments"]["nodes"])

    reviews_nodes = pr["reviews"]["nodes"]

    # Note: reviews_nodes contains reviews, not review comments
    # We'll process them below when iterating through reviews

    review_comments_by_ids: dict[str, ReviewComment] = {}
    for review in reviews_nodes:
        review_comments_nodes = review["comments"]["nodes"]

        review_comments = []
        for comment in review_comments_nodes:
            c = ReviewComment.from_review_comment_json(comment)
            if c.reply_to:
                if (referred := review_comments_by_ids.get(c.reply_to)) is not None:
                    referred.replies.append(c)
                else:
                    review_comments.append(c)
            else:
                review_comments.append(c)
            review_comments_by_ids[c.id] = c
        comments.append(Review.from_json(review, review_comments))

    return sorted(comments, key=lambda x: x.created_at)


def colorize_diff(diff: str) -> str:
    lines = []
    for line in diff.split("\n"):
        if line.startswith("-"):
            color = "\x1b[31m"
        elif line.startswith("+"):
            color = "\x1b[32m"
        elif line.startswith("@"):
            color = "\x1b[34m"
        else:
            color = ""
        lines.append(f"{color}{line}\x1b[0m")
    return "\n".join(lines)


def show_comments(args: argparse.Namespace) -> None:
    comments = get_comments(ensure_github_token(args.token), get_current_pr())

    for comment in comments:
        if isinstance(comment, Review) and (comment.body or comment.comments):
            print(
                f"[{comment.created_at}] {bold(comment.author)} reviewed: {comment.body}\n"
            )
            for review_comment in comment.comments:
                print(colorize_diff(review_comment.diff_hunk))
                print(f"  {bold(review_comment.author)}: {review_comment.body}")
                for reply in review_comment.replies:
                    print(f"  {bold(reply.author)}: {reply.body}\n")
                if not review_comment.replies:
                    print("\n")
        elif isinstance(comment, Comment):
            print(
                f"[{comment.created_at}] {bold(comment.author)} said: {comment.body}\n"
            )
