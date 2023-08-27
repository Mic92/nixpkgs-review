import json
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any


def pr_url(pr: int) -> str:
    return f"https://github.com/NixOS/nixpkgs/pull/{pr}"


class GithubClient:
    def __init__(self, api_token: str | None) -> None:
        self.api_token = api_token

    def _request(
        self, path: str, method: str, data: dict[str, Any] | None = None
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

    def post(self, path: str, data: dict[str, str]) -> Any:
        return self._request(path, "POST", data)

    def put(self, path: str) -> Any:
        return self._request(path, "PUT")

    def comment_issue(self, pr: int, msg: str) -> Any:
        "Post a comment on a PR with nixpkgs-review report"
        print(f"Posting result comment on {pr_url(pr)}")
        return self.post(
            f"/repos/NixOS/nixpkgs/issues/{pr}/comments", data=dict(body=msg)
        )

    def approve_pr(self, pr: int) -> Any:
        "Approve a PR"
        print(f"Approving {pr_url(pr)}")
        return self.post(
            f"/repos/NixOS/nixpkgs/pulls/{pr}/reviews",
            data=dict(event="APPROVE"),
        )

    def merge_pr(self, pr: int) -> Any:
        "Merge a PR. Requires maintainer access to NixPkgs"
        print(f"Merging {pr_url(pr)}")
        return self.put(f"/repos/NixOS/nixpkgs/pulls/{pr}/merge")

    def graphql(self, query: str) -> dict[str, Any]:
        resp = self.post("/graphql", data=dict(query=query))
        if "errors" in resp:
            raise RuntimeError(f"Expected data from graphql api, got: {resp}")
        data: dict[str, Any] = resp["data"]
        return data

    def pull_request(self, number: int) -> Any:
        "Get a pull request"
        return self.get(f"repos/NixOS/nixpkgs/pulls/{number}")

    def get_borg_eval_gist(self, pr: dict[str, Any]) -> dict[str, set[str]] | None:
        packages_per_system: defaultdict[str, set[str]] = defaultdict(set)
        statuses = self.get(pr["statuses_url"])
        for status in statuses:
            if (
                status["description"] == "^.^!"
                and status["state"] == "success"
                and status["context"] == "ofborg-eval"
                and status["creator"]["login"] == "ofborg[bot]"
            ):
                url = status.get("target_url", "")
                if url == "":
                    return packages_per_system

                url = urllib.parse.urlparse(url)
                gist_hash = url.path.split("/")[-1]
                raw_gist_url = (
                    f"https://gist.githubusercontent.com/GrahamcOfBorg/{gist_hash}/raw/"
                )
                for line in urllib.request.urlopen(raw_gist_url):
                    if line == b"":
                        break
                    system, attribute = line.decode("utf-8").split()
                    packages_per_system[system].add(attribute)
                return packages_per_system
        return None
