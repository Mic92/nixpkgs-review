import json
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, override

from .utils import System


def pr_url(pr: int) -> str:
    return f"https://github.com/NixOS/nixpkgs/pull/{pr}"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


no_redirect_opener = urllib.request.build_opener(NoRedirectHandler)


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

        req = urllib.request.Request(  # noqa: S310
            url,
            headers=self.headers,
            method=method,
            data=body,
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
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
            msg = f"Expected data from graphql api, got: {resp}"
            raise RuntimeError(msg)
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

        req = urllib.request.Request(download_url, headers=self.headers)  # noqa: S310
        try:
            with no_redirect_opener.open(req) as resp:
                pass
        except urllib.error.HTTPError as e:
            if e.code == 302:
                new_url = e.headers["Location"]
                # Handle the new URL as needed
            else:
                raise
        else:
            msg = f"Expected 302, got {resp.status}"
            raise RuntimeError(msg)

        if not new_url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)

        req = urllib.request.Request(new_url)  # noqa: S310
        with (
            urllib.request.urlopen(req) as new_resp,  # noqa: S310
            tempfile.TemporaryDirectory() as _temp_dir,
        ):
            temp_dir = Path(_temp_dir)
            # download zip file to disk
            artifact_zip = temp_dir / "artifact.zip"
            with artifact_zip.open("wb") as f:
                shutil.copyfileobj(new_resp, f)

            # Extract zip archive to temporary directory
            with zipfile.ZipFile(artifact_zip, "r") as zip_ref:
                zip_ref.extract(json_filename, temp_dir)

            with (temp_dir / json_filename).open() as json_file:
                return json.load(json_file)

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
            if workflow_run["name"] != "Eval":
                continue
            artifacts: list[Any] = self.get(
                workflow_run["artifacts_url"],
            )["artifacts"]

            for artifact in artifacts:
                if artifact["name"] != "comparison":
                    continue
                changed_paths: Any = self.get_json_from_artifact(
                    workflow_id=artifact["id"],
                    json_filename="changed-paths.json",
                )
                if changed_paths is None:
                    continue
                if (path := changed_paths.get("rebuildsByPlatform")) is not None:
                    assert isinstance(path, dict)
                    return {
                        # Convert package lists to package sets
                        system: set(packages_list)
                        for system, packages_list in path.items()
                    }

        return None
