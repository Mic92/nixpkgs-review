#!/usr/bin/env bash

set -eux -o pipefail

escape() { perl -p -e 's/%/%25/;s/\r/%0D/;s/\n/%0A/'; }
ref=${{ github.ref }}
tag_name=${ref#refs/tags/}
release_name=$(git tag -l --format='%(subject)' "$tag_name"  | escape)
body=$(git tag -l --format='%(contents:body)' "$tag_name" | escape)

echo "::set-output name=release_name::$release_name"
echo "::set-output name=body::$body"
