from __future__ import annotations

import json
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from textwrap import dedent
from typing import IO, TYPE_CHECKING, Any, Literal, Required, TypedDict, cast, override

from . import http_requests
from .errors import ArtifactExpiredError
from .utils import System, warn

if TYPE_CHECKING:
    from http.client import HTTPMessage

# Type alias for JSON-serializable types
type JSONType = dict[str, object] | list[object] | str | int | float | bool | None


# GitHub API TypedDicts
class GitHubUser(TypedDict):
    login: Required[str]


class GitHubRef(TypedDict):
    sha: Required[str]
    label: Required[str]


class GitHubPullRequest(TypedDict):
    title: Required[str]
    state: Required[str]
    body: str | None
    draft: bool
    diff_url: Required[str]
    merge_commit_sha: Required[str]
    user: Required[GitHubUser]
    head: Required[GitHubRef]
    base: Required[GitHubRef]
    node_id: Required[str]


class GitHubWorkflowRun(TypedDict):
    name: Required[str]
    artifacts_url: Required[str]


class GitHubWorkflowRunsResponse(TypedDict):
    workflow_runs: Required[list[GitHubWorkflowRun]]


class GitHubArtifact(TypedDict):
    id: Required[int]
    name: Required[str]


class GitHubArtifactsResponse(TypedDict):
    artifacts: Required[list[GitHubArtifact]]


