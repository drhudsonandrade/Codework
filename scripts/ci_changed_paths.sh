#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: ci_changed_paths.sh BASE_SHA HEAD_SHA CHANGED_OUT DELETED_OUT" >&2
  exit 2
fi

base_sha=$1
head_sha=$2
changed_out=$3
deleted_out=$4
sha_re='^[0-9a-fA-F]{40}$'

if [[ ! $base_sha =~ $sha_re ]] || [[ ! $head_sha =~ $sha_re ]]; then
  echo "base/head must be full 40-hex Git SHAs" >&2
  exit 2
fi

null_sha=0000000000000000000000000000000000000000
if [ "$base_sha" = "$null_sha" ]; then
  git ls-tree -r --name-only -z "$head_sha" -- > "$changed_out"
  : > "$deleted_out"
  exit 0
fi
git diff --no-renames --name-only -z "$base_sha" "$head_sha" -- > "$changed_out"
git diff --no-renames --diff-filter=D --name-only -z "$base_sha" "$head_sha" -- > "$deleted_out"
