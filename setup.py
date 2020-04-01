#!/usr/bin/env python

import sys

from setuptools import find_packages, setup

assert sys.version_info >= (3, 6, 0), "nixpkgs-review requires Python 3.6+"

setup(
    name="nixpkgs-review",
    version="2.2.0",
    description="Review nixpkgs pull requests",
    author="Jörg Thalheim",
    author_email="joerg@thalheim.io",
    url="https://github.com/Mic92/nixpkgs-review",
    license="MIT",
    packages=find_packages(),
    package_data={"nixpkgs_review": ["nix/*.nix"]},
    entry_points={
        "console_scripts": [
            "nix-review = nixpkgs_review:main",
            "nixpkgs-review = nixpkgs_review:main",
        ]
    },
    install_requires=["PyGithub"],
    extras_require={"dev": ["mypy", "flake8>=3.5,<3.6", "black"]},
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Topic :: Utilities",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.6",
    ],
)
