import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..github import GithubClient
from .utils import ensure_github_token, get_current_pr


def comments_query(pr: int) -> str:
    return """
{
    repository(owner: "NixOS", name: "nixpkgs") {
        pullRequest(number: %d) {
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
""" % (pr)


@dataclass
class Comment:
    author: str
    body: str
    created_at: datetime

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Comment":
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
    replies: "list[ReviewComment]" = field(default_factory=list)

    @staticmethod
    def from_json(data: dict[str, Any]) -> "ReviewComment":
        reply_to = data.get("replyTo")
        reply_to_id = None
        if reply_to is not None:
            reply_to_id = reply_to.get("id")
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
    def from_json(data: dict[str, Any], comments: list[ReviewComment]) -> "Review":
        return Review(
            author=data["author"]["login"],
            body=data["body"],
            created_at=parse_time(data["createdAt"]),
            comments=comments,
        )


def parse_time(string: str) -> datetime:
    return datetime.strptime(string, "%Y-%m-%dT%H:%M:%SZ")


def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def get_comments(github_token: str, pr_num: int) -> list[Comment | Review]:
    github_client = GithubClient(github_token)
    query = comments_query(pr_num)
    data = github_client.graphql(query)
    pr = data["repository"]["pullRequest"]

    comments: list[Comment | Review] = [Comment.from_json(pr)]

    for comment in pr["comments"]["nodes"]:
        comments.append(Comment.from_json(comment))

    review_comments_by_ids: dict[str, ReviewComment] = {}
    for review in pr["reviews"]["nodes"]:
        review_comments = []
        for comment in review["comments"]["nodes"]:
            c = ReviewComment.from_json(comment)
            if c.reply_to:
                referred = review_comments_by_ids.get(c.reply_to, None)
                if referred is not None:
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
        color = ""
        if line.startswith("-"):
            color = "\x1b[31m"
        elif line.startswith("+"):
            color = "\x1b[32m"
        elif line.startswith("@"):
            color = "\x1b[34m"
        lines.append(f"{color}{line}\x1b[0m")
    return "\n".join(lines)


def show_comments(args: argparse.Namespace) -> None:
    comments = get_comments(ensure_github_token(args.token), get_current_pr())

    for comment in comments:
        if isinstance(comment, Review):
            if comment.body == "" and len(comment.comments) == 0:
                # skip replies
                continue
            print(
                f"[{comment.created_at}] {bold(comment.author)} reviewed: {comment.body}\n"
            )
            for review_comment in comment.comments:
                print(colorize_diff(review_comment.diff_hunk))
                print(f"  {bold(review_comment.author)}: {review_comment.body}")
                for reply in review_comment.replies:
                    print(f"  {bold(reply.author)}: {reply.body}\n")
                if len(review_comment.replies) == 0:
                    print("\n")
        else:
            print(
                f"[{comment.created_at}] {bold(comment.author)} said: {comment.body}\n"
            )