class GitHubChangedPaths(TypedDict, total=False):
    rebuildsByPlatform: dict[str, list[str]]


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
        data: dict[str, object] | None = None,
    ) -> JSONType:
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
        with http_requests.urlopen(req) as resp:
            result: JSONType = json.loads(resp.read())
            return result

    def get(self, path: str) -> JSONType:
        return self._request(path, "GET")

    def post(self, path: str, data: dict[str, object]) -> JSONType:
        return self._request(path, "POST", data)

    def put(self, path: str) -> JSONType:
        return self._request(path, "PUT")

    def labels(self, pr: int) -> JSONType:
        "Fetch list of labels attached to a PR (or issue)"
        return self.get(f"/repos/NixOS/nixpkgs/issues/{pr}/labels")

    def comment_issue(self, pr: int, msg: str) -> JSONType:
        "Post a comment on a PR with nixpkgs-review report"
        print(f"Posting comment on {pr_url(pr)}")
        return self.post(
            f"/repos/NixOS/nixpkgs/issues/{pr}/comments", data={"body": msg}
        )

    def approve_pr(self, pr: int, comment: str = "") -> None:
        "Approve a PR with an optional comment"
        print(f"Approving {pr_url(pr)}")
        data: dict[str, object] = {"event": "APPROVE"}
        if comment:
            data["body"] = comment
        try:
            self.post(
                f"/repos/NixOS/nixpkgs/pulls/{pr}/reviews",
                data=data,
            )
        except urllib.error.HTTPError as e:
            if e.code == 422:
                warn(
                    "Sorry, unable to process request. You may have tried to approve your own PR, which is unsupported by GitHub"
                )
            else:
                raise

    def is_nixpkgs_committer(self) -> bool:
        resp = self.get("/repos/NixOS/nixpkgs")
        if not isinstance(resp, dict):
            msg = f"Expected response to be a dict, got {type(resp)}"
            raise TypeError(msg)
        perms = resp["permissions"]
        if not isinstance(perms, dict):
            msg = f"expected response['permissions'] to be a dict, got {type(perms)}"
            raise TypeError(msg)
        if "push" not in perms:
            msg = f"expected 'push' key in permissions, got keys: {perms.keys()}"
            raise KeyError(msg)
        perms = cast("dict[Literal['push'], object]", perms)
        if not isinstance(perms["push"], bool):
            msg = f"expected 'push' permission to be a bool, got {type(perms['push'])}"
            raise TypeError(msg)
        return perms["push"]

    def merge_pr(self, pr: int, expected_head_sha: str | None = None) -> JSONType:
        "Merge a PR. Requires maintainer access to Nixpkgs"
        print(f"Merging {pr_url(pr)}")
        node_id = self.pull_request(pr)["node_id"]
        q = dedent(f"""
        mutation EnqueuePR {{
            enablePullRequestAutoMerge(input: {{
                pullRequestId: "{node_id}",
                {f'expectedHeadOid: "{expected_head_sha}"' if expected_head_sha else ""}
            }}) {{
                clientMutationId
            }}
        }}
        """)
        return self.graphql(q)

    def graphql(self, query: str) -> dict[str, Any]:
        """Execute a GraphQL query and return the data portion of the response."""
        resp = self.post("/graphql", data={"query": query})
        if not isinstance(resp, dict):
            msg = f"Expected response to be a dict, got {type(resp)}"
            raise TypeError(msg)
        if "errors" in resp:
            msg = f"GraphQL query returned errors: {resp}"
            raise RuntimeError(msg)
        if "data" not in resp:
            msg = f"Expected 'data' key in response, got keys: {resp.keys()}"
            raise KeyError(msg)
        data = resp["data"]
        if not isinstance(data, dict):
            msg = f"Expected dict data from graphql api, got {type(data)}"
            raise TypeError(msg)
        return data

    def pull_request(self, number: int) -> GitHubPullRequest:
        "Get a pull request"
        response = self.get(f"repos/NixOS/nixpkgs/pulls/{number}")
        if not isinstance(response, dict):
            msg = f"Expected pull request response to be a dict, got {type(response)}"
            raise TypeError(msg)
        return cast("GitHubPullRequest", response)

    def get_json_from_artifact(self, workflow_id: int, json_filename: str) -> JSONType:
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
            elif e.code == 410:
                msg = dedent(f"""
                GitHub artifact {workflow_id} has expired or been removed
                    * try passing --eval local
                    * try re-running GitHub CI
                """)
                raise ArtifactExpiredError(msg) from e
            else:
                raise
        else:
            msg = f"Expected 302, got {resp.status}"
            raise RuntimeError(msg)

        req = urllib.request.Request(new_url)  # noqa: S310
        with (
            http_requests.urlopen(req) as new_resp,
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
                result: JSONType = json.load(json_file)
                return result

    def _get_workflow_runs(self, commit_sha: str) -> list[Any] | None:
        workflow_runs_resp = self.get(
            f"repos/NixOS/nixpkgs/actions/runs?head_sha={commit_sha}"
        )
        if not isinstance(workflow_runs_resp, dict):
            msg = f"Expected workflow runs response to be a dict, got {type(workflow_runs_resp)}"
            raise TypeError(msg)

        if "workflow_runs" not in workflow_runs_resp:
            return None

        workflow_runs_list = workflow_runs_resp["workflow_runs"]
        if not isinstance(workflow_runs_list, list):
            msg = f"Expected workflow_runs to be a list, got {type(workflow_runs_list)}"
            raise TypeError(msg)

        return cast("list[GitHubWorkflowRun]", workflow_runs_list)

    def _process_comparison_artifact(
        self, artifact_id: int
    ) -> dict[System, set[str]] | None:
        changed_paths = self.get_json_from_artifact(
            workflow_id=artifact_id,
            json_filename="changed-paths.json",
        )
        if not isinstance(changed_paths, dict):
            msg = f"Expected changed_paths to be a dict, got {type(changed_paths)}"
            raise TypeError(msg)

        if (path := changed_paths.get("rebuildsByPlatform")) is not None:
            if not isinstance(path, dict):
                msg = f"Expected rebuildsByPlatform to be a dict, got {type(path)}"
                raise TypeError(msg)
            return {
                # Convert package lists to package sets
                system: set(packages_list)
                for system, packages_list in path.items()
            }
        return None

    def get_github_action_eval_result(
        self, pr: GitHubPullRequest
    ) -> dict[System, set[str]] | None:
        commit_sha = pr["head"]["sha"]
        workflow_runs = self._get_workflow_runs(commit_sha)

        if not workflow_runs:
            return None

        for workflow_run in workflow_runs:
            # "Eval" could be removed after a transition period, when
            # all pull requests run with the new PR workflow.
            if workflow_run["name"] not in ("Eval", "PR"):
                continue

            artifacts_resp = self.get(workflow_run["artifacts_url"])
            if not isinstance(artifacts_resp, dict):
                msg = f"Expected artifacts response to be a dict, got {type(artifacts_resp)}"
                raise TypeError(msg)

            if "artifacts" not in artifacts_resp:
                msg = f"Expected 'artifacts' key in response, got keys: {artifacts_resp.keys()}"
                raise KeyError(msg)

            artifacts_list = artifacts_resp["artifacts"]
            if not isinstance(artifacts_list, list):
                msg = f"Expected artifacts to be a list, got {type(artifacts_list)}"
                raise TypeError(msg)

            artifacts = cast("list[GitHubArtifact]", artifacts_list)

            for artifact in artifacts:
                if artifact["name"] != "comparison":
                    continue
                result = self._process_comparison_artifact(artifact["id"])
                if result is not None:
                    return result

        return None
