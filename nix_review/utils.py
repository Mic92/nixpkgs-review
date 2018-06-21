import subprocess
from typing import List, Optional


def sh(command: List[str], cwd: Optional[str] = None) -> None:
    print("$ " + ' '.join(command))
    subprocess.check_call(command, cwd=cwd)
