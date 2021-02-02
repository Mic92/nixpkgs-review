import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Callable, List, Optional, Union

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
