#!/usr/bin/env python3

import pytest
import shutil
import subprocess

from nixpkgs_review.cli import branch
from .conftest import Helpers

# https://pypi.org/project/pytest-snapshot/
# python3 -m pytest --snapshot-update -- tests/test_branch.py
def test_branch_parse_args(snapshot):
    arglist = [
        "staging",
        "alice:patch-1",
        "https://github.com/alice/nixpkgs/commit/a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",
        "https://github.com/NixOS/nixpkgs/compare/master..alice:patch-1",
        "https://github.com/NixOS/nixpkgs/compare/master...alice:patch-1",
        "https://github.com/alice/nixpkgs/tree/patch-1",
        "https://github.com/alice/nixpkgs/tree/a/b/c/d",
        "https://github.com/alice/nixpkgs/tree/github.com/a/b/c/d",
        # illegal chars in branch name: :^,~[\?!
        "https://github.com/NixOS/nixpkgs/compare/master...a/b-c%2Bd%26e%25f(g)hijk%3Dl.m%5D__%40n%23op%3Cq%3Er%C2%A7t%22u'v%60w%C2%B4x%3By_z",
        #"master..alice:patch-1", # TODO impl?
        #"master...alice:patch-1", # TODO impl?
    ]
    actual = []
    for arg in arglist:
        actual.append(f"input: {arg}\noutput: {branch.Branch(arg)}")
    actual = "\n\n".join(actual) + "\n"
    #snapshot.snapshot_dir = 'snapshots'
    snapshot.assert_match(actual, 'parse_args.txt')
