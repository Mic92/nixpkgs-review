import json
import urllib.parse
import urllib.request

from collections import defaultdict
from typing import Any, DefaultDict, Dict, Optional, Set

# The PyGithub module does have stub files, but they're not installed via its
# setup.py, so mypy complains about missing types.
from github import Github  # type: ignore


class GithubClient:
    def __init__(self, api_token: Optional[str]) -> None:
        self.api_token = api_token
        if api_token:
            self.github = Github(api_token)
            self.nixpkgs = self.github.get_repo("NixOS/nixpkgs")

    def get(self, path: str) -> Any:
        url = urllib.parse.urljoin("https://api.github.com/", path)
        req = urllib.request.Request(url)
        if self.api_token:
            req.add_header("Authorization", f"token {self.api_token}")
        return json.loads(urllib.request.urlopen(req).read())

    def pr_comment(self, pr: int, msg: str) -> None:
        "Post a comment on a PR with nixpkgs-review report"
        gh_pr = self.nixpkgs.get_pull(pr)
        gh_pr.create_issue_comment(msg)

    def get_borg_eval_gist(self, pr: Dict[str, Any]) -> Optional[Dict[str, Set[str]]]:
        packages_per_system: DefaultDict[str, Set[str]] = defaultdict(set)
        statuses = self.get(pr["statuses_url"])
        for status in statuses:
            url = status.get("target_url", "")
            if (
                status["description"] == "^.^!"
                and status["creator"]["login"] == "ofborg[bot]"
                and url != ""
            ):
                url = urllib.parse.urlparse(url)
                raw_gist_url = (
                    f"https://gist.githubusercontent.com/GrahamcOfBorg{url.path}/raw/"
                )
                for line in urllib.request.urlopen(raw_gist_url):
                    if line == b"":
                        break
                    system, attribute = line.decode("utf-8").split()
                    packages_per_system[system].add(attribute)
                return packages_per_system
        return None
