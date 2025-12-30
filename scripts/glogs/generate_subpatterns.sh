#!/bin/bash
set -eu
set -o pipefail

pattern=$(realpath $1)
outdir=$(pwd)/$2

workspace=$(realpath $(dirname $0)/../../)

$workspace/glogs/ir/target/release/generate_subpatterns -p $pattern -o $outdir