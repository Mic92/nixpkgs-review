import subprocess
from pathlib import Path

from .errors import NixpkgsReviewError
from .utils import sh


def run(
    command: list[str],
    cwd: Path | str | None = None,
    stdin: str | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    *,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with nixpkgs-review identity."""
    env = {
        "GIT_AUTHOR_NAME": "nixpkgs-review",
        "GIT_AUTHOR_EMAIL": "nixpkgs-review@example.com",
        "GIT_COMMITTER_NAME": "nixpkgs-review",
        "GIT_COMMITTER_EMAIL": "nixpkgs-review@example.com",
    }
    return sh(
        ["git", *command],
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        quiet=quiet,
    )


def verify_commit_hash(commit: str) -> str:
    """Verify and return full commit hash."""
    cmd = ["rev-parse", "--verify", commit]
    proc = run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, quiet=True)
    if proc.returncode != 0:
        error_message = f"Failed to verify commit hash '{commit}': {proc.stderr or 'Invalid commit'}"
        raise NixpkgsReviewError(error_message)
    return proc.stdout.strip()
