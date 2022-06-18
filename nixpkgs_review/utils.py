import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Callable, List, Optional, Union
import functools
from urllib.parse import urlparse, unquote

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
    #base = "master" # TODO implement? allow comparing to other branches (staging ...)
    branch = None
    commit = None

    def __repr__(self):
        return f"Branch:\n  remote: {self.remote}\n  branch: {self.branch}\n  commit: {self.commit}"

    def __init__(self, raw_input):

        if not ":" in raw_input:
            # compare a nixpkgs branch to the nixpkgs master branch
            self.branch = raw_input
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
            self.remote = f"https://github.com/{owner}/nixpkgs"
            self.branch = branch
            # input is not a url, so it's not urlencoded
            # copy branch from github webinterface https://github.com/milahu/random/pull/5
            # -> a/b-c+d&e%f(g)hijk=l.m]__@n#op<q>r§t"u'v`w´x;y_z
            #self.branch = unquote(branch)
            return

        if url.netloc != "github.com":
            # TODO implement: gitlab, gitea, ... maybe use https://github.com/nephila/giturlparse
            raise Exception(f"not implemented. branch must be a github url, got {repr(raw_input)}")

        dirs = url.path.split("/")

        if dirs[2] != "nixpkgs":
            raise Exception(f"branch repo name must be nixpkgs, got {repr(raw_input)}")

        if dirs[3] == "tree":
            self.branch = unquote("/".join(dirs[4:]))
            return

        if dirs[3] == "commit":
            self.commit = dirs[4]
            owner = dirs[1]
            self.remote = f"https://github.com/{owner}/nixpkgs"
            return

        if dirs[3] == "compare":
            if not raw_input.startswith("https://github.com/NixOS/nixpkgs/compare/master.."):
                raise Exception(f"expected github compare link versus nixpkgs master, got {repr(raw_input)}")

            branch = unquote("/".join(dirs[4:]))
            if branch.startswith("master..."):
                branch = branch[9:]
            elif branch.startswith("master.."):
                branch = branch[8:]

            parts = branch.split(":")
            if len(parts) == 2:
                [owner, branch] = parts
                self.remote = f"https://github.com/{owner}/nixpkgs"
                self.branch = branch
                return
            if len(parts) == 1:
                # remote is NixOS/nixpkgs
                self.branch = branch
                return
            raise Exception(f"expected github compare link with user:branch or branch, got {repr(raw_input)}")

        raise Exception(f"failed to parse branch from {repr(raw_input)}")
