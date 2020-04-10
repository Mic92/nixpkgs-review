import json
import urllib.parse
import urllib.request

from collections import defaultdict
from typing import Any, DefaultDict, Dict, Optional, Set


class GithubClient:
    def __init__(self, api_token: Optional[str]) -> None:
        self.api_token = api_token

    def _request(
        self, path: str, method: str, data: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = urllib.parse.urljoin("https://api.github.com/", path)
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"token {self.api_token}"

        body = None
        if data:
            body = json.dumps(data).encode("ascii")

        req = urllib.request.Request(url, headers=headers, method=method, data=body)
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())

    def get(self, path: str) -> Any:
        return self._request(path, "GET")

    def post(self, path: str, data: Dict[str, str]) -> Any:
        return self._request(path, "POST", data)

    def put(self, path: str) -> Any:
        return self._request(path, "PUT")

    def issue_comment(self, pr: int, msg: str) -> Any:
        "Post a comment on a PR with nixpkgs-review report"
        print(f"Posting result comment on PR {pr}")
        return self.post(
            f"/repos/NixOS/nixpkgs/issues/{pr}/comments", data=dict(body=msg)
        )

    def pr_approve(self, pr: int) -> Any:
        "Approve a PR"
        print(f"Approving PR {pr}")
        return self.post(
            f"/repos/NixOS/nixpkgs/pulls/{pr}/reviews", data=dict(event="APPROVE"),
        )

    def pr_merge(self, pr: int) -> Any:
        "Merge a PR. Requires maintainer access to NixPkgs"
        print(f"Merging PR {pr}")
        return self.put(f"/repos/NixOS/nixpkgs/pulls/{pr}/merge")

    def pull_request(self, number: int) -> Any:
        return self.get(f"repos/NixOS/nixpkgs/pulls/{number}")

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
