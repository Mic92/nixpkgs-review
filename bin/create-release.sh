#!/usr/bin/env bash

set -eu -o pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
cd $SCRIPT_DIR/..

version=${1:-}
if [[ -z "$version" ]]; then
  echo "USAGE: $0 version" 2>/dev/null
  exit 1
fi

if [[ "$(git symbolic-ref --short HEAD)" != "master" ]]; then
  echo "must be on master branch" 2>/dev/null
  exit 1
fi

sed -i -e "s!version=\".*\"!version=\"${version}\"!" setup.py
git add setup.py
nix-build default.nix
git commit -m "bump version ${version}"
git tag "${version}"

echo 'now run `git push --tags origin master`'
