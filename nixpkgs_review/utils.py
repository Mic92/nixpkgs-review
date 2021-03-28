import os
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Optional, Union

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
    command: List[str],
    cwd: Optional[Union[Path, str]] = None,
    check: bool = True,
    stdout: Any = None,
    stderr: Any = None,
    input: Optional[str] = None,
    **kwargs: Dict[str, Any],
) -> "subprocess.CompletedProcess[str]":
    start_time = time.time()
    info("$ " + " ".join(command))
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        return subprocess.run(  # type: ignore
            command,
            cwd=cwd,
            check=check,
            text=True,
            stdout=stdout,
            stderr=stderr,
            input=input,
            **kwargs,
        )
    finally:
        elapsed = time.time() - start_time
        if elapsed > 120.0:
            info(f"{command[0]} subprocess took {elapsed:.1f} sec")


def verify_commit_hash(commit: str) -> str:
    cmd = ["git", "rev-parse", "--verify", commit]
    proc = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
    return proc.stdout.strip()


def escape_attr(attr: str) -> str:
    index = attr.rfind(".")
    if index == -1:
        return attr
    return f'{attr[:index]}."{attr[index+1:]}"'
