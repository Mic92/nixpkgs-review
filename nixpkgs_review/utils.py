import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Callable, List, Optional, Union

HAS_TTY = sys.stdout.isatty()
ROOT = Path(os.path.dirname(os.path.realpath(__file__)))


def color_text(code: int, file: Optional[IO[Any]] = None) -> Callable[[str], None]:
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
    attr_parts = attr.split(".")
    first = attr_parts[0]
    rest = [f'"{item}"' for item in attr_parts[1:]]
    return ".".join([first, *rest])


@functools.lru_cache(maxsize=1)
def current_system() -> str:
    system = subprocess.run(
        [
            "nix",
            "--extra-experimental-features",
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


def nix_nom_tool() -> str:
    "Return `nom` if found in $PATH"
    if shutil.which("nom"):
        return "nom"
    else:
        return "nix"
