import unittest
import tempfile
import os
import random
import multiprocessing
from unittest.mock import patch, mock_open

from nix_review.app import real_main

TEST_ROOT = os.path.dirname(os.path.realpath(__file__))
DEBUG = False


def read_asset(asset):
    with open(os.path.join(TEST_ROOT, "assets", asset)) as f:
        return f.read()


def expect_side_effects(test, arg_spec):
    arg_spec_iterator = iter(arg_spec)

    def side_effect(*args, **kwargs):
        try:
            (expected_args, ret) = next(arg_spec_iterator)
            if DEBUG:
                print(f"({expected_args}) -> {ret}")
            if expected_args != args[0]:
                print(args[0])
            test.assertEqual(expected_args, args[0])
            return ret
        except StopIteration:
            test.fail(
                f"run out of calls, you can mock it with following arguments:\n({args}, 0)"
            )

    return side_effect

pkg_list = read_asset("package_list_after.txt").encode("utf-8")


def local_eval_cmds():
    return [
       ("https://api.github.com/repos/NixOS/nixpkgs/pulls/1", mock_open(read_data=read_asset("github-pull-1.json"))()),
       ("https://api.github.com/repos/NixOS/nixpkgs/statuses/f5a5915f6e3e1756b4ce78d38c2655a912e156c4", mock_open(read_data=read_asset("github-pull-1-statuses.json"))()),
       (['git', 'fetch', '--force', 'https://github.com/NixOS/nixpkgs', 'master:refs/nix-review/0', 'pull/1/head:refs/nix-review/1'], 0),
       (['git', 'rev-parse', '--verify', 'refs/nix-review/0'], b"hash1"),
       (['git', 'rev-parse', '--verify', 'refs/nix-review/1'], b"hash2"),
       (['git', 'worktree', 'add', './.review/pr-1', 'hash1'], 0),
       (['nix-env', '-f', './.review/pr-1', '-qaP', '--xml', '--out-path', '--show-trace'], b"<items></items>"),
       (['git', 'merge', 'hash2', '--no-commit', '--author', 'Snail Mail <>'], 0),
       (['nix-env', '-f', './.review/pr-1', '-qaP', '--xml', '--out-path', '--show-trace', '--meta'], pkg_list),
    ]

def borg_eval_cmds():
    return [
       ("https://api.github.com/repos/NixOS/nixpkgs/pulls/37200", mock_open(read_data=read_asset("github-pull-37200.json"))()),
       ("https://api.github.com/repos/NixOS/nixpkgs/statuses/aa02248781700e8a4030f1e1c7ee5aa1bd835226", mock_open(read_data=read_asset("github-pull-37200-statuses.json"))()),
       ("https://gist.githubusercontent.com/GrahamcOfBorg/4c9ebc3e608308c6096202375b0dc902/raw/", read_asset("gist-37200.txt").encode("utf-8").split(b"\n")),
       (['git', 'fetch', '--force', 'https://github.com/NixOS/nixpkgs', 'master:refs/nix-review/0', 'pull/37200/head:refs/nix-review/1'], 0),
       (['git', 'rev-parse', '--verify', 'refs/nix-review/0'], b"hash1"),
       (['git', 'rev-parse', '--verify', 'refs/nix-review/1'], b"hash2"),
       (['git', 'worktree', 'add', './.review/pr-37200', 'hash1'], 0),
       (['git', 'merge', 'hash2', '--no-commit', '--author', 'Snail Mail <>'], 0),
       (['nix', 'eval', '--raw', 'nixpkgs.system'], b"x86_64-linux"),
   ]

build_cmds = [
   (['nix', 'eval', '--json', '(with import <nixpkgs> {}; {\n\t"pong3d" = (builtins.tryEval "${pong3d}").success;\n})'], b'{"pong3d":true}'),
   (['nix-shell',
     '--no-out-link',
     '--keep-going',
     '--max-jobs', str(multiprocessing.cpu_count()),
     '--option', 'build-use-sandbox', 'true',
     '--run', 'true',
     '--builders', 'ssh://joerg@10.243.29.170 aarch64-linux',
     '-p', 'pong3d'], 0),
   (['nix-shell', '-p', 'pong3d'], 0),
   (['git', 'worktree', 'prune'], 0)
]

class TestStringMethods(unittest.TestCase):
    def setUp(self):
        os.chdir(os.path.join(TEST_ROOT, "assets/nixpkgs"))

    @patch('urllib.request.urlopen')
    @patch('subprocess.Popen')
    @patch('subprocess.check_call')
    @patch('subprocess.check_output')
    def test_pr_local_eval(self, mock_check_output, mock_check_call, mock_popen, mock_urlopen):
        effects = expect_side_effects(self, local_eval_cmds() + build_cmds)
        mock_check_call.side_effect = effects
        mock_popen.stdout.side_effect = effects
        mock_check_output.side_effect = effects
        mock_urlopen.side_effect = effects

        real_main("nix-review", ["--build-args", '--builders "ssh://joerg@10.243.29.170 aarch64-linux"', "pr", "1"])

    @patch('urllib.request.urlopen')
    @patch('subprocess.Popen')
    @patch('subprocess.check_call')
    @patch('subprocess.check_output')
    def test_pr_borg_eval(self, mock_check_output, mock_check_call, mock_popen, mock_urlopen):
        effects = expect_side_effects(self, borg_eval_cmds() + build_cmds)
        mock_check_call.side_effect = effects
        mock_popen.stdout.side_effect = effects
        mock_check_output.side_effect = effects
        mock_urlopen.side_effect = effects

        real_main("nix-review", ["--build-args", '--builders "ssh://joerg@10.243.29.170 aarch64-linux"', "pr", "37200"])


if __name__ == '__main__':
    unittest.main(failfast=True)
