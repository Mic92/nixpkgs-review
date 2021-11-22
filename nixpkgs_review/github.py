import sys
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any, DefaultDict, Dict, Optional, Set

import backoff


class GithubClient:
    def __init__(self, api_token: Optional[str], remote: str) -> None:
        self.api_token = api_token

        match = re.match(r"https?:\/\/github.com/(\w+)/(\w+)", remote)
        if match is not None:
            # usually remote = "https://github.com/NixOS/nixpkgs"
            # => _owner = "NixOS", _repo = "nixpkgs"
            self._owner, self._repo = match.groups()
        else:
            raise ValueError(f"Unparsable remote: {remote}")

    def _pr_url(self, pr: int) -> str:
        return f"https://github.com/{self._owner}/{self._repo}/pull/{pr}"

    @backoff.on_exception(backoff.expo, urllib.error.HTTPError, max_time=60)
    def _request(
        self, path: str, method: str, data: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = urllib.parse.urljoin("https://api.github.com/", path)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.api_token:
            headers["Authorization"] = f"token {self.api_token}"

        body = None
        if data:
            body = json.dumps(data).encode("ascii")

        req = urllib.request.Request(url, headers=headers, method=method, data=body)
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            print(f"Url: {url}", file=sys.stderr)
            print(f"Code: {e.code}", file=sys.stderr)
            print(f"Reason: {e.reason}", file=sys.stderr)
            print(f"Headers: {e.headers}", file=sys.stderr)
            print(f"Request data: {data}", file=sys.stderr)
            print(f"Response: {e.read().decode('utf-8')}", file=sys.stderr)
            raise

        return json.loads(resp.read())

    def get(self, path: str) -> Any:
        return self._request(path, "GET")

    def post(self, path: str, data: Dict[str, Any]) -> Any:
        return self._request(path, "POST", data)

    def put(self, path: str) -> Any:
        return self._request(path, "PUT")

    def patch(self, path: str, data: Dict[str, Any]) -> Any:
        return self._request(path, "PATCH", data)

    def comment_issue(self, pr: int, msg: str) -> Any:
        "Post a comment on a PR with nixpkgs-review report"
        print(f"Posting result comment on {self._pr_url(pr)}")
        return self.post(
            f"/repos/{self._owner}/{self._repo}/issues/{pr}/comments",
            data=dict(body=msg),
        )

    def comment_or_update_prior_comment_issue(self, pr: int, msg: str) -> Any:
        NEEDLE = "[1](https://github.com/Mic92/nixpkgs-review)"
        user = self.get("/user")

        my_prev_comment: Optional[Dict[str, Any]] = None
        for comment in self.get(
            f"/repos/{self._owner}/{self._repo}/issues/{pr}/comments"
        )[::-1]:
            if comment["user"]["login"] == user["login"] and NEEDLE in comment["body"]:
                my_prev_comment = comment

        if my_prev_comment is not None:
            id = my_prev_comment["id"]
            new_msg = my_prev_comment["body"] + "\n\n--------\n\n" + msg
            return self.patch(
                f"/repos/{self._owner}/{self._repo}/issues/comments/{id}",
                data=dict(body=new_msg),
            )
        return self.comment_issue(pr, msg)

    def approve_pr(self, pr: int) -> Any:
        "Approve a PR"
        print(f"Approving {self._pr_url(pr)}")
        return self.post(
            f"/repos/{self._owner}/{self._repo}/pulls/{pr}/reviews",
            data=dict(event="APPROVE"),
        )

    def merge_pr(self, pr: int) -> Any:
        "Merge a PR. Requires maintainer access to nixpkgs"
        print(f"Merging {self._pr_url(pr)}")
        return self.put(f"/repos/{self._owner}/{self._repo}/pulls/{pr}/merge")

    def graphql(self, query: str) -> Dict[str, Any]:
        resp = self.post("/graphql", data=dict(query=query))
        if "errors" in resp:
            raise RuntimeError(f"Expected data from graphql api, got: {resp}")
        data: Dict[str, Any] = resp["data"]
        return data

    def pull_request(self, number: int) -> Any:
        "Get a pull request"
        return self.get(f"repos/{self._owner}/{self._repo}/pulls/{number}")

    def get_borg_eval_gist(self, pr: Dict[str, Any]) -> Optional[Dict[str, Set[str]]]:
        packages_per_system: DefaultDict[str, Set[str]] = defaultdict(set)
        statuses = self.get(pr["statuses_url"])
        raw_gist_url = os.environ.get("NIXPKGS_REVIEW_OFBORG_GIST_URL")
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
                break

        if raw_gist_url is not None:
            for line in urllib.request.urlopen(raw_gist_url):
                if line == b"":
                    break
                system, attribute = line.decode("utf-8").split()
                packages_per_system[system].add(attribute)
            return packages_per_system
        return None

    def upload_gist(self, name: str, content: str, description: str) -> Dict[str, Any]:
        data = dict(
            files={name: {"content": content}}, public=True, description=description
        )
        resp: Dict[str, Any] = self.post("/gists", data=data)
        return resp
