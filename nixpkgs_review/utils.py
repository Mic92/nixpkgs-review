import functools
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

HAS_TTY = sys.stdout.isatty()
ROOT = Path(os.path.dirname(os.path.realpath(__file__)))

System: type = str


def color_text(code: int, file: IO[Any] | None = None) -> Callable[[str], None]:
    def wrapper(text: str) -> None:
        if HAS_TTY:
            print(f"\x1b[{code}m{text}\x1b[0m", file=file)
        else:
            print(text, file=file)

    return wrapper


warn = color_text(31, file=sys.stderr)
info = color_text(32)
skipped = color_text(33)
link = color_text(34)


def sh(
    command: list[str], cwd: Path | str | None = None
) -> "subprocess.CompletedProcess[str]":
    info("$ " + shlex.join(command))
    return subprocess.run(command, cwd=cwd, text=True)


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
    "Return `nom` and `nom-shell` if found in $PATH"
    if shutil.which("nom") and shutil.which("nom-shell"):
        return "nom"

    return "nix"


def system_order_key(system: System) -> str:
    """
    For a consistent UI, we keep the platforms sorted as such:
    - x86_64-linux
    - aarch64-linux
    - x86_64-darwin
    - aarch64-darwin

    This helper turns a system name to an alias which can then be sorted in the anti-alphabetical order.
    (i.e. should be used in `sort` with `reverse=True`)

    Example:
    `aarch64-linux` -> `linuxaarch64`
    """
    return "".join(reversed(system.split("-")))
