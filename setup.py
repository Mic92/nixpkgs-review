#!/usr/bin/env python

from setuptools import setup, find_packages

setup(
    name="nix-review",
    version="0.0.1",
    description="Review nixpkgs pull requests",
    author="Jörg Thalheim",
    author_email="joerg@thalheim.io",
    url="https://github.com/Mic92/nix-review",
    license="MIT",
    packages=find_packages(),
    entry_points={
      "console_scripts": ["nix-review = nix_review:main"],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Topic :: Utilities",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.6",
    ]
)
