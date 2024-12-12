import json
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from typing import Any

import requests

from .utils import System


def pr_url(pr: int) -> str:
    return f"https://github.com/NixOS/nixpkgs/pull/{pr}"


class GithubClient:
    def __init__(self, api_token: str | None) -> None:
        self.api_token = api_token
        self.headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        }
        if self.api_token:
            self.headers["Authorization"] = f"token {self.api_token}"

    def _request(
        self,
        path: str,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        url = urllib.parse.urljoin("https://api.github.com/", path)

        body = None
        if data:
            body = json.dumps(data).encode("ascii")

        req = urllib.request.Request(
            url,
            headers=self.headers,
            method=method,
            data=body,
        )
        with urllib.request.urlopen(req) as resp:
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
            f"/repos/NixOS/nixpkgs/issues/{pr}/comments", data={"body": msg}
        )

    def approve_pr(self, pr: int) -> Any:
        "Approve a PR"
        print(f"Approving {pr_url(pr)}")
        return self.post(
            f"/repos/NixOS/nixpkgs/pulls/{pr}/reviews",
            data={"event": "APPROVE"},
        )

    def merge_pr(self, pr: int) -> Any:
        "Merge a PR. Requires maintainer access to NixPkgs"
        print(f"Merging {pr_url(pr)}")
        return self.put(f"/repos/NixOS/nixpkgs/pulls/{pr}/merge")

    def graphql(self, query: str) -> dict[str, Any]:
        resp = self.post("/graphql", data={"query": query})
        if "errors" in resp:
            raise RuntimeError(f"Expected data from graphql api, got: {resp}")
        data: dict[str, Any] = resp["data"]
        return data

    def pull_request(self, number: int) -> Any:
        "Get a pull request"
        return self.get(f"repos/NixOS/nixpkgs/pulls/{number}")

    def get_json_from_artifact(self, workflow_id: int, json_filename: str) -> Any:
        """
        - Download a workflow artifact
        - Extract the archive
        - Open, deserialize and return a specific `json_filename` JSON file
        """
        download_url: str = f"https://api.github.com/repos/NixOS/nixpkgs/actions/artifacts/{workflow_id}/zip"

        with requests.get(
            url=download_url,
            headers=self.headers,
            stream=True,
        ) as resp:
            with tempfile.TemporaryDirectory() as temp_dir:
                # download zip file to disk
                with tempfile.NamedTemporaryFile(delete_on_close=False) as f:
                    f.write(resp.content)
                    f.close()

                    # Extract zip archive to temporary directory
                    with zipfile.ZipFile(f.name, "r") as zip_ref:
                        zip_ref.extractall(temp_dir)

                with open(os.path.join(temp_dir, json_filename)) as f:
                    return json.loads(f.read())

        return None

    def get_github_action_eval_result(
        self, pr: dict[str, Any]
    ) -> dict[System, set[str]] | None:
        commit_sha: str = pr["head"]["sha"]

        workflow_runs_resp: Any = self.get(
            f"repos/NixOS/nixpkgs/actions/runs?head_sha={commit_sha}"
        )
        if (
            not isinstance(workflow_runs_resp, dict)
            or "workflow_runs" not in workflow_runs_resp
        ):
            return None

        workflow_runs: list[Any] = workflow_runs_resp["workflow_runs"]

        if not workflow_runs:
            return None

        for workflow_run in workflow_runs:
            if workflow_run["name"] == "Eval":
                artifacts: list[Any] = self.get(
                    workflow_run["artifacts_url"],
                )["artifacts"]

                for artifact in artifacts:
                    if artifact["name"] == "comparison":
                        changed_paths: Any = self.get_json_from_artifact(
                            workflow_id=artifact["id"],
                            json_filename="changed-paths.json",
                        )
                        if changed_paths is not None:
                            if "rebuildsByPlatform" in changed_paths:
                                return changed_paths["rebuildsByPlatform"]  # type: ignore
        return None

    def get_borg_eval_gist(self, pr: dict[str, Any]) -> dict[System, set[str]] | None:
        packages_per_system: defaultdict[System, set[str]] = defaultdict(set)
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

                with urllib.request.urlopen(raw_gist_url) as resp:
                    for line in resp:
                        if line == b"":
                            break
                        system, attribute = line.decode("utf-8").split()
                        packages_per_system[system].add(attribute)

                return packages_per_system
        return None
