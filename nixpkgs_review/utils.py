from __future__ import annotations

import functools
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

HAS_TTY = sys.stdout.isatty()
ROOT = Path(__file__).resolve().parent

type System = str


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


def to_link(uri: str, text: str) -> str:
    if HAS_TTY:
        return f"\u001b]8;;{uri}\u001b\\{text}\u001b]8;;\u001b\\"
    return text


def sh(
    command: list[str],
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    *,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        info("$ " + shlex.join(command))
    env = os.environ | env if env else None
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        check=False,
        env=env,
        input=stdin,
        stdout=stdout,
        stderr=stderr,
    )


def escape_attr(attr: str) -> str:
    parts = attr.split(".")
    return ".".join([parts[0], *(f'"{p}"' for p in parts[1:])])


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
    return "nom" if shutil.which("nom") and shutil.which("nom-shell") else "nix"


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
