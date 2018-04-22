import subprocess
from typing import List


def sh(command: List[str], **kwargs) -> None:
    print("$ " + ' '.join(command))
    subprocess.check_call(command, **kwargs)
