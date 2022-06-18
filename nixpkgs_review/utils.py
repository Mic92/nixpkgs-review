import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Callable, List, Optional, Union
import functools
from urllib.parse import urlparse, unquote
import re

HAS_TTY = sys.stdout.isatty()
ROOT = Path(os.path.dirname(os.path.realpath(__file__)))


def color_text(code: int, file: IO[Any] = sys.stdout) -> Callable[[str], None]:
    def wrapper(text: str) -> None:
        if HAS_TTY:
            print(f"\x1b[{code}m{text}\x1b[0m", file=file)
        else:
            print(text, file=file)

    return wrapper


warn = color_text(31, file=sys.stderr)
info = color_text(32)
link = color_text(34)


def sh(
    command: List[str], cwd: Optional[Union[Path, str]] = None, check: bool = True
) -> "subprocess.CompletedProcess[str]":
    info("$ " + " ".join(command))
    return subprocess.run(command, cwd=cwd, check=check, text=True)


def verify_commit_hash(commit: str) -> str:
    cmd = ["git", "rev-parse", "--verify", commit]
    proc = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
    return proc.stdout.strip()


def escape_attr(attr: str) -> str:
    index = attr.rfind(".")
    if index == -1:
        return attr
    return f'{attr[:index]}."{attr[index+1:]}"'


@functools.lru_cache(maxsize=1)
def current_system() -> str:
    system = subprocess.run(
        [
            "nix",
            "--experimental-features",
            "nix-command",
            "eval",
            "--impure",
            "--raw",
            "--expr",
            "builtins.currentSystem",
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return system.stdout


class Branch:
    "parse string to branch object"
    remote = "https://github.com/NixOS/nixpkgs"
    owner = "NixOS"
    repo = "nixpkgs"
    #base = "master" # TODO implement? allow comparing to other branches (staging ...)
    branch = None
    commit = None

    def __repr__(self):
        parts = []
        if self.remote.startswith("https://github.com/"):
            parts.append("github")
            parts.append(self.owner)
            parts.append(self.repo)
        # TODO else
        if self.branch:
            parts.append(self.branch)
        elif self.commit:
            parts.append(self.commit)
        return "-".join(parts)

    def set_branch(self, branch, check=True):
        if check:
            if not branch:
                raise Exception(f"failed to parse branch from {repr(self.raw_input)}")
        self.branch = branch

    def set_remote(self, owner=None, repo=None, url=None, check=True):
        if owner and repo:
            self.owner = owner
            self.repo = repo
            self.remote = f"https://github.com/{owner}/{repo}"
            return
        if owner and repo is None:
            self.owner = owner
            self.remote = f"https://github.com/{owner}/nixpkgs"
            return
        if url:
            self.remote = url
            self.owner = None
            self.repo = None
            return
        if check:
            raise Exception(f"failed to parse remote from {repr(self.raw_input)}")

    _commit_expr = r"[0-9a-f]{40}"
    _is_commit = re.compile(_commit_expr).fullmatch

    def set_commit(self, commit):
        if not commit:
            raise Exception(f"failed to parse commit from {repr(raw_input)}")
        if not self._is_commit(commit):
            raise Exception(f"expected commit matching {self._commit_expr}, got {repr(commit)}")
        self.commit = commit



    def __init__(self, raw_input):

        self.raw_input = raw_input

        if not ":" in raw_input:
            # compare a nixpkgs branch to the nixpkgs master branch
            self.set_branch(raw_input)
            # input is not a url, so it's not urlencoded
            #self.branch = unquote(raw_input)
            return

        url = urlparse(raw_input)

        if not url.scheme in {"https", "git", "git+ssh"}: # TODO more?
            # format is user:branch
            # example: alice:a/b-c+d&e%f
            parts = raw_input.split(":")
            if len(parts) != 2:
                raise Exception(f"branch expected format user:branch, got {repr(raw_input)}")
            [owner, branch] = parts
            self.set_branch(branch)
            self.set_remote(owner=owner)

            # input is not a url, so it's not urlencoded
            # copy branch from github webinterface https://github.com/milahu/random/pull/5
            # -> a/b-c+d&e%f(g)hijk=l.m]__@n#op<q>r§t"u'v`w´x;y_z
            #self.branch = unquote(branch)
            return

        if url.netloc != "github.com":
            # TODO implement: gitlab, gitea, ... maybe use https://github.com/nephila/giturlparse
            raise Exception(f"not implemented. branch must be a github url, got {repr(raw_input)}")

        dirs = url.path.split("/")
        #print("dirs =", dirs)

        if len(dirs) < 5:
            raise Exception(f"bad input. could not parse {repr(raw_input)}")

        if dirs[3] == "tree":
            # dirs = ['', 'some-user', 'nixpkgs', 'tree', 'some-branch']
            self.set_remote(owner=dirs[1], repo=dirs[2])
            self.set_branch(unquote("/".join(dirs[4:])))
            return

        if dirs[3] == "commit":
            # dirs = ['', 'NixOS', 'nixpkgs', 'commit', '0000000000000000000000000000000000000000']
            self.set_remote(owner=dirs[1], repo=dirs[2])
            self.set_commit(dirs[4])
            # challenge: find branch of commit. wontfix?
            raise Exception("TODO implement review from commit")
            return

        if dirs[3] == "compare":
            # dirs = ['', 'NixOS', 'nixpkgs', 'compare', 'master...some-user:some-branch']
            if not raw_input.startswith("https://github.com/NixOS/nixpkgs/compare/master.."):
                raise Exception(f"expected github compare link versus nixpkgs master, got {repr(raw_input)}")

            branch = unquote("/".join(dirs[4:]))
            if branch.startswith("master..."):
                branch = branch[9:]
            elif branch.startswith("master.."):
                branch = branch[8:]

            parts = branch.split(":")
            if len(parts) == 2:
                self.set_remote(owner=parts[0])
                self.set_branch(parts[1])
                return
            if len(parts) == 1:
                # remote is NixOS/nixpkgs
                self.set_branch(branch)
                return
            raise Exception(f"expected github compare link with user:branch or branch, got {repr(raw_input)}")

        raise Exception(f"failed to parse branch from {repr(raw_input)}")
