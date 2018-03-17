import subprocess


def sh(command, **kwargs):
    print("$ " + ' '.join(command))
    subprocess.check_call(command, **kwargs)
